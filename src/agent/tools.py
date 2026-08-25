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


def _first_number(value):
    """Rút số đầu tiên trong value (số hoặc chuỗi kiểu '5', '5 phút'). None nếu không có."""
    m = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(m.group().replace(",", ".")) if m else None


def _relative_from_text(text, now):
    """'5 phút' / 'sau 2 tiếng' / '30 giây' -> datetime. None nếu không có số."""
    low = strip_accents(str(text).lower())
    n = _first_number(low)
    if n is None:
        return None
    if "gio" in low or "tieng" in low or "hour" in low:
        return now + timedelta(hours=n)
    if "giay" in low or "sec" in low:
        return now + timedelta(seconds=n)
    return now + timedelta(minutes=n)          # mặc định coi là phút


def _parse_fire_time(delay_minutes=None, at=None, now=None):
    """Tính thời điểm nhắc — CHỊU LỖI với tham số lộn xộn do model sinh ra.

    delay_minutes: số hoặc chuỗi có số ('5', '5 phút'). at: ISO, 'HH:MM', hoặc cả cụm
    tương đối lọt vào đây ('sau 5 phút', '2 tiếng'). Trả datetime, hoặc None.
    """
    now = now or datetime.now()

    if delay_minutes is not None:
        n = _first_number(delay_minutes)
        if n is not None:
            return now + timedelta(minutes=n)

    if at:
        at = str(at).strip()
        try:                                    # ISO đầy đủ, vd 2026-07-25T15:00
            return datetime.fromisoformat(at)
        except ValueError:
            pass
        m = re.match(r"^(\d{1,2})\s*[:hg]\s*(\d{1,2})", at)   # HH:MM / HHhMM / HHgMM
        if m:
            fire = now.replace(hour=int(m.group(1)) % 24, minute=int(m.group(2)) % 60,
                               second=0, microsecond=0)
            return fire + timedelta(days=1) if fire <= now else fire
        rel = _relative_from_text(at, now)      # 'sau 5 phút' lọt vào 'at'
        if rel is not None:
            return rel

    return None


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
def build_default_registry(actions, scheduler=None, browser=None, screen=None,
                           profile=None, tasks=None, routines=None, contacts=None,
                           mcp=None, places=None, location=None, bus=None) -> ToolRegistry:
    """Tạo registry điều khiển máy tính từ một facade actions (hoặc mock).

    Nếu truyền `scheduler` (ReminderScheduler) thì đăng ký thêm bộ tool lập lịch.
    Nếu truyền `browser` (BrowserBridge) thì đăng ký thêm tool điều khiển Chrome.
    Nếu truyền `screen` (ScreenController) thì đăng ký thêm tool đọc/điều khiển màn hình.
    Nếu truyền `profile` (UserProfile) thì đăng ký tool ghi nhớ thông tin người dùng, và
    tool thời tiết dùng địa điểm mặc định trong hồ sơ (thay cho cấu hình cứng).
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

    if scheduler is not None:
        _register_schedule_tools(reg, scheduler)

    if browser is not None:
        _register_browser_tools(reg, browser)
        _register_web_search_tools(reg, browser, actions)

    if screen is not None:
        _register_screen_tools(reg, screen)

    if profile is not None:
        _register_profile_tools(reg, profile)

    if tasks is not None:
        _register_task_tools(reg, tasks)

    if routines is not None:
        _register_routine_tools(reg, routines)

    if contacts is not None:
        _register_contact_tools(reg, contacts)

    if mcp is not None:
        _register_mcp_tools(reg, mcp)

    # Tra địa điểm: cần CẢ nguồn dữ liệu lẫn kho vị trí (toạ độ giải ở tầng tool).
    if places is not None and location is not None:
        _register_place_tools(reg, places, location, browser=browser, bus=bus,
                              speak_limit=config.PLACES_LIMIT)

    return reg


def _register_mcp_tools(reg: ToolRegistry, mcp, destructive_keywords=None):
    """Đăng ký mỗi tool của MCP server thành một Tool: handler gọi `mcp.call_tool`. Tool
    GHI (heuristic theo tên: send/create/delete...) đánh dấu destructive -> cổng xác nhận.

    NGOÀI RA: mọi tool mang hình dạng EMAIL đều được gắn `preview` để hiện panel nháp,
    KỂ CẢ tool không destructive: tool LƯU NHÁP không chứa từ khoá GHI nào nên heuristic
    tên xếp nó là "chỉ đọc" -> không cổng, không panel. Mà "viết mail" (chưa gửi) chính là
    lúc người dùng cần nhìn bản nháp nhất. Cột mốc để hiện panel phải là "có nội dung do
    LLM viết ra", không phải "tên tool có chữ send".
    """
    from services.mcp_bridge import is_destructive_tool, DEFAULT_DESTRUCTIVE_KEYWORDS
    from actions.email_draft import email_draft, say_draft
    keywords = destructive_keywords or DEFAULT_DESTRUCTIVE_KEYWORDS

    def _confirm(tool_name):
        """Cụm mô tả để hỏi xác nhận. Lời gọi hình dạng EMAIL được nói bằng tiếng người
        ('gửi email tới sếp...') thay vì đọc tên tool máy móc ('thực hiện gws_gmail_send')."""
        saves_draft = "draft" in tool_name.lower() or "nhap" in strip_accents(tool_name).lower()

        def phrase(**args):
            draft = email_draft(args)
            # Dò tên chỉ để chọn ĐỘNG TỪ ('lưu nháp' vs 'gửi'). Đoán sai làm câu chữ hơi
            # lệch chứ KHÔNG làm mất cổng duyệt — việc chặn do email_draft quyết định.
            return (say_draft(draft, action="draft" if saves_draft else "send")
                    if draft else f"thực hiện '{tool_name}'")
        return phrase

    for spec in mcp.list_tools():
        name = spec["name"]
        if reg.has(name):                          # tránh trùng tên tool sẵn có
            logger.warning("Bỏ qua MCP tool trùng tên: %s", name)
            continue
        destructive = is_destructive_tool(name, keywords)
        reg.register(Tool(
            name=name,
            description=spec.get("description", ""),
            input_schema=spec.get("input_schema") or {"type": "object", "properties": {}},
            handler=(lambda tn: (lambda **kwargs: mcp.call_tool(tn, kwargs)))(name),
            destructive=destructive,
            confirm_message=_confirm(name),
            # Gắn cho MỌI tool: tool không mang hình dạng email thì email_draft trả None
            # -> không panel, không cổng, luồng y như cũ.
            preview=lambda **a: email_draft(a),
        ))


def _register_routine_tools(reg: ToolRegistry, routines):
    """Tool QUẢN LÝ routine (tạo/xem/xoá). Việc CHẠY routine do app.py lo (fast-path)."""

    def create_routine(name, steps):
        r = routines.create(name, steps)
        if r is None:
            return "Routine cần một tên và ít nhất một bước."
        verb = "cập nhật" if r["replaced"] else "tạo"
        return f'Đã {verb} routine "{r["name"]}" gồm {len(r["steps"])} bước.'

    def list_routines():
        items = routines.list()
        if not items:
            return "Chưa có routine nào."
        lines = "\n".join(f'- {r["name"]} ({len(r["steps"])} bước)' for r in items)
        return f"Có {len(items)} routine:\n{lines}"

    def delete_routine(name):
        return (f'Đã xoá routine "{name}".' if routines.delete(name)
                else f"Không thấy routine tên '{name}'.")

    reg.register(Tool(
        name="create_routine",
        description="Tạo một QUY TRÌNH (routine) có tên gồm nhiều bước, để chạy lại bằng một "
                    "câu. Dùng khi người dùng nói 'tạo routine X gồm A, B, C', 'đặt routine...'. "
                    "Tách mỗi việc thành một phần tử trong 'steps' (câu lệnh tiếng Việt).",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên routine, vd 'buổi sáng'"},
                "steps": {"type": "array", "items": {"type": "string"},
                          "description": "Danh sách bước, mỗi bước là một câu lệnh, "
                                         "vd ['mở chrome', 'đọc thời tiết']"},
            },
            "required": ["name", "steps"],
        },
        handler=create_routine,
    ))

    reg.register(Tool(
        name="list_routines",
        description="Liệt kê các routine đã có. Dùng khi người dùng hỏi 'có routine nào', "
                    "'các quy trình của tôi'.",
        input_schema={"type": "object", "properties": {}},
        handler=list_routines,
    ))

    reg.register(Tool(
        name="delete_routine",
        description="Xoá một routine theo tên. Trợ lý sẽ tự hỏi xác nhận trước khi xoá.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên routine cần xoá"},
            },
            "required": ["name"],
        },
        handler=delete_routine,
        destructive=True,
        confirm_message=lambda name=None: f"xoá routine '{name}'",
    ))


def _register_task_tools(reg: ToolRegistry, tasks):
    """Tool quản lý VIỆC CẦN LÀM (to-do). Khớp việc theo từ khoá trong nội dung; khớp nhiều
    -> hỏi lại, không đoán bừa. remove_task là destructive -> Agent tự hỏi xác nhận."""

    def add_task(text, due=None):
        t = tasks.add(text, due=due)
        if t is None:
            return "Bạn muốn thêm việc gì? Hãy nói nội dung việc cần làm."
        return f'Đã thêm việc: "{t["text"]}".'

    def list_tasks(include_done=False):
        items = tasks.list(include_done=include_done)
        if not items:
            return "Hiện không có việc nào cần làm."
        lines = "\n".join(f'- {"(xong) " if t["done"] else ""}{t["text"]}' for t in items)
        return f"Có {len(items)} việc:\n{lines}"

    def complete_task(keyword):
        matches = [m for m in tasks.find(keyword) if not m["done"]]
        if not matches:
            return f"Không thấy việc nào chưa xong giống '{keyword}'."
        if len(matches) > 1:
            names = ", ".join(f'"{m["text"]}"' for m in matches)
            return f"Có {len(matches)} việc khớp: {names}. Bạn muốn hoàn thành việc nào?"
        tasks.complete(matches[0]["id"])
        return f'Đã đánh dấu xong: "{matches[0]["text"]}".'

    def remove_task(keyword):
        matches = tasks.find(keyword)          # cả việc đã xong cũng xoá được
        if not matches:
            return f"Không thấy việc nào giống '{keyword}'."
        if len(matches) > 1:
            names = ", ".join(f'"{m["text"]}"' for m in matches)
            return f"Có {len(matches)} việc khớp: {names}. Bạn muốn xoá việc nào?"
        removed = tasks.remove(matches[0]["id"])
        return f'Đã xoá việc: "{removed["text"]}".'

    reg.register(Tool(
        name="add_task",
        description="Thêm một việc cần làm (to-do) KHÔNG gắn giờ cụ thể. Dùng khi người dùng "
                    "nói 'thêm việc...', 'ghi chú việc...', 'tôi cần làm...'. (Nếu có GIỜ cụ "
                    "thể để nhắc thì dùng schedule_reminder, không phải tool này.)",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Nội dung việc cần làm"},
                "due": {"type": "string", "description": "Hạn (tuỳ chọn), vd 'thứ 6'"},
            },
            "required": ["text"],
        },
        handler=add_task,
    ))

    reg.register(Tool(
        name="list_tasks",
        description="Liệt kê các việc cần làm. Dùng khi người dùng hỏi 'còn việc gì', "
                    "'việc hôm nay', 'danh sách việc'. Mặc định chỉ việc chưa xong.",
        input_schema={
            "type": "object",
            "properties": {
                "include_done": {"type": "boolean",
                                 "description": "true = liệt kê cả việc đã xong"},
            },
        },
        handler=list_tasks,
        speakable=True,      # danh sách đã định dạng sẵn
    ))

    reg.register(Tool(
        name="complete_task",
        description="Đánh dấu một việc là ĐÃ XONG (không xoá), khớp theo từ khoá trong nội "
                    "dung. Dùng khi người dùng nói 'xong việc...', 'làm xong...', 'hoàn thành...'.",
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Từ khoá nội dung việc, vd 'mua sữa'"},
            },
            "required": ["keyword"],
        },
        handler=complete_task,
    ))

    reg.register(Tool(
        name="remove_task",
        description="Xoá hẳn một việc khỏi danh sách, khớp theo từ khoá. Trợ lý sẽ tự hỏi "
                    "xác nhận trước khi xoá. Dùng khi người dùng nói 'xoá việc...', 'bỏ việc...'.",
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Từ khoá nội dung việc cần xoá"},
            },
            "required": ["keyword"],
        },
        handler=remove_task,
        destructive=True,
        confirm_message=lambda keyword=None: f"xoá việc '{keyword}'",
    ))


def _register_contact_tools(reg: ToolRegistry, contacts):
    """Tool SỔ DANH BẠ cục bộ: lưu/tra địa chỉ email theo tên để khỏi phải đọc cả địa chỉ.
    Là nguồn PHỤ — trợ lý tra Google Contacts (gws_contacts_search) trước, không thấy mới
    dùng/lưu sổ này. remove_contact là destructive -> Agent tự hỏi xác nhận."""

    def save_contact(name, email):
        c = contacts.add(name, email)
        if c is None:
            return "Cần cả TÊN và địa chỉ EMAIL để lưu liên hệ."
        return f'Đã lưu liên hệ: {c["name"]} — {c["email"]}.'

    def find_contact(name):
        matches = contacts.find(name)
        if not matches:
            return f"Không thấy liên hệ nào tên '{name}' trong sổ danh bạ."
        lines = "\n".join(f'- {c["name"]}: {c["email"]}' for c in matches)
        return f"Tìm thấy {len(matches)} liên hệ:\n{lines}"

    def list_contacts():
        items = contacts.list()
        if not items:
            return "Sổ danh bạ đang trống."
        lines = "\n".join(f'- {c["name"]}: {c["email"]}' for c in items)
        return f"Có {len(items)} liên hệ:\n{lines}"

    def remove_contact(name):
        matches = contacts.find(name)
        if not matches:
            return f"Không thấy liên hệ nào tên '{name}'."
        if len(matches) > 1:
            names = ", ".join(c["name"] for c in matches)
            return f"Có {len(matches)} liên hệ khớp: {names}. Bạn muốn xoá ai?"
        removed = contacts.remove(matches[0]["id"])
        return f'Đã xoá liên hệ: {removed["name"]}.'

    reg.register(Tool(
        name="save_contact",
        description="Lưu một liên hệ (tên -> email) vào sổ danh bạ để lần sau chỉ cần gọi "
                    "tên. Dùng khi người dùng nói 'lưu liên hệ...', 'số/mail của X là...', "
                    "'ghi nhớ email của...'.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên hoặc biệt danh, vd 'sếp', 'mẹ'"},
                "email": {"type": "string", "description": "Địa chỉ email của liên hệ"},
            },
            "required": ["name", "email"],
        },
        handler=save_contact,
    ))

    reg.register(Tool(
        name="find_contact",
        description="Tra địa chỉ email của một liên hệ đã lưu trong sổ danh bạ CỤC BỘ theo "
                    "tên. Dùng để lấy email trước khi soạn/gửi mail khi người dùng chỉ nói tên.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên liên hệ cần tra, vd 'sếp'"},
            },
            "required": ["name"],
        },
        handler=find_contact,
    ))

    reg.register(Tool(
        name="list_contacts",
        description="Liệt kê toàn bộ liên hệ trong sổ danh bạ cục bộ. Dùng khi người dùng "
                    "hỏi 'danh bạ có ai', 'tôi lưu những liên hệ nào'.",
        input_schema={"type": "object", "properties": {}},
        handler=list_contacts,
        speakable=True,
    ))

    reg.register(Tool(
        name="remove_contact",
        description="Xoá một liên hệ khỏi sổ danh bạ, khớp theo tên. Trợ lý sẽ tự hỏi xác "
                    "nhận trước khi xoá.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên liên hệ cần xoá"},
            },
            "required": ["name"],
        },
        handler=remove_contact,
        destructive=True,
        confirm_message=lambda name=None: f"xoá liên hệ '{name}'",
    ))


def _register_profile_tools(reg: ToolRegistry, profile):
    """Tool ghi nhớ thông tin cá nhân LÂU DÀI về người dùng (tên, xưng hô, địa điểm...)."""
    reg.register(Tool(
        name="remember_about_user",
        description=("Ghi nhớ thông tin cá nhân LÂU DÀI về người dùng khi họ cho biết, để "
                     "cá nhân hoá về sau. Dùng khi người dùng nói 'tôi tên là...', 'gọi tôi "
                     "là...', 'tôi ở/sống ở...', 'nhớ giúp tôi rằng...'. CHỈ truyền trường "
                     "người dùng thực sự nói (bỏ trống các trường khác). QUAN TRỌNG: nếu "
                     "điều cần nhớ là một SỰ KIỆN có thời điểm (phỏng vấn, cuộc hẹn, deadline) "
                     "thì truyền thêm 'when' — nhờ đó sau khi qua giờ trợ lý biết việc đã "
                     "xong, không nhắc lại như sắp diễn ra."),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên người dùng"},
                "address_form": {"type": "string",
                                 "description": "Cách xưng hô muốn được gọi, vd 'sếp', 'anh Nam'"},
                "location": {"type": "string",
                             "description": "Địa điểm mặc định (để hỏi thời tiết), vd 'Đà Nẵng'"},
                "note": {"type": "string", "description": "Một điều khác cần nhớ lâu dài"},
                "when": {"type": "string",
                         "description": "CHỈ khi 'note' là sự kiện có thời điểm: thời điểm "
                                        "diễn ra dạng ISO 'YYYY-MM-DDTHH:MM' (suy từ ngày giờ "
                                        "hiện tại đã cho ở đầu prompt, vd 'chiều nay 3h')"},
            },
        },
        handler=lambda name=None, address_form=None, location=None, note=None, when=None:
            profile.remember(name=name, address_form=address_form,
                             location=location, note=note, when=when),
    ))

    reg.register(Tool(
        name="forget_about_user",
        description=("QUÊN một điều đã ghi nhớ về người dùng (ghi chú, quan sát, hoặc sự "
                     "kiện), khớp theo từ khoá. Dùng khi người dùng nói 'quên chuyện... đi', "
                     "'đừng nhớ... nữa', 'bỏ ghi chú...'. Trợ lý sẽ tự hỏi xác nhận trước "
                     "khi quên."),
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string",
                            "description": "Từ khoá của điều cần quên, vd 'phỏng vấn'"},
            },
            "required": ["keyword"],
        },
        handler=lambda keyword: profile.forget(keyword),
        destructive=True,      # xoá trí nhớ KHÔNG khôi phục được -> chốt xác nhận trong code
        confirm_message=lambda keyword=None: f"quên chuyện '{keyword}'",
    ))


def _register_screen_tools(reg: ToolRegistry, screen):
    """Tool đọc/điều khiển màn hình (chụp / tìm chữ OCR / cuộn) — chạy local."""
    reg.register(Tool(
        name="take_screenshot",
        description="Chụp lại toàn bộ màn hình và lưu vào máy (local). Dùng khi người "
                    "dùng yêu cầu 'chụp màn hình', 'chụp lại màn hình'.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: screen.capture(),
    ))

    reg.register(Tool(
        name="find_on_screen",
        description="Tìm một từ/cụm từ đang HIỂN THỊ trên màn hình (đọc chữ bằng OCR, "
                    "chạy local). Trả về các dòng chứa từ khóa. Dùng khi người dùng hỏi "
                    "'trên màn hình có ... không', 'tìm ... trên màn hình'.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Từ/cụm từ cần tìm trên màn hình"},
            },
            "required": ["query"],
        },
        handler=lambda query: screen.find(query),
    ))

    reg.register(Tool(
        name="scroll_screen",
        description="Cuộn màn hình lên hoặc xuống (tại cửa sổ đang trỏ chuột). Dùng khi "
                    "người dùng nói 'cuộn xuống', 'lướt lên', 'kéo xuống tiếp'.",
        input_schema={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down"],
                              "description": "Hướng cuộn: up (lên) / down (xuống)"},
                "amount": {"type": "integer", "description": "Số nấc cuộn (mặc định 3)"},
            },
            "required": ["direction"],
        },
        handler=lambda direction, amount=3: screen.scroll(direction, amount),
    ))


def _register_browser_tools(reg: ToolRegistry, browser):
    """Tool điều khiển Chrome (media + quản lý tab) qua BrowserBridge/extension."""
    from services.browser_protocol import (
        build_media_command, summarize_media_response,
        summarize_tab_list, summarize_close,
        build_open_or_reuse, summarize_open_or_reuse)

    def media_control(action, value=None):
        try:
            cmd = build_media_command(action, value)
        except ValueError as e:
            return str(e)
        resp = browser.send_command(**cmd)
        return summarize_media_response(resp, action, value)

    def list_tabs():
        return summarize_tab_list(browser.send_command(action="GET_TABS"))

    def close_tab(keyword, confirm=False):
        if not keyword or not str(keyword).strip():
            return "Cần cho biết từ khoá của tab cần đóng (tên trang hoặc tiêu đề)."
        resp = browser.send_command(action="CLOSE_TAB_BY_KEYWORD",
                                    keyword=keyword, dryRun=not confirm)
        return summarize_close(resp, keyword, confirm)

    def open_or_reuse(url, match_domain=None):
        try:
            cmd = build_open_or_reuse(url, match_domain)
        except ValueError as e:
            return str(e)
        return summarize_open_or_reuse(browser.send_command(**cmd), url)

    reg.register(Tool(
        name="browser_list_tabs",
        description="Liệt kê các tab Chrome đang mở (tiêu đề + trang). Dùng khi người "
                    "dùng hỏi 'đang mở tab gì', hoặc để biết tab nào trước khi đóng.",
        input_schema={"type": "object", "properties": {}},
        handler=list_tabs,
    ))

    reg.register(Tool(
        name="browser_close_tab",
        description=(
            "Đóng (các) tab Chrome có tiêu đề hoặc URL chứa 'keyword'. QUAN TRỌNG — đóng "
            "tab KHÓ HOÀN TÁC: BẮT BUỘC gọi lần đầu với confirm=false để xem danh sách tab "
            "sẽ đóng, ĐỌC danh sách đó cho người dùng và CHỜ họ đồng ý; chỉ gọi lại với "
            "confirm=true SAU KHI người dùng xác nhận. Không tự đặt confirm=true ngay lần đầu."),
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string",
                            "description": "Từ khoá khớp tiêu đề/URL tab, vd 'facebook'"},
                "confirm": {"type": "boolean",
                            "description": "false = chỉ xem trước; true = thật sự đóng "
                                           "(chỉ dùng sau khi người dùng đã đồng ý)"},
            },
            "required": ["keyword"],
        },
        handler=close_tab,
    ))

    reg.register(Tool(
        name="browser_open_or_reuse",
        description=(
            "Mở một URL trong Chrome, TÁI DÙNG tab cùng trang nếu đã mở (chuyển tab đó "
            "tới URL mới + đưa lên trước) thay vì tạo tab mới. Dùng khi mở/chuyển sang "
            "một trang có thể đã mở sẵn, vd mở video YouTube khác trong tab YouTube đang có."),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL đầy đủ cần mở"},
                "match_domain": {"type": "string",
                                 "description": "Tên miền để tìm tab tái dùng "
                                                "(mặc định tự suy từ url, vd youtube.com)"},
            },
            "required": ["url"],
        },
        handler=open_or_reuse,
    ))

    reg.register(Tool(
        name="browser_media_control",
        description=(
            "Điều khiển trình phát media (video/nhạc) trên tab Chrome đang mở, ví dụ "
            "YouTube. Dùng khi người dùng nói 'tạm dừng/phát tiếp nhạc', 'tua', 'chỉnh "
            "âm lượng video', 'bài kế/trước'. 'action': play, pause, toggle (đảo phát/dừng), "
            "next, prev (trong playlist), set_volume (cần 'value' 0-100), adjust_volume (cần "
            "'value' = mức thay đổi tương đối, vd +10/-10 để to/nhỏ hơn), seek (cần 'value' "
            "= số giây tua tới; số âm để tua lùi)."),
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "enum": ["play", "pause", "toggle", "next", "prev",
                                    "set_volume", "adjust_volume", "seek"],
                           "description": "Hành động điều khiển media"},
                "value": {"type": "number",
                          "description": "set_volume (0-100), adjust_volume (±, vd 10/-10), "
                                         "hoặc seek (giây)"},
            },
            "required": ["action"],
        },
        handler=media_control,
    ))


def _register_web_search_tools(reg: ToolRegistry, browser, actions):
    """Tìm web + ĐỌC danh sách kết quả (extension trích DOM), rồi mở kết quả người dùng
    chọn theo SỐ THỨ TỰ — hoặc ĐỌC NỘI DUNG một kết quả để trả lời câu hỏi trực tiếp
    (khác việc mở tab). Giữ trạng thái danh sách kết quả gần nhất giữa các lượt trong
    closure `session` — người dùng/model chỉ cần nói 'số 2', KHÔNG cần chép lại URL dài.
    """
    from services.browser_protocol import (
        build_search_read, parse_search_results, summarize_search_results,
        build_open_or_reuse)

    session = {"results": []}      # kết quả tìm kiếm gần nhất (sống suốt phiên)

    def search_list(query, engine=None):
        try:
            cmd = build_search_read(query, engine or config.WEB_SEARCH_ENGINE)
        except ValueError as e:
            return str(e)
        # Đọc DOM cần mở tab + chờ render -> cho timeout rộng hơn lệnh thường.
        resp = browser.send_command(timeout=25, **cmd)
        results, err = parse_search_results(resp)
        if err:
            return err
        session["results"] = results
        return summarize_search_results(results, query)

    def open_result(index=None):
        results = session["results"]
        if not results:
            return "Chưa có kết quả tìm kiếm nào để mở — hãy tìm trước đã."
        try:
            i = int(str(index).strip())
        except (TypeError, ValueError):
            return "Cần cho biết số thứ tự kết quả cần mở (ví dụ 1, 2, 3)."
        if i < 1 or i > len(results):
            return f"Chỉ có {len(results)} kết quả, không có số {i}."
        chosen = results[i - 1]
        browser.send_command(**build_open_or_reuse(chosen["url"]))
        return f"Đang mở kết quả số {i}: {chosen['title']}."

    reg.register(Tool(
        name="web_search_list",
        description=("Tìm thông tin trên web rồi ĐỌC danh sách vài kết quả đầu để người "
                     "dùng chọn (KHÔNG mở thẳng). Dùng khi người dùng muốn 'tìm thông tin "
                     "về X', 'tra cứu X', 'tìm hiểu về X' — trừ YouTube/Wikipedia. Sau đó "
                     "người dùng chọn số nào thì dùng open_search_result."),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung cần tìm"},
                "engine": {"type": "string", "enum": ["google", "duckduckgo"],
                           "description": "Công cụ tìm (mặc định theo cấu hình)"},
            },
            "required": ["query"],
        },
        handler=search_list,
    ))

    reg.register(Tool(
        name="open_search_result",
        description=("Mở một kết quả trong danh sách VỪA tìm bằng web_search_list, theo "
                     "SỐ THỨ TỰ. Dùng khi người dùng nói 'mở kết quả số 2', 'vào link 1', "
                     "'cái đầu tiên'..."),
        input_schema={
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "Số thứ tự kết quả (1, 2, 3...)"},
            },
            "required": ["index"],
        },
        handler=open_result,
    ))

    def read_result(index=1):
        results = session["results"]
        if not results:
            return "Chưa có kết quả tìm kiếm nào — hãy gọi web_search_list trước."
        try:
            i = int(str(index).strip())
        except (TypeError, ValueError):
            i = 1
        if i < 1 or i > len(results):
            return f"Chỉ có {len(results)} kết quả, không có số {i}."
        chosen = results[i - 1]
        text = actions.web_fetch(chosen["url"])
        return f"Nội dung bài '{chosen['title']}':\n{text}"

    reg.register(Tool(
        name="read_search_result",
        description=("Tải NỘI DUNG THẬT của một kết quả trong danh sách VỪA tìm bằng "
                     "web_search_list, theo SỐ THỨ TỰ (mặc định số 1) — để ĐỌC rồi TRẢ LỜI "
                     "CÂU HỎI của người dùng bằng nội dung đó. Dùng cho câu hỏi cần thông "
                     "tin cụ thể (vd 'hôm nay có sự kiện gì...', 'vì sao...', 'X là ai'), "
                     "KHÁC với open_search_result (chỉ mở tab, không đọc nội dung)."),
        input_schema={
            "type": "object",
            "properties": {
                "index": {"type": "integer",
                          "description": "Số thứ tự kết quả cần đọc (mặc định 1)"},
            },
        },
        handler=read_result,
    ))


def _register_schedule_tools(reg: ToolRegistry, scheduler):
    def schedule_reminder(message, delay_minutes=None, at=None):
        fire = _parse_fire_time(delay_minutes=delay_minutes, at=at)
        if fire is None:
            return "Cần cho biết thời điểm: delay_minutes (số phút nữa) hoặc at (HH:MM)."
        task = scheduler.add(message, fire)
        return (f"Đã đặt nhắc lúc {fire.strftime('%H:%M %d/%m')}: "
                f"\"{message}\" (mã {task['id']}).")

    def list_reminders():
        tasks = scheduler.list()
        if not tasks:
            return "Hiện không có lịch nhắc nào."
        lines = []
        for t in tasks:
            when = datetime.fromisoformat(t["fire_at"]).strftime("%H:%M %d/%m")
            lines.append(f"- [{t['id']}] {when}: {t['message']}")
        return "Các lịch nhắc:\n" + "\n".join(lines)

    def cancel_reminder(task_id):
        return ("Đã hủy lịch nhắc." if scheduler.cancel(task_id)
                else f"Không tìm thấy lịch nhắc mã '{task_id}'.")

    def schedule_action(command, delay_minutes=None, at=None):
        fire = _parse_fire_time(delay_minutes=delay_minutes, at=at)
        if fire is None:
            return "Cần cho biết thời điểm: delay_minutes (số phút nữa) hoặc at (HH:MM)."
        scheduler.add(command, fire, kind="do")
        return f"Được, tôi sẽ tự làm giúp bạn lúc {fire.strftime('%H:%M %d/%m')}: {command}."

    reg.register(Tool(
        name="schedule_reminder",
        description="Đặt một lời NHẮC (chỉ ĐỌC nhắc, KHÔNG tự làm) vào thời điểm sau. Dùng khi "
                    "người dùng nói 'nhắc tôi X lúc...'. Cho 'delay_minutes' (số phút nữa) HOẶC "
                    "'at' (giờ HH:MM, hoặc ISO datetime).",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Nội dung cần nhắc"},
                "delay_minutes": {"type": "number", "description": "Nhắc sau bao nhiêu phút"},
                "at": {"type": "string", "description": "Giờ nhắc, vd '15:00' hoặc ISO datetime"},
            },
            "required": ["message"],
        },
        handler=schedule_reminder,
    ))

    reg.register(Tool(
        name="schedule_action",
        description="Hẹn THỰC THI một lệnh vào thời điểm sau (trợ lý TỰ LÀM khi tới giờ, không "
                    "chỉ nhắc). Dùng khi người dùng nói 'lúc X hãy mở/phát/làm Y', '22h30 mở "
                    "youtube'. 'command' = câu lệnh sẽ chạy (vd 'mở youtube'). Cho 'delay_minutes' "
                    "(số phút nữa) HOẶC 'at' (giờ HH:MM).",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Lệnh cần thực thi khi tới giờ, vd 'mở youtube'"},
                "delay_minutes": {"type": "number", "description": "Làm sau bao nhiêu phút"},
                "at": {"type": "string", "description": "Giờ thực thi, vd '22:30'"},
            },
            "required": ["command"],
        },
        handler=schedule_action,
    ))

    reg.register(Tool(
        name="list_reminders",
        description="Liệt kê các lịch nhắc đang có.",
        input_schema={"type": "object", "properties": {}},
        handler=list_reminders,
        speakable=True,
    ))

    reg.register(Tool(
        name="cancel_reminder",
        description="Hủy một lịch nhắc theo mã (id).",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "Mã lịch nhắc"}},
            "required": ["task_id"],
        },
        handler=cancel_reminder,
    ))


def _register_place_tools(reg: ToolRegistry, places, location, browser=None, bus=None,
                          speak_limit=3):
    """Tra ĐỊA ĐIỂM — hai ý định tách đôi.

    `find_nearby` : theo LOẠI, quanh một điểm  -> ràng buộc KHOẢNG CÁCH
    `find_place`  : ĐÚNG MỘT CHỖ có tên        -> ràng buộc TÊN (và khu vực nếu người nói)

    Ràng buộc đến từ lời người dùng: "quanh đây" là ràng buộc, "X ở đâu" thì không.
    Toạ độ chính xác chỉ được giải ở ĐÂY, ngay lúc gọi — không quay lại lịch sử hội thoại.
    """
    from actions.place_explain import explain
    from actions.place_refine import (CHANGES, apply_refinement, needs_requery,
                                      radius_factor)
    from services.browser_protocol import summarize_places, build_open_or_reuse

    # Trạng thái lượt tìm gần nhất — nền cho việc tinh chỉnh ở lượt sau.
    # Giữ CẢ ứng viên lẫn ngữ cảnh: "có chỗ nào mở muộn hơn không" phải lọc trên đúng
    # danh sách đó, không được tra lại bằng từ khoá mới.
    session = {"results": [], "query": None, "area": None, "center": None,
               "radius_km": None, "rank_ctx": {}}

    def _origin(near):
        """Giải điểm tra cứu -> ((lat,lng), tên hiển thị) hoặc (None, câu hỏi lại)."""
        text = (near or "").strip()
        if not text or text == "@current":
            coords = location.coords()
            if not coords:
                return None, ("Tôi chưa biết bạn đang ở khu vực nào. Bạn cho tôi biết "
                              "quận/thành phố nhé, tôi sẽ nhớ cho lần sau.")
            return coords, location.display()
        spot = places.resolve_area(text, origin=location.coords())
        if not spot:
            return None, (f"Tôi chưa xác định được '{text}' nằm ở đâu. Bạn cho tôi biết "
                          f"quận hoặc thành phố nhé, tôi tìm quanh đó.")
        return (spot[0], spot[1]), spot[2]

    def _remember(out, query, area=None, center=None, radius_km=None):
        # Chỉ giữ danh sách khi THỰC SỰ có kết quả — tránh 'mở cái thứ 2' trỏ vào lượt cũ.
        ok = out["outcome"] == "OK"
        session["results"] = out["results"] if ok else []
        session["query"] = query if ok else None
        session["area"] = (area or out.get("area")) if ok else None
        session["center"] = center if ok else None
        session["radius_km"] = radius_km if ok else None
        session["rank_ctx"] = ((out.get("diagnostics") or {}).get("rank_ctx") or {}) if ok else {}
        # Giải thích CHỈ dựng từ bằng chứng có thật; LLM chỉ đọc lại, không thêm.
        reason = None
        if out["outcome"] == "OK" and out["results"]:
            reason = explain(out["results"][0],
                             (out.get("diagnostics") or {}).get("rank_ctx") or {})
        return summarize_places(out["outcome"], out["results"], query,
                                out.get("diagnostics"), area=area or out.get("area"),
                                source=out.get("source"), speak_limit=speak_limit,
                                top_reason=reason)

    def find_nearby(query=None, near=None, radius_km=None):
        if not query or not str(query).strip():
            return "Bạn muốn tìm loại địa điểm nào quanh đó?"
        coords, label = _origin(near)
        if coords is None:
            return label
        try:
            r = float(radius_km) if radius_km else None
        except (TypeError, ValueError):
            r = None
        out = places.find_nearby(str(query).strip(), coords, radius_km=r)
        return _remember(out, str(query).strip(), area=None if not near else label,
                         center=coords, radius_km=r or places.radius_km)

    def find_place(name=None, in_area=None):
        if not name or not str(name).strip():
            return "Bạn muốn tìm chỗ nào?"
        area = (in_area or "").strip()
        out = places.find_place(str(name).strip(), origin=location.coords(),
                                area=area or None)
        if out.get("diagnostics", {}).get("unknown_area"):
            return (f"Tôi chưa xác định được '{area}' nằm ở đâu. Bạn nói rõ quận hoặc "
                    f"thành phố giúp tôi nhé.")
        if out["outcome"] == "SOURCE_UNAVAILABLE" and not area \
                and out.get("diagnostics", {}).get("reason"):
            return ("Tôi chưa biết bạn đang ở đâu để tra. Bạn cho tôi biết quận/thành phố "
                    "nhé, hoặc nói rõ tìm ở khu vực nào.")
        return _remember(out, str(name).strip(), area=out.get("area"))

    def _browser_search(query, limit=8):
        """Dự phòng cho discovery: đọc trang kết quả trong TRÌNH DUYỆT THẬT -> [url].

        Cần vì mọi máy tìm kiếm qua HTTP thẳng đều chặn sau một buổi gọi liên tục từ cùng
        một IP. Trình duyệt thật không bị chặn vì nó là trình duyệt thật — chậm hơn, nhưng
        giữ tính năng sống thay vì chết lặng.
        """
        if browser is None or not getattr(browser, "connected", False):
            return []
        from services.browser_protocol import build_search_read, parse_search_results
        try:
            cmd = build_search_read(query, config.WEB_SEARCH_ENGINE, limit=limit)
            resp = browser.send_command(timeout=25, **cmd)
        except Exception as e:
            logger.warning("research: discovery qua trình duyệt lỗi: %s", e)
            return []
        results, err = parse_search_results(resp)
        if err:
            logger.warning("research: discovery qua trình duyệt: %s", err)
            return []
        return [r["url"] for r in results if r.get("url")]

    def _claim_cache():
        """ClaimCache dùng chung cho lane research, TẠO LƯỜI.

        Lười vì phiên nào không hỏi địa điểm thì không phải đọc file nào — cùng lý lẽ với
        panel kết quả. Dựng hỏng thì trả None: mất phần tăng tốc, không mất tính năng.
        """
        if "claim_cache" not in session:
            store = None
            if config.RESEARCH_CACHE_ENABLED:
                try:
                    from research.claim_cache import DEFAULT_PATH, ClaimCache
                    store = ClaimCache(config.RESEARCH_CACHE_PATH or DEFAULT_PATH,
                                       fresh_hours=config.RESEARCH_CACHE_FRESH_H,
                                       ttl_days=config.RESEARCH_CACHE_TTL_DAYS)
                except Exception as e:
                    logger.warning("research: không dựng được claim cache: %s", e)
            session["claim_cache"] = store
        return session["claim_cache"]

    def research_places(need=None, in_area=None):
        """Tìm theo NHU CẦU chứ không theo loại.

        Chậm hơn `find_nearby` nhiều lần vì phải đọc web, nên chỉ dùng khi ràng buộc KHÔNG
        có trường dữ liệu nào trên bản đồ ("nhiều cây xanh", "phong cách cổ"). Ném thẳng
        những câu đó vào Maps là vô nghĩa một cách im lặng: Maps ÉP KHỚP thay vì trả rỗng.
        """
        from actions.place_research import research, say_research
        if not need or not str(need).strip():
            return "Bạn muốn tìm chỗ như thế nào?"
        area = (in_area or "").strip() or location.coarse("province") or None
        out = research(str(need).strip(), area=area, places=places,
                       origin=location.coords(), browser_search=_browser_search,
                       cache=_claim_cache())

        # Giữ ứng viên cho "mở cái thứ N", nhưng KHÔNG đặt `center`/`query`: nhánh tra lại
        # của `refine_places` sẽ ném nguyên câu nhu cầu vào Maps như từ khoá. Thiếu `center`
        # thì nhánh đó dừng và hỏi lại, an toàn hơn.
        ok = out["outcome"] == "OK"
        session["results"] = out["results"] if ok else []
        session["query"] = None
        session["area"] = area if ok else None
        session["center"] = None
        session["radius_km"] = None
        session["rank_ctx"] = {}

        # Panel là tầng KIỂM CHỨNG BẰNG MẮT cho thuộc tính không đo được.
        # Giọng nói đọc 3 chỗ đầu; panel hiện đủ danh sách kèm bằng chứng xem được.
        if bus is not None:
            bus.emit_places(out["results"], need=str(need).strip())
        return say_research(out, str(need).strip(), speak_limit=speak_limit)

    def open_place_result(index=None):
        results = session["results"]
        if not results:
            return "Chưa có danh sách địa điểm nào để mở — hãy tìm trước đã."
        try:
            i = int(str(index).strip())
        except (TypeError, ValueError):
            return "Cần cho biết số thứ tự chỗ cần mở (ví dụ 1, 2, 3)."
        if i < 1 or i > len(results):
            return f"Chỉ có {len(results)} chỗ, không có số {i}."
        chosen = results[i - 1]

        # Lane 3 trả ứng viên CHƯA tra bản đồ (giải toạ độ lười — xem
        # `place_research.DEFAULT_RESOLVE_LIMIT`). Đây đúng là lúc trả khoản nợ đó: người
        # dùng đã chọn một chỗ cụ thể, nên bỏ ~12 giây tra một chỗ là xứng đáng, khác hẳn
        # việc tra sẵn cả danh sách mà phần lớn không ai mở.
        if not chosen.get("url") and chosen.get("resolved") is False:
            out = places.find_place(chosen["name"], origin=location.coords())
            if out.get("outcome") == "OK" and out.get("results"):
                chosen = dict(chosen, **out["results"][0])
                chosen["resolved"] = True
                results[i - 1] = chosen          # nhớ lại, khỏi tra lần hai
            else:
                where = f" (địa chỉ ghi trên bài: {chosen['address']})" if chosen.get("address") else ""
                return (f"Tôi chưa tra được '{chosen['name']}' trên bản đồ{where}.")

        if browser is not None and chosen.get("url"):
            browser.send_command(**build_open_or_reuse(chosen["url"]))
            return f"Đang mở chỗ số {i}: {chosen['name']}."
        return f"Chỗ số {i} là {chosen['name']}."

    _REFINE_LABEL = {"open_later": "mở muộn hơn", "open_now": "đang mở cửa",
                     "closer": "gần hơn", "cheaper": "rẻ hơn",
                     "better_rated": "đánh giá cao hơn", "quieter": "yên tĩnh hơn",
                     "farther": "tìm rộng ra"}

    def refine_places(change=None, value=None):
        import datetime as _dt
        if not session["results"]:
            return "Chưa có danh sách địa điểm nào để lọc — bạn muốn tìm gì trước đã?"
        ch = (change or "").strip().lower()
        if ch not in CHANGES:
            return ("Bạn muốn đổi theo hướng nào: mở muộn hơn, gần hơn, rẻ hơn, "
                    "đánh giá cao hơn, hay yên tĩnh hơn?")

        if needs_requery(ch):
            # Mở rộng phạm vi thì buộc phải tra lại — không bịa ra ứng viên mới.
            center = session["center"]
            if not center:
                return "Bạn nhắc lại giúp tôi tìm gì và ở khu vực nào nhé."
            base = session["radius_km"] or places.radius_km
            new_r = max(0.3, min(30.0, base * radius_factor(ch)))
            out = places.find_nearby(session["query"], center, radius_km=new_r)
            return _remember(out, session["query"], area=session["area"],
                             center=center, radius_km=new_r)

        # Dùng giờ HIỆN TẠI, không dùng giờ của lượt tìm trước: hội thoại có thể đã kéo
        # dài, và "còn mở bao lâu nữa" phụ thuộc lúc HỎI.
        kept, meta = apply_refinement(session["results"], ch, value, now=_dt.datetime.now(),
                                      radius_km=session["radius_km"])
        label = _REFINE_LABEL.get(ch, ch)
        if not kept:
            # Giữ nguyên danh sách cũ để người dùng còn lọc kiểu khác được.
            note = meta.get("note") or f"Không có chỗ nào {label}."
            return note + " Bạn có muốn tôi tìm rộng ra không?"

        session["results"] = kept
        reason = explain(kept[0], session.get("rank_ctx") or {})
        head = summarize_places("OK", kept, f"{session['query']} ({label})",
                                area=session.get("area"), speak_limit=speak_limit,
                                top_reason=reason)
        return (meta["note"] + "\n" + head) if meta.get("note") else head

    def set_my_location(place=None):
        if not place or not str(place).strip():
            return "Bạn đang ở khu vực nào?"
        # Dùng CHUNG bộ giải địa danh hai tầng với find_nearby: danh bạ hành chính không
        # biết khu đô thị / toà nhà, nhưng bản đồ thì biết.
        spot = places.resolve_area(str(place).strip())
        if not spot:
            return (f"Tôi chưa xác định được '{place}' ở đâu. Bạn nói tên quận hoặc "
                    f"thành phố giúp tôi nhé.")
        shown = location.set_coords(spot[0], spot[1], spot[2])
        return f"Tôi nhớ rồi, bạn đang ở {shown}."

    reg.register(Tool(
        name="find_nearby",
        description=("Tìm địa điểm theo LOẠI ở gần một vị trí (quán ăn, cà phê, ATM, hiệu "
                     "thuốc, cây xăng...). Dùng khi người dùng hỏi 'quanh đây có...', 'gần "
                     "đây có...', 'chỗ nào gần tôi...'. KHÔNG dùng khi người dùng nêu TÊN "
                     "RIÊNG của một chỗ cụ thể mà không kèm 'gần đây' — khi đó dùng find_place."),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Loại địa điểm, ví dụ 'quán cà phê'"},
                "near": {"type": "string",
                         "description": "Khu vực người dùng nêu; để trống = vị trí hiện tại"},
                "radius_km": {"type": "number",
                              "description": "Chỉ đặt khi người dùng nói rõ, ví dụ 'trong 2 km'"},
            },
            "required": ["query"],
        },
        handler=find_nearby,
        speakable=True,
    ))

    reg.register(Tool(
        name="find_place",
        description=("Tìm ĐÚNG MỘT địa điểm mà người dùng gọi TÊN (ví dụ 'nhà sách Fahasa "
                     "Nguyễn Văn Cừ', 'quán Highlands Trần Duy Hưng'). KHÔNG giới hạn khoảng "
                     "cách trừ khi người dùng nêu khu vực trong `in_area`. Nếu câu có 'gần "
                     "đây/quanh đây' thì dùng find_nearby thay vì tool này."),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên chỗ cần tìm"},
                "in_area": {"type": "string",
                            "description": "Khu vực người dùng nêu, ví dụ 'quận 9'; để trống nếu không nêu"},
            },
            "required": ["name"],
        },
        handler=find_place,
        speakable=True,
    ))

    reg.register(Tool(
        name="research_places",
        # Mô tả này là thứ model dùng để CHỌN LANE, nên con số thời gian trong đó phải
        # đúng với hiện trạng: nói quá chậm thì model né tool, nói "nhanh, cứ dùng" thì nó
        # thành lane mặc định. Luật chọn lane vẫn là: KHÔNG diễn đạt được bằng loại +
        # khoảng cách thì mới dùng tool này.
        description=("Tìm địa điểm theo MÔ TẢ/CẢM GIÁC mà bản đồ không có trường dữ liệu: "
                     "'quán cà phê nhiều cây xanh', 'quán phong cách cổ', 'quán view đẹp "
                     "để dẫn người yêu đi', 'chỗ nào decor xinh'. Tool này ĐỌC BÁO/BLOG "
                     "(khoảng 5 giây) và trả về chỗ được NHIỀU NGUỒN nhắc tới, kèm ảnh và "
                     "trích dẫn — nhưng KHÔNG lọc theo khoảng cách. Chỉ dùng khi yêu cầu "
                     "KHÔNG diễn đạt được bằng loại địa điểm + khoảng cách; hỏi 'quán cà "
                     "phê gần đây' thì dùng find_nearby."),
        input_schema={
            "type": "object",
            "properties": {
                "need": {"type": "string",
                         "description": "Nguyên văn mô tả của người dùng, ví dụ 'quán cà phê nhiều cây xanh'"},
                "in_area": {"type": "string",
                            "description": "Khu vực người dùng nêu; để trống = khu vực đang ở"},
            },
            "required": ["need"],
        },
        handler=research_places,
        speakable=True,
    ))

    reg.register(Tool(
        name="open_place_result",
        description=("Mở một chỗ trong danh sách vừa đọc, theo SỐ THỨ TỰ (1, 2, 3...). "
                     "Dùng sau find_nearby hoặc find_place."),
        input_schema={
            "type": "object",
            "properties": {"index": {"type": "integer", "description": "Số thứ tự"}},
            "required": ["index"],
        },
        handler=open_place_result,
        speakable=True,
    ))

    reg.register(Tool(
        name="refine_places",
        description=("Lọc lại DANH SÁCH ĐỊA ĐIỂM vừa đọc theo một yêu cầu mới, KHÔNG tìm "
                     "lại từ đầu. Dùng khi người dùng nói kiểu 'có chỗ nào mở muộn hơn "
                     "không', 'gần hơn nữa đi', 'rẻ hơn', 'chỗ nào yên tĩnh hơn', 'chỗ "
                     "nào điểm cao hơn', 'tìm rộng ra'. KHÔNG được đưa những từ này vào "
                     "find_nearby như từ khoá tìm kiếm — chúng là RÀNG BUỘC, không phải "
                     "tên quán."),
        input_schema={
            "type": "object",
            "properties": {
                "change": {"type": "string",
                           "enum": ["open_later", "open_now", "closer", "cheaper",
                                    "better_rated", "quieter", "farther"],
                           "description": "Hướng tinh chỉnh"},
                "value": {"type": "string",
                          "description": "Mốc cụ thể nếu người dùng nói rõ, vd '23' cho "
                                         "'mở tới 23 giờ'; để trống nếu không nói"},
            },
            "required": ["change"],
        },
        handler=refine_places,
        speakable=True,
    ))

    reg.register(Tool(
        name="set_my_location",
        description=("Ghi nhớ khu vực người dùng đang ở (quận/thành phố) để lần sau hỏi "
                     "'quanh đây' là biết. Dùng khi người dùng nói họ đang ở đâu."),
        input_schema={
            "type": "object",
            "properties": {"place": {"type": "string", "description": "Tên quận/thành phố"}},
            "required": ["place"],
        },
        handler=set_my_location,
        speakable=True,
    ))
