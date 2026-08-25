"""
Tool của feature `weather` — Thời tiết theo địa điểm, mặc định lấy từ hồ sơ người dùng.

Chuyển nguyên văn khối `reg.register(Tool(...))` từ
`agent/tools.py::build_default_registry` (2026-08-25). Nội dung từng tool KHÔNG
sửa một ký tự; chỉ bọc lại trong `register(reg, ctx)` của hợp đồng feature.
"""

from agent.tools import Tool


def register(reg, ctx):
    """Đăng ký tool của feature `weather`."""
    actions, profile = ctx.actions, ctx.profile

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
