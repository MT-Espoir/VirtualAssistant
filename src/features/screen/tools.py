"""
Tool của feature `screen` — Chụp / tìm chữ / cuộn màn hình. Local-only, opt-in bằng config.

Chuyển nguyên khối từ `agent/tools.py` (2026-08-25); thân hàm KHÔNG sửa một
dòng nào. `register(reg, ctx)` chỉ là lớp bọc mỏng lấy dependency từ ctx.
"""

from agent.tools import Tool, ToolRegistry



def register(reg, ctx):
    """Đăng ký tool của feature `screen` theo đúng thứ tự đăng ký cũ."""
    if ctx.screen is not None:
        _register_screen_tools(reg, ctx.screen)


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
        untrusted_output=True,   # nội dung do bên ngoài kiểm soát
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
