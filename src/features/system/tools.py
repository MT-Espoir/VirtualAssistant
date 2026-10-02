"""
Tool của feature `system` — Điều khiển máy: mở/đóng ứng dụng, cửa sổ, âm lượng, độ sáng, thông tin máy.

Chuyển nguyên văn khối `reg.register(Tool(...))` từ
`agent/tools.py::build_default_registry` (2026-08-25). Nội dung từng tool KHÔNG
sửa một ký tự; chỉ bọc lại trong `register(reg, ctx)` của hợp đồng feature.
"""

from agent.tools import Tool


def _emit_system(bus, kind, rows, **context):
    """Đẩy snapshot sang UI nếu app có bus; CLI/legacy vẫn chạy bình thường."""
    if bus is not None:
        bus.emit_system(kind, rows, **context)


def _list_processes(actions, bus, sort_by="memory", limit=3):
    # Stub cũ trong test/legacy chỉ có `list_processes`: kiểm trên LỚP để MagicMock không
    # tự bịa ra một method truthy rồi làm hỏng phép unpack hai giá trị.
    if bus is None or getattr(type(actions), "process_report", None) is None:
        return actions.list_processes(sort_by=sort_by, limit=limit)
    summary, rows = actions.process_report(sort_by=sort_by, limit=limit)
    _emit_system(bus, "processes", rows, sort_by=sort_by)
    return summary


def _audio_device(actions, bus, action="list", name=None):
    if bus is None or getattr(type(actions), "audio_device_report", None) is None:
        return actions.audio_device(action=action, name=name)
    summary, rows = actions.audio_device_report(action=action, name=name)
    _emit_system(bus, "audio_devices", rows)
    return summary


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
        # Tool DUY NHẤT hiện được phép chạy trên vòng nền tự động (hạ sáng khi pin yếu).
        # Đủ điều kiện vì hoàn tác được bằng một câu: "sáng lên". Xem `Tool.tu_dong`.
        tu_dong=True,
    ))

    reg.register(Tool(
        name="system_info",
        description="Xem RAM, ổ đĩa, CPU, pin hoặc mạng nội bộ.",
        input_schema={
            "type": "object",
            "properties": {
                "what": {"type": "string",
                         "enum": ["all", "memory", "disk", "cpu", "battery", "network"],
                         "description": "Mục xem; mặc định all"},
            },
        },
        handler=lambda what="all": actions.system_info(what),
        speakable=True,      # "RAM: đã dùng 9.8 GB/15.4 GB (64%)..."
        # SSID do bên ngoài đặt. Đánh dấu cả tool vì cờ hiện nằm ở cấp tool, không ở enum;
        # đổi lại mọi lần xem chỉ số đều đi theo nhánh an toàn hơn.
        untrusted_output=True,
    ))

    reg.register(Tool(
        name="list_processes",
        description="Xem ứng dụng nào đang ngốn RAM hoặc CPU nhất khi máy chậm.",
        input_schema={
            "type": "object",
            "properties": {
                "sort_by": {"type": "string", "enum": ["memory", "cpu"],
                            "description": "Xếp theo RAM hay CPU"},
                "limit": {"type": "integer", "description": "Lấy mấy cái đầu"},
            },
        },
        handler=lambda sort_by="memory", limit=3: _list_processes(
            actions, ctx.bus, sort_by=sort_by, limit=limit),
        speakable=True,
        # CHỈ ĐỌC nên không `destructive`. Nhưng vẫn là `admin`: biết ứng dụng nào đang mở
        # là bước do thám tự nhiên trước một lệnh kill/tắt máy, và một trang web không có
        # việc gì phải biết người dùng đang chạy gì.
        admin=True,
    ))

    reg.register(Tool(
        name="power",
        description="Nguồn máy: khoá màn hình, ngủ, khởi động lại, tắt máy, hoặc huỷ lệnh đã hẹn.",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "enum": ["lock", "sleep", "restart", "shutdown", "cancel"],
                           "description": "Việc cần làm"},
                "delay_minutes": {"type": "integer",
                                  "description": "Hẹn mấy phút nữa"},
            },
            "required": ["action"],
        },
        handler=lambda action=None, delay_minutes=None: actions.control_power(
            action=action, delay_minutes=delay_minutes),
        speakable=True,
        # Chỉ HAI trong năm việc là khó hoàn tác. Cờ tĩnh thì hoặc tắt máy không hỏi, hoặc
        # khoá màn hình cũng phải xác nhận — đúng cái bẫy `docs/system_admin_spec.md` §3.
        # `cancel` cố ý KHÔNG cần duyệt: nó là đường thoát, phải dễ nhất trong cả bộ.
        destructive=lambda action=None, **_: action in ("restart", "shutdown"),
        confirm_message=lambda action=None, delay_minutes=None, **_: (
            "tắt máy" if action == "shutdown" else "khởi động lại máy"),
        admin=True,
        cam=lambda action=None, **_: cam_power(action),
    ))

    reg.register(Tool(
        name="kill_process",
        description="Kết thúc một ứng dụng đang chạy theo tên hoặc pid, khi nó treo hoặc ngốn máy.",
        input_schema={
            "type": "object",
            "properties": {
                "name_or_pid": {"type": "string", "description": "Tên tiến trình hoặc pid"},
            },
            "required": ["name_or_pid"],
        },
        handler=lambda name_or_pid=None: actions.kill_process(name_or_pid),
        speakable=True,
        destructive=True,     # mất việc chưa lưu, không hoàn tác được
        confirm_message=lambda name_or_pid=None, **_: f"tắt tiến trình {name_or_pid}",
        admin=True,
        cam=lambda name_or_pid=None, **_: cam_kill(name_or_pid),
    ))

    reg.register(Tool(
        name="keep_awake",
        description="Giữ máy không tự ngủ (vd đang tải file), hoặc thôi giữ.",
        input_schema={
            "type": "object",
            "properties": {
                "on": {"type": "boolean", "description": "true = giữ thức, false = thôi"},
                "minutes": {"type": "integer", "description": "Tự thôi sau mấy phút"},
            },
        },
        handler=lambda on=True, minutes=None: actions.keep_awake(on=on, minutes=minutes),
        speakable=True,
        # Dù hoàn tác được, giữ máy thức vẫn thay đổi trạng thái nguồn và có thể kéo dài
        # vô hạn. Nội dung web không được phép mớm hành động này qua một lượt đã nhiễm.
        admin=True,
    ))

    reg.register(Tool(
        name="audio_device",
        description="Xem hoặc đổi thiết bị phát âm thanh (loa, tai nghe).",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "switch"],
                           "description": "Xem hay đổi"},
                "name": {"type": "string", "description": "Tên thiết bị muốn chuyển sang"},
            },
        },
        handler=lambda action="list", name=None: _audio_device(
            actions, ctx.bus, action=action, name=name),
        speakable=True,
        # Tên thiết bị do phần cứng/driver đặt, không do ta — nhưng cũng không do bên ngoài
        # đặt được từ xa. Cùng lằn ranh với `list_processes`, xem `test_untrusted_content`.
        admin=True,
    ))


def cam_power(action):
    """Lý do TUYỆT ĐỐI không chạy `power`, hoặc None. Người dùng đồng ý cũng không mở được.

    Tách ra khỏi lambda để test gọi thẳng được — đây là luật an toàn, phải kiểm được mà
    không phải dựng cả registry.
    """
    if (action or "").strip().lower() not in ("restart", "shutdown"):
        return None
    from actions.system.system_info import dang_cai_windows_update
    ten = dang_cai_windows_update()
    if ten:
        return (f"Windows đang cài cập nhật ({ten}), tắt máy lúc này có thể hỏng bản cài "
                "nên tôi không làm, kể cả khi bạn đồng ý")
    return None


def cam_kill(name_or_pid):
    """Lý do TUYỆT ĐỐI không chạy `kill_process`, hoặc None.

    Quy pid về TÊN trước khi so: cấm theo tên mà không quy đổi thì vòng qua được chỉ bằng
    cách nói số pid thay vì nói tên.
    """
    target = str(name_or_pid or "").strip().strip('"\'').lower()
    if target in {"camera", "webcam", "web cam", "cam", "camera.exe", "webcam.exe"}:
        return ("camera/webcam là tên thiết bị trong lệnh này, không phải tiến trình "
                "để kết thúc; hãy dùng lệnh tắt webcam của Alice")
    from actions.system.system_control import TIEN_TRINH_CAM, ten_tien_trinh
    ten = ten_tien_trinh(name_or_pid)
    if ten and ten in TIEN_TRINH_CAM:
        return (f"{ten} là tiến trình lõi của Windows, tắt nó là máy sập xanh ngay "
                "nên tôi không làm, kể cả khi bạn đồng ý")
    return None
