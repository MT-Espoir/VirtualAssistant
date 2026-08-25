"""Test feature `place` sau khi chuyển sang hợp đồng feature-module."""

from unittest.mock import MagicMock

from agent.router import CASE_TOOLS
from agent.tools import ToolRegistry
from features.contract import FeatureContext, load_features
from features.places.feature import FEATURE
from llm import prompts


def _ctx(**kwargs):
    base = dict(places=MagicMock(), location=MagicMock(), browser=MagicMock(),
                bus=MagicMock())
    base.update(kwargs)
    return FeatureContext(**base)


def _load(ctx=None):
    reg = ToolRegistry()
    report = load_features(reg, ctx or _ctx(), [FEATURE])
    return reg, report


# --- khai báo -----------------------------------------------------------------------

def test_ten_feature_khop_ten_router_case():
    """Tên feature DÙNG LUÔN làm tên case; lệch là router không tìm ra fragment prompt."""
    assert FEATURE.name == "place"
    assert FEATURE.name in CASE_TOOLS


def test_dang_ky_du_sau_tool():
    reg, report = _load()
    assert len(report.loaded[0].tools) == 6
    for name in ("find_nearby", "find_place", "research_places",
                 "open_place_result", "refine_places", "set_my_location"):
        assert reg.has(name)


def test_thieu_nguon_du_lieu_thi_tu_tat():
    """Đúng điều kiện cũ trong `build_default_registry`: cần CẢ places lẫn location."""
    for thieu in ("places", "location"):
        reg, report = _load(_ctx(**{thieu: None}))
        assert report.loaded == []
        assert report.skipped == [("place", f"thiếu {thieu}")]
        assert reg.names() == []


def test_thieu_browser_van_chay():
    """browser/bus là TUỲ CHỌN — thiếu thì mất mở link và panel, không mất tra cứu.

    Khai chúng vào `requires` sẽ làm cả tính năng tắt oan mỗi khi Chrome chưa chạy.
    """
    reg, report = _load(_ctx(browser=None, bus=None))
    assert [f.name for f in report.loaded] == ["place"]
    assert reg.has("find_nearby")


# --- bắc cầu sang việc xoá CASE_TOOLS viết tay ---------------------------------------

def test_tool_suy_ra_trung_khop_bang_case_tools_viet_tay():
    """Bảng `CASE_TOOLS["place"]` chép tay phải khớp thứ registry thật nhận.

    Đây là bằng chứng để xoá bảng đó (việc 5): nếu hai bên đã trùng thì thay bảng chép
    tay bằng bảng suy ra không đổi hành vi. So bằng TẬP HỢP vì bảng cũ liệt kê theo thứ
    tự khác thứ tự đăng ký.
    """
    _, report = _load()
    assert set(report.case_tools()["place"]) == set(CASE_TOOLS["place"])


def test_doan_prompt_giu_nguyen_van():
    """Text đã chuyển sang `features/places/prompt.py`; `CASES` nhập ngược nên phải y hệt."""
    assert FEATURE.prompt == prompts.load()["cases"]["place"]
    assert FEATURE.prompt.strip(), "fragment rỗng -> router mất chỉ dẫn riêng cho case place"


# --- ngân sách ----------------------------------------------------------------------

def test_nam_trong_tran_da_khai():
    """Feature nặng nhất hệ thống (đo 2026-08-25: 3.341 chars). Trần khai 3.500."""
    _, report = _load()
    assert report.spec_chars <= FEATURE.max_spec_chars
