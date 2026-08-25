"""
Dựng ToolRegistry đầy đủ từ danh mục feature.

Thay cho `agent/tools.py::build_default_registry` (đã xoá 2026-08-25). Hàm cũ nhận một
danh sách tham số dài dằng dặc — mỗi tính năng mới lại thêm một tham số, và biết tính
năng nào tồn tại thì phải đọc hết thân hàm 1.400 dòng. Giờ nguồn sự thật là
`features/catalog.py::FEATURES`.
"""

from agent.tools import ToolRegistry
from features.catalog import FEATURES
from features.contract import load_features


def build_registry(ctx, features=None):
    """Dựng registry từ `features` (mặc định là toàn bộ danh mục). Trả (registry, report).

    `report` mang tên tool của từng feature, số ký tự specs và các đoạn prompt — đủ để
    suy ra bảng case->tool cho router và để kiểm ngân sách, nên nơi gọi giữ lấy nó thay
    vì dựng lại bằng tay.
    """
    reg = ToolRegistry()
    report = load_features(reg, ctx, FEATURES if features is None else features)
    return reg, report
