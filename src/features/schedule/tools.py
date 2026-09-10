"""
Tool của feature `schedule` — Nhắc giờ và hẹn hành động. Kèm bộ phân tích thời điểm chịu lỗi.

Chuyển nguyên khối từ `agent/tools.py` (2026-08-25); thân hàm KHÔNG sửa một
dòng nào. `register(reg, ctx)` chỉ là lớp bọc mỏng lấy dependency từ ctx.
"""

from agent.tools import Tool, ToolRegistry
from datetime import datetime, timedelta
from utils.text_norm import strip_accents
import re



def register(reg, ctx):
    """Đăng ký tool của feature `schedule` theo đúng thứ tự đăng ký cũ."""
    if ctx.scheduler is not None:
        _register_schedule_tools(reg, ctx.scheduler)


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
        # HẸN CHẠY MỘT LỆNH là hành động khó hoàn tác, và tệ hơn: nó chạy LÚC NGƯỜI
        # DÙNG KHÔNG NGỒI TRƯỚC MÁY. Đây là cơ chế duy nhất cho phép một lần tiêm
        # (prompt injection) tồn tại quá lượt hiện tại mà không cần đụng tới trí nhớ.
        destructive=True,
        confirm_message=lambda command=None, **_: f"hẹn tự làm: {command}",
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
