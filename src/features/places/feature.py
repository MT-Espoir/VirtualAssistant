"""Khai báo Feature `place` — tách khỏi `__init__.py` để package nhẹ khi chỉ cần prompt."""

from features.contract import Feature
from features.places import tools
from features.places.prompt import CASE_PLACE, ROUTER_HINT

# Tên feature = tên router case. Là "place" (số ít) chứ không phải "places" — phải khớp
# khoá cũ trong `CASE_TOOLS`/`CASES`, nếu không router sẽ không tìm ra fragment prompt.
FEATURE = Feature(
    name="place",
    register=tools.register,
    # Đúng điều kiện cũ trong `build_default_registry`: cần CẢ nguồn dữ liệu lẫn kho vị
    # trí. `browser` và `bus` là tuỳ chọn (thiếu thì mất mở link/panel, không mất tra cứu)
    # nên KHÔNG khai ở đây — khai vào là feature tự tắt oan khi Chrome chưa chạy.
    requires=("places", "location"),
    prompt=CASE_PLACE,
    router_hint=ROUTER_HINT,
    # Đo 2026-08-25: 6 tool = 3.341 chars. Đây là feature nặng nhất hệ thống — nếu phải
    # nén payload thì bắt đầu từ đây (xem việc 12: gom 6 tool thành 1 + `action` enum).
    max_spec_chars=3_800,
)
