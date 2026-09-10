"""
Tool của feature `system` — Điều khiển máy: mở/đóng ứng dụng, cửa sổ, âm lượng, độ sáng, thông tin máy.

Chuyển nguyên văn khối `reg.register(Tool(...))` từ
`agent/tools.py::build_default_registry` (2026-08-25). Nội dung từng tool KHÔNG
sửa một ký tự; chỉ bọc lại trong `register(reg, ctx)` của hợp đồng feature.
"""

from agent.tools import Tool


def register(reg, ctx):
    """Đăng ký tool của feature `system`."""
    actions = ctx.actions

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
        habit=("app_name", "mở {}"),   # app mở đi mở lại = thói quen dùng máy
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
        untrusted_output=True,   # nội dung do bên ngoài kiểm soát
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
