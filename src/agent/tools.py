"""
Định nghĩa "tool" (công cụ) và registry cho agent.

Mỗi Tool = tên + mô tả + JSON schema tham số + hàm thực thi. LLM đọc mô tả +
schema để quyết định gọi tool nào với tham số gì (tool-calling). Registry gom
các tool lại, cung cấp:
  - specs():  danh sách định nghĩa tool để gửi cho LLM
  - run():    thực thi tool theo tên với tham số LLM sinh ra

build_default_registry(actions) dựng sẵn bộ tool điều khiển máy tính từ
AssistantActions (core/actions_facade.py) — tái dùng đúng phần refactor Tầng 2.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from utils.config import config
from utils.logger import get_logger
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

    def spec(self) -> dict:
        """Định nghĩa tool gửi cho LLM (định dạng Anthropic tool-use)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


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

    def run(self, name: str, arguments: dict) -> str:
        """Thực thi tool. Ném KeyError nếu không có tool tên đó."""
        tool = self._tools[name]
        logger.debug("Chạy tool %s(%s)", name, arguments)
        return tool.handler(**(arguments or {}))

# Bộ tool mặc định (điều khiển máy tính) dựng từ AssistantActions
def build_default_registry(actions, profile=None) -> ToolRegistry:
    """Tạo registry điều khiển máy tính từ một facade actions (hoặc mock).

    Nếu truyền `scheduler` (ReminderScheduler) thì đăng ký thêm bộ tool lập lịch.
    Nếu truyền `browser` (BrowserBridge) thì đăng ký thêm tool điều khiển Chrome.
    Nếu truyền `profile` (UserProfile) thì tool thời tiết dùng địa điểm mặc định trong
    hồ sơ (thay cho cấu hình cứng).

    ĐANG THU HẸP DẦN: mỗi feature tách ra `features/<tên>/` lại bớt một tham số ở đây.
    Còn lại là nhóm lõi (system, weather, web) — bước cuối của việc 4 sẽ dọn nốt.
    """
    reg = ToolRegistry()

    reg.register(Tool(
        name="open_app",
        description="Mở một ứng dụng trên máy (ví dụ Chrome, Notepad, Word).",
        input_schema={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Tên ứng dụng cần mở"},
            },
            "required": ["app_name"],
        },
        handler=lambda app_name: actions.open_application(app_name),
        speakable=True,      # "Đã mở Chrome."
    ))

    reg.register(Tool(
        name="close_app",
        description="Đóng một ứng dụng đang chạy. Trợ lý sẽ tự hỏi xác nhận trước khi đóng.",
        input_schema={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Tên ứng dụng cần đóng"},
            },
            "required": ["app_name"],
        },
        handler=lambda app_name: actions.close_application(app_name),
        destructive=True,      # đóng app có thể mất dữ liệu chưa lưu -> chốt xác nhận trong code
        confirm_message=lambda app_name=None: f"đóng ứng dụng {app_name}",
    ))

    reg.register(Tool(
        name="list_windows",
        description="Liệt kê các cửa sổ/ứng dụng ĐANG MỞ trên máy (theo tiêu đề). Dùng khi "
                    "người dùng hỏi 'đang mở những gì', 'có cửa sổ/ứng dụng nào đang chạy', "
                    "hoặc để biết tên cửa sổ trước khi chuyển sang nó.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: actions.list_windows(),
    ))

    reg.register(Tool(
        name="switch_window",
        description="Chuyển sang (đưa RA TRƯỚC) một cửa sổ/ứng dụng ĐANG CHẠY SẴN theo tên, "
                    "vd 'chuyển sang Chrome', 'qua cửa sổ Word', 'mở lại Claude đang mở'. "
                    "KHÁC open_app (mở ứng dụng MỚI) — tool này chỉ focus cửa sổ đã chạy.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Tên/một phần tiêu đề cửa sổ cần chuyển sang"},
            },
            "required": ["name"],
        },
        handler=lambda name: actions.switch_window(name),
    ))

    reg.register(Tool(
        name="set_volume",
        description=("Điều chỉnh âm lượng hệ thống. Dùng 'level' để đặt mức tuyệt "
                     "đối (0-100), hoặc 'change' để tăng/giảm tương đối (số âm để giảm)."),
        input_schema={
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Mức âm lượng 0-100"},
                "change": {"type": "integer", "description": "Thay đổi tương đối, vd 10 hoặc -15"},
            },
        },
        handler=lambda level=None, change=None: actions.control_volume(level=level, change=change),
        speakable=True,      # câu xác nhận ngắn
    ))

    reg.register(Tool(
        name="set_brightness",
        description=("Điều chỉnh độ sáng màn hình. Dùng 'level' để đặt mức tuyệt "
                     "đối (0-100), hoặc 'change' để tăng/giảm tương đối."),
        input_schema={
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Mức độ sáng 0-100"},
                "change": {"type": "integer", "description": "Thay đổi tương đối"},
            },
        },
        handler=lambda level=None, change=None: actions.control_brightness(level=level, change=change),
        speakable=True,
    ))

    # (Đã gỡ tool 'shutdown'/'restart' — tắt/khởi động lại máy quá rủi ro khi STT
    #  nghe nhầm; cố ý không cung cấp cho agent.)

    reg.register(Tool(
        name="system_info",
        description="Xem tình trạng máy tính: RAM, ổ đĩa, CPU, pin.",
        input_schema={
            "type": "object",
            "properties": {
                "what": {"type": "string",
                         "enum": ["all", "memory", "disk", "cpu", "battery"],
                         "description": "Mục cần xem (mặc định all)"},
            },
        },
        handler=lambda what="all": actions.system_info(what),
        speakable=True,      # "RAM: đã dùng 9.8 GB/15.4 GB (64%)..."
    ))

    reg.register(Tool(
        name="web_fetch",
        description="Tải nội dung một trang web theo URL để đọc/tóm tắt. "
                    "Dùng khi người dùng đưa link hoặc muốn tóm tắt một trang cụ thể.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL đầy đủ (http/https)"},
            },
            "required": ["url"],
        },
        handler=lambda url: actions.web_fetch(url),
    ))

    reg.register(Tool(
        name="wikipedia_lookup",
        description="Tra cứu nhanh một chủ đề trên Wikipedia (trả đoạn tóm tắt). "
                    "Dùng khi người dùng hỏi 'X là gì', tra cứu khái niệm/nhân vật.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Chủ đề/từ khóa cần tra"},
            },
            "required": ["topic"],
        },
        handler=lambda topic: actions.wikipedia_lookup(topic),
    ))

    reg.register(Tool(
        name="get_weather",
        description="Xem thời tiết hôm nay ở một địa điểm: mô tả trời, nhiệt độ, khả năng "
                    "mưa, chỉ số tia UV, kèm khuyến nghị (che nắng, mang áo mưa...). Dùng "
                    "khi người dùng hỏi 'thời tiết hôm nay', 'trời có mưa không', 'nắng "
                    "không', 'tia UV mạnh không'. Không nói địa điểm thì để trống.",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string",
                             "description": "Tên thành phố/địa điểm; để trống nếu người "
                                            "dùng không nói (dùng địa điểm mặc định)"},
            },
        },
        handler=lambda location=None: actions.get_weather(
            location or (profile.get_default_location() if profile else None)
            or config.WEATHER_DEFAULT_LOCATION),
        speakable=True,      # đã gồm mô tả trời + khuyến nghị + ghi nguồn
    ))

    reg.register(Tool(
        name="open_website",
        description="Mở một trang web trong trình duyệt.",
        input_schema={
            "type": "object",
            "properties": {
                "website": {"type": "string", "description": "Tên hoặc URL trang web"},
            },
            "required": ["website"],
        },
        handler=lambda website: actions.open_website(website),
    ))

    reg.register(Tool(
        name="web_search",
        description="Tìm kiếm trên web với engine chỉ định.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung tìm kiếm"},
                "engine": {"type": "string", "enum": ["google", "bing", "youtube"],
                           "description": "Công cụ tìm kiếm (mặc định google)"},
            },
            "required": ["query"],
        },
        handler=lambda query, engine="google": actions.search_web(query, engine),
    ))

    reg.register(Tool(
        name="play_youtube",
        description="Tìm và phát một video/bài hát trên YouTube.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Tên video/bài hát"},
            },
            "required": ["query"],
        },
        handler=lambda query: actions.search_and_play_youtube_direct(query),
    ))

    reg.register(Tool(
        name="search_on_site",
        description="Tìm kiếm nội dung trên một trang cụ thể (facebook, youtube, github...).",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung tìm kiếm"},
                "site": {"type": "string", "description": "Tên trang, vd facebook, youtube"},
            },
            "required": ["query", "site"],
        },
        handler=lambda query, site: actions.search_on_specific_site(query, site),
    ))

    return reg

