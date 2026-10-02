"""
Tool của feature `profile` — Ghi nhớ / quên thông tin về người dùng.

"""

from agent.tools import Tool, ToolRegistry


def _export_memory(profile):
    path = profile.export_data()
    return f"Đã xuất dữ liệu bộ nhớ ra: {path}"


def _clear_memory(profile, habits=None):
    profile.clear()
    if habits is not None:
        habits.clear()
    return "Đã xóa toàn bộ hồ sơ, sở thích và trí nhớ dài hạn về bạn."


def _manage_memory(profile, action, habits=None):
    if action == "export":
        return _export_memory(profile)
    if action == "delete_all":
        return _clear_memory(profile, habits)
    return "Hành động quản lý bộ nhớ không hợp lệ."



def register(reg, ctx):
    """Đăng ký tool của feature `profile` theo đúng thứ tự đăng ký cũ."""
    if ctx.profile is not None:
        _register_profile_tools(reg, ctx.profile, ctx.habits)


def _register_profile_tools(reg: ToolRegistry, profile, habits=None):
    """Tool ghi nhớ thông tin cá nhân LÂU DÀI về người dùng (tên, xưng hô, địa điểm...)."""
    reg.register(Tool(
        name="remember_about_user",
        description=("Ghi nhớ LÂU DÀI thông tin người dùng vừa trực tiếp cho biết. Chỉ "
                     "truyền trường họ thực sự nói. Nếu note là sự kiện có thời điểm "
                     "(cuộc hẹn, deadline), phải truyền thêm when để sự kiện tự hết hạn."),
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
        persistent=True,
    ))

    reg.register(Tool(
        name="forget_about_user",
        description=("QUÊN ghi chú, quan sát hoặc sự kiện theo từ khoá khi họ "
                     "yêu cầu đừng nhớ điều cụ thể đó; hệ thống hỏi xác nhận trước khi xóa."),
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

    reg.register(Tool(
        name="manage_user_memory",
        description=("Quản lý TOÀN BỘ trí nhớ người dùng: export tạo bản JSON cục bộ; "
                     "delete_all xóa sạch hồ sơ/sở thích/trí nhớ. Xóa một mục riêng lẻ "
                     "thì dùng forget_about_user."),
        input_schema={
            "type": "object",
            "properties": {"action": {"type": "string",
                                        "enum": ["export", "delete_all"]}},
            "required": ["action"],
        },
        handler=lambda action: _manage_memory(profile, action, habits),
        destructive=lambda action=None: action == "delete_all",
        confirm_message=lambda action=None: (
            "xóa toàn bộ hồ sơ và trí nhớ dài hạn về bạn"
            if action == "delete_all" else "quản lý bộ nhớ người dùng"),
        persistent=True,
        speakable=True,
    ))
