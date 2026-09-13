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
    # True = khó hoàn tác -> Agent hỏi xác nhận trước khi chạy.
    #
    # Nhận cả CALLABLE `(**args) -> bool`, cùng lối với `confirm_message`/`preview` ngay
    # dưới. Cần cho tool gom nhiều hành động khác nhau về rủi ro vào một enum — ngân sách
    # spec đẩy ta về phía gom (xem `docs/system_admin_spec.md` §2–3), mà cờ tĩnh thì
    # `power(action=lock|shutdown)` chỉ có hai kết cục và cả hai đều sai: hoặc tắt máy
    # không hỏi, hoặc khoá màn hình cũng phải xác nhận.
    destructive: "bool | Callable[..., bool]" = False
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

    # QUẢN TRỊ: tool đụng tới chính cái máy chứ không tới dữ liệu (kết thúc tiến trình,
    # tắt/khởi động lại máy). Khác `destructive` ở BẬC thiệt hại, nên khác cả cách xử:
    # `destructive` thì HỎI, `admin` gặp lượt nhiễm thì TỪ CHỐI THẲNG — xem `gate()` và
    # `docs/system_admin_spec.md` §7. Gửi nhầm một email còn xin lỗi được; kill nhầm tiến
    # trình đang lưu file thì không.
    admin: bool = False

    # TỰ ĐỘNG: tool được phép chạy trên đường trợ lý TỰ khởi xướng (vòng nền chủ động),
    # nơi KHÔNG có lượt nào để hỏi ai cả. Mặc định False, và đó là mặc định đúng: thêm
    # tool mới thì nó nằm ngoài đường tự động cho tới khi có người cân nhắc đưa vào.
    #
    # Điều kiện để bật, ghi ở đây vì đây là chỗ người ta nhìn khi định bật nó: hành động
    # phải HOÀN TÁC ĐƯỢC BẰNG MỘT CÂU NÓI. `set_brightness` đạt (hạ sáng rồi bảo "sáng
    # lên" là xong); `kill_process` và `power` thì vĩnh viễn không — một hành động khó
    # hoàn tác do máy tự quyết định thì không còn ai chịu trách nhiệm cho nó.
    # Xem `docs/system_admin_spec.md` §5.3.
    tu_dong: bool = False

    # CẤM CỨNG: `(**args) -> lý do | None`. Trả về chuỗi thì lời gọi KHÔNG chạy, kể cả khi
    # người dùng đã đồng ý — khác `destructive` ở đúng điểm đó.
    #
    # Vì sao cần một trục nữa: hai lớp kia (`admin` + `gate`) đều quy về "hỏi người dùng",
    # mà xác nhận dựa vào việc người dùng tỉnh táo đúng lúc. Người đang bận trả lời "ừ"
    # theo phản xạ thì cả hai lớp đã làm đúng việc của mình mà máy vẫn hỏng. Nên phải có
    # những thứ KHÔNG cửa nào mở được. Xem `docs/system_admin_spec.md` §7 lớp 3.
    cam: Callable[..., str] = None

    # Nhóm feature sở hữu tool, do `load_features()` gắn sau khi đăng ký. Metadata này
    # chỉ dùng để đo phân bố sử dụng thật; `spec()` cố ý không gửi nó lên LLM. Đặt cuối
    # để không đổi ý nghĩa các lời gọi `Tool(...)` positional cũ.
    group: str = None

    def spec(self) -> dict:
        """Định nghĩa tool gửi cho LLM (định dạng Anthropic tool-use)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def _co(flag, args):
    """Đọc một cờ rủi ro: callable thì gọi với `args`, không thì đọc thẳng.

    Callable nổ -> coi như CÓ. Cờ rủi ro hỏng thì hỏi thừa một câu là phiền; đoán là
    "không nguy hiểm" rồi chạy thẳng mới là hỏng thật.
    """
    if callable(flag):
        try:
            return bool(flag(**(args or {})))
        except Exception:
            logger.warning("Cờ rủi ro lỗi khi chấm %r -> coi như cần duyệt", args,
                           exc_info=True)
            return True
    return bool(flag)


class ActionRefused(Exception):
    """Lời gọi bị TỪ CHỐI THẲNG — không phải "hỏi rồi làm", mà là không làm.

    Khác `NeedsConfirmation` ở chỗ không có đường đi tiếp: người dùng đáp "có" cũng không
    mở được. Mang theo câu nói được để nơi bắt đọc thẳng cho người dùng nghe.
    """

    def __init__(self, name, arguments, ly_do):
        super().__init__(f"Tool {name!r} bị từ chối: {ly_do}")
        self.name = name
        self.arguments = arguments
        self.ly_do = ly_do


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

    def tu_choi(self, name: str, arguments: dict, nhiem: bool = False,
                tu_dong: bool = False) -> str:
        """Lý do lời gọi này KHÔNG được phép chạy, hoặc None nếu được phép.

        Tách hẳn khỏi `gate()` vì đây là câu hỏi khác: `gate()` hỏi *có phải hỏi người
        dùng không*, hàm này hỏi *có được làm không*. Nhập hai câu đó vào một giá trị trả
        về thì nơi gọi phải phân biệt bằng hình dạng dict — đúng thứ về sau đọc nhầm.

        Ba luật, cùng một lý do nền: có những lúc cổng xác nhận KHÔNG dùng được, và lúc
        đó câu trả lời phải là "không", không phải "hỏi kỹ hơn".

        1. Tool `admin` gặp lượt đã chạm nội dung ngoài -> từ chối, KHÔNG hỏi thêm
           (`docs/system_admin_spec.md` §7 lớp 1). Xác nhận bằng giọng là lớp phòng thủ
           chính của hệ này, mà nó dựa vào việc người dùng tỉnh táo đúng lúc; không nên
           để nó là thứ duy nhất đứng trước một lệnh tắt máy do trang web mớm vào.
        2. Đường TỰ ĐỘNG chỉ chạy tool có cờ `tu_dong` (§5.3). Ở đây cổng duyệt không
           thủng — nó đơn giản là KHÔNG TỒN TẠI, vì cả `gate()` lẫn vết nhiễm đều dựng
           quanh hình dạng *người dùng hỏi → xác nhận → chạy* mà đường tự động thiếu hẳn
           vế đầu. Nên chặn bằng danh sách trắng, không bằng cách hỏi.
        3. `tool.cam(**args)` trả lý do -> cấm cứng, không cửa nào mở (§7 lớp 3). Khác hai
           luật trên ở chỗ nó xét THAM SỐ chứ không xét ngữ cảnh: cùng một tool, tắt máy
           lúc bình thường thì được, tắt máy giữa lúc Windows đang cài cập nhật thì không.
        """
        tool = self._tools.get(name)
        if tool is None:
            return None
        if nhiem and tool.admin:
            return ("lượt này đã đọc nội dung từ bên ngoài nên tôi không tự ý đụng vào máy; "
                    "bạn nói lại giúp tôi ở lượt sau nhé")
        if tu_dong and not tool.tu_dong:
            return f"tôi không được tự ý làm việc '{name}' khi bạn chưa bảo"
        if tool.cam is not None:
            try:
                return tool.cam(**(arguments or {})) or None
            except Exception:      # lệnh cấm hỏng -> cấm. Cùng lối fail-closed với `_co`.
                logger.warning("Lệnh cấm của %s lỗi -> từ chối cho chắc", name, exc_info=True)
                return f"tôi không kiểm được việc '{name}' lúc này có an toàn không"
        return None

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
        can_duyet = _co(tool.destructive, args) or bool(preview)
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
            nhiem: bool = False, tu_dong: bool = False) -> str:
        """Thực thi tool. Ném KeyError nếu không có tool tên đó.

        Chưa `confirmed` mà `gate()` bảo cần duyệt -> ném `NeedsConfirmation`, handler
        KHÔNG chạy. Cổng đặt ở ĐÂY chứ không chỉ ở vòng lặp agent vì đây là chỗ MỌI đường
        gọi đi qua: fast-path và nút trên panel gọi thẳng registry, còn các bề mặt tool
        sau này (meta-tool, code) không có `tool_calls` để agent soi. Xem
        `docs/tool_surface_spec.md` §5.

        `tu_dong=True` = lời gọi đến từ vòng nền chủ động, KHÔNG từ người dùng. Cờ này chỉ
        SIẾT chứ không bao giờ nới: nó thêm một luật từ chối, và cố ý KHÔNG hàm ý
        `confirmed` — tool tự động nào lỡ thành `destructive` thì nó dừng lại ở đây chứ
        không âm thầm chạy, vì đường này không có ai để hỏi.
        """
        tool = self._tools[name]
        # Từ chối xét TRƯỚC `confirmed`: đây là thứ một câu "có" không mở được, nên nó
        # phải đứng trên cả đường đã-được-duyệt.
        ly_do = self.tu_choi(name, arguments, nhiem=nhiem, tu_dong=tu_dong)
        if ly_do is not None:
            raise ActionRefused(name, arguments, ly_do)
        if not confirmed:
            can_duyet = self.gate(name, arguments, nhiem=nhiem)
            if can_duyet is not None:
                raise NeedsConfirmation(**can_duyet)
        logger.debug("Chạy tool %s(%s)", name, arguments)
        return tool.handler(**(arguments or {}))

# Bộ tool mặc định (điều khiển máy tính) dựng từ AssistantActions
