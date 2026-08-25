"""
Tool của feature `profile` — Ghi nhớ / quên thông tin về người dùng.

Chuyển nguyên khối từ `agent/tools.py` (2026-08-25); thân hàm KHÔNG sửa một
dòng nào. `register(reg, ctx)` chỉ là lớp bọc mỏng lấy dependency từ ctx.
"""

from agent.tools import Tool, ToolRegistry



def register(reg, ctx):
    """Đăng ký tool của feature `profile` theo đúng thứ tự đăng ký cũ."""
    if ctx.profile is not None:
        _register_profile_tools(reg, ctx.profile)


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
