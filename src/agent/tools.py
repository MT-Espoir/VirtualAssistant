"""
Định nghĩa "tool" (công cụ) và registry cho agent.

Mỗi Tool = tên + mô tả + JSON schema tham số + hàm thực thi. LLM đọc mô tả +
schema để quyết định gọi tool nào với tham số gì (tool-calling). Registry gom
các tool lại, cung cấp:
  - specs():  danh sách định nghĩa tool để gửi cho LLM
  - run():    thực thi tool theo tên với tham số LLM sinh ra

Registry KHÔNG còn tự biết tool nào tồn tại: mỗi tính năng tự đăng ký tool của mình
qua hợp đồng ở `features/contract.py`, và `features/registry.py::build_registry` gom
chúng lại theo danh mục `features/catalog.py`.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from utils.config import config
from utils.logger import get_logger
from utils.outbound import mo_ta_ra_ngoai
from utils.text_norm import strip_accents

logger = get_logger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict          # JSON Schema cho tham số
    handler: Callable[..., str]  # nhận **kwargs theo schema, trả về chuỗi
    destructive: bool = False    # True = khó hoàn tác -> Agent hỏi xác nhận trước khi chạy
    confirm_message: Callable[..., str] = None  # (**args) -> cụm mô tả việc sẽ làm, để hỏi
    # (**args) -> dict để HIỆN RA cho người dùng xem trước khi xác nhận, hoặc None nếu
    # không có gì đáng xem. Chỉ có nghĩa với tool destructive (Agent gọi lúc hoãn hành
    # động). Dùng cho nội dung mà TAI không kiểm được — thư dài, văn bản do LLM viết ra.
    preview: Callable[..., dict] = None
    # True = kết quả trả về ĐÃ là câu tiếng Việt hoàn chỉnh, đọc thẳng cho người dùng được.
    # Agent dùng cờ này để BỎ lượt LLM soạn lời (tiết kiệm 1 call) — chỉ khi model gọi đúng
    # MỘT tool này và không làm gì thêm. Đánh đổi: câu trả lời không mang giọng persona,
    # nên chỉ bật cho tool mà output vốn đã tự nhiên. KHÔNG bật cho tool cần diễn giải
    # (tìm web, đọc mail, tóm tắt trang).
    speakable: bool = False

    # True = kết quả tool chứa nội dung do BÊN NGOÀI kiểm soát (trang web, email, tiêu đề
    # tab, chữ OCR trên màn hình, review địa điểm). Agent sẽ bọc nó lại và báo cho model
    # biết đó là DỮ LIỆU chứ không phải lệnh — xem `agent/untrusted.py`.
    # Không ảnh hưởng `spec()`: cờ này dành cho ta, không gửi lên LLM.
    untrusted_output: bool = False

    # (tên tham số, mẫu nhãn) — vd ("query", "nghe '{}'"). Có thì mỗi lần chạy THÀNH CÔNG,
    # Agent đếm thêm một lần cho giá trị tham số đó vào kho thói quen (`memory/habits.py`),
    # nhờ vậy trợ lý biết "hay nghe bài gì", "hay mở app nào" mà không cần người dùng nói.
    # Đặt ngay tại tool thay vì một bảng tên-tool ở chỗ khác: bảng chép tay là nguồn sự
    # thật thứ hai, đổi tên tool một cái là nó lệch trong im lặng.
    habit: tuple = None

    # --- Hai trục RỦI RO ngoài "khó hoàn tác" -------------------------------------------
    # Cổng duyệt ban đầu chỉ hỏi "có khó hoàn tác không?". Đợt soi bảo mật 2026-08-29 cho
    # thấy mọi lỗ hổng còn lại nằm ở hai câu hỏi KHÔNG được hỏi. Xem
    # `docs/security_review_2026-08-29.md`.
    #
    # RÒ RỈ: tool đưa chuỗi do model sinh ra tới một đích NGOÀI máy (URL, truy vấn tìm
    # kiếm). Nó không "phá" gì nên lọt hết mọi heuristic destructive — nhưng dữ liệu đã đi
    # thì không gọi về được. Đây là kênh rò rỉ thật: hồ sơ người dùng nằm sẵn trong ngữ
    # cảnh, kẻ tấn công chỉ cần bảo model nhét nó vào một URL.
    exfil: bool = False

    # BỀN VỮNG: tool ghi thứ sẽ QUAY LẠI prompt ở các lượt sau (trí nhớ dài hạn, danh bạ,
    # routine). Nguy hiểm vì nó biến một lần tiêm thành chỗ đứng lâu dài — mọi lỗ khác chỉ
    # sống một lượt, lỗ này cắm rễ qua nhiều phiên.
    persistent: bool = False

    def spec(self) -> dict:
        """Định nghĩa tool gửi cho LLM (định dạng Anthropic tool-use)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class NeedsConfirmation(Exception):
    """Lời gọi cần người dùng duyệt nhưng chưa được duyệt -> handler KHÔNG chạy.

    Mang theo đủ thứ để đi hỏi, nên nơi bắt được ngoại lệ này không phải tra lại registry
    mới biết hỏi câu gì. Nhận thẳng dict `gate()` trả về (`**can_duyet`).
    """

    def __init__(self, name, arguments, phrase, preview=None):
        super().__init__(f"Tool {name!r} cần xác nhận trước khi chạy")
        self.name = name
        self.arguments = arguments
        self.phrase = phrase
        self.preview = preview


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool trùng tên: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> List[str]:
        """Tên tool THEO ĐÚNG thứ tự đăng ký (dict giữ thứ tự chèn).

        Bộ nạp feature so tên trước/sau khi gọi `register` để biết feature nào đăng ký
        tool nào — nhờ vậy `CASE_TOOLS` suy ra được thay vì chép tay.
        """
        return list(self._tools)

    def specs(self) -> List[dict]:
        return [t.spec() for t in self._tools.values()]

    def gate(self, name: str, arguments: dict, nhiem: bool = False) -> dict:
        """{name, arguments, phrase, preview} nếu lời gọi này CẦN duyệt; None nếu không.

        `nhiem=True` = ngữ cảnh lượt này ĐÃ chạm nội dung ngoài (web/email/OCR). Khi đó
        tool `exfil` hoặc `persistent` cũng phải duyệt.

        Vì sao gác theo VẾT NHIỄM chứ không gác mọi lúc: nguy hiểm không nằm ở việc tải
        một URL, mà ở việc tải một URL DO NỘI DUNG NGOÀI MỚM CHO. Gác mọi lúc thì mỗi lần
        nhờ tóm tắt một trang đều phải xác nhận — người dùng sẽ bấm "có" theo phản xạ, và
        cổng mất hết giá trị đúng lúc cần nó nhất.

        `nhiem` do NƠI GỌI đưa vào, không phải registry tự biết: fast-path và nút trên
        panel đến thẳng từ hành động của người dùng, không qua model, nên chúng luôn sạch.

        NƠI DUY NHẤT giữ chính sách duyệt. Agent vẫn tự duyệt cả lô trước khi chạy lô,
        nhưng gọi hàm này chứ không đọc cờ lần nữa — hai chỗ đọc cờ là hai chỗ để lệch.

        HAI lý do phải duyệt, chỉ cần một là đủ:
          1. tool `destructive` — khó hoàn tác (đóng app, gửi thư, xoá việc);
          2. tool dựng được BẢN XEM TRƯỚC — có nội dung do LLM viết ra mà người dùng phải
             đọc bằng mắt mới kiểm được. Không thừa: `gws_gmail_draft` không chứa từ khoá
             GHI nào nên (1) xếp nó là "chỉ đọc", trong khi "viết mail" chính là lúc cần
             nhìn bản nháp nhất.

        Tên tool không có -> None (không phải việc của cổng; `run` sẽ ném KeyError).
        """
        tool = self._tools.get(name)
        if tool is None:
            return None
        args = arguments or {}
        try:
            preview = tool.preview(**args) if tool.preview else None
        except Exception as e:            # dựng bản xem trước lỗi -> coi như không có
            logger.warning("Không dựng được bản xem trước cho %s: %s", name, e)
            preview = None
        can_duyet = tool.destructive or bool(preview)
        if nhiem and (tool.exfil or tool.persistent):
            can_duyet = True
            # CỔNG tự dựng bản xem trước, thay vì gắn `preview` vào từng tool `exfil`: gắn
            # vào tool thì luật "có preview => duyệt" ở trên sẽ bắt hỏi cả ở LƯỢT SẠCH,
            # phá mất chính điều kiện khiến cổng này có giá trị (hỏi hiếm thì người ta
            # còn đọc; hỏi luôn thì họ bấm "có" theo phản xạ).
            if preview is None:
                preview = mo_ta_ra_ngoai(args)
        if not can_duyet:
            return None
        try:
            phrase = tool.confirm_message(**args) if tool.confirm_message else name
        except Exception:                 # confirm_message lỗi -> vẫn hỏi, dùng tên tool
            phrase = name
        return {"name": name, "arguments": args, "phrase": phrase, "preview": preview}

    def run(self, name: str, arguments: dict, confirmed: bool = False,
            nhiem: bool = False) -> str:
        """Thực thi tool. Ném KeyError nếu không có tool tên đó.

        Chưa `confirmed` mà `gate()` bảo cần duyệt -> ném `NeedsConfirmation`, handler
        KHÔNG chạy. Cổng đặt ở ĐÂY chứ không chỉ ở vòng lặp agent vì đây là chỗ MỌI đường
        gọi đi qua: fast-path và nút trên panel gọi thẳng registry, còn các bề mặt tool
        sau này (meta-tool, code) không có `tool_calls` để agent soi. Xem
        `docs/tool_surface_spec.md` §5.
        """
        tool = self._tools[name]
        if not confirmed:
            can_duyet = self.gate(name, arguments, nhiem=nhiem)
            if can_duyet is not None:
                raise NeedsConfirmation(**can_duyet)
        logger.debug("Chạy tool %s(%s)", name, arguments)
        return tool.handler(**(arguments or {}))

# Bộ tool mặc định (điều khiển máy tính) dựng từ AssistantActions
