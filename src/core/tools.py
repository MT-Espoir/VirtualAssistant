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

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from utils.logger import get_logger

logger = get_logger(__name__)


def _parse_fire_time(delay_minutes=None, at=None, now=None):
    """Tính thời điểm nhắc từ delay_minutes (tương đối) hoặc at (HH:MM / ISO).

    Trả về datetime, hoặc None nếu không xác định được.
    """
    now = now or datetime.now()
    if delay_minutes is not None:
        try:
            return now + timedelta(minutes=float(delay_minutes))
        except (TypeError, ValueError):
            return None
    if at:
        at = str(at).strip()
        try:                                   # ISO đầy đủ, vd 2026-07-25T15:00
            return datetime.fromisoformat(at)
        except ValueError:
            pass
        try:                                   # dạng HH:MM -> hôm nay, quá giờ thì mai
            hh, mm = at.split(":")
            fire = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            return fire + timedelta(days=1) if fire <= now else fire
        except (ValueError, TypeError):
            return None
    return None


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict          # JSON Schema cho tham số
    handler: Callable[..., str]  # nhận **kwargs theo schema, trả về chuỗi

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

    def specs(self) -> List[dict]:
        return [t.spec() for t in self._tools.values()]

    def run(self, name: str, arguments: dict) -> str:
        """Thực thi tool. Ném KeyError nếu không có tool tên đó."""
        tool = self._tools[name]
        logger.debug("Chạy tool %s(%s)", name, arguments)
        return tool.handler(**(arguments or {}))


# --------------------------------------------------------------------------- #
# Bộ tool mặc định (điều khiển máy tính) dựng từ AssistantActions
# --------------------------------------------------------------------------- #
def build_default_registry(actions, scheduler=None) -> ToolRegistry:
    """Tạo registry điều khiển máy tính từ một facade actions (hoặc mock).

    Nếu truyền `scheduler` (ReminderScheduler) thì đăng ký thêm bộ tool lập lịch.
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
    ))

    reg.register(Tool(
        name="close_app",
        description="Đóng một ứng dụng đang chạy.",
        input_schema={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Tên ứng dụng cần đóng"},
            },
            "required": ["app_name"],
        },
        handler=lambda app_name: actions.close_application(app_name),
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
    ))

    reg.register(Tool(
        name="shutdown",
        description="Tắt máy tính. immediate=true để tắt ngay, không đóng ứng dụng trước.",
        input_schema={
            "type": "object",
            "properties": {
                "immediate": {"type": "boolean", "description": "Tắt ngay lập tức"},
            },
        },
        handler=lambda immediate=False: actions.system_shutdown(close_apps=not immediate),
    ))

    reg.register(Tool(
        name="restart",
        description="Khởi động lại máy tính. immediate=true để khởi động lại ngay.",
        input_schema={
            "type": "object",
            "properties": {
                "immediate": {"type": "boolean", "description": "Khởi động lại ngay"},
            },
        },
        handler=lambda immediate=False: actions.system_restart(close_apps=not immediate),
    ))

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

    return reg


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

    reg.register(Tool(
        name="schedule_reminder",
        description="Đặt một lời nhắc vào thời điểm sau này. Cho 'delay_minutes' "
                    "(số phút nữa) HOẶC 'at' (giờ dạng HH:MM, hoặc ISO datetime).",
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
        name="list_reminders",
        description="Liệt kê các lịch nhắc đang có.",
        input_schema={"type": "object", "properties": {}},
        handler=list_reminders,
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
