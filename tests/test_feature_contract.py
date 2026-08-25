"""Test hợp đồng feature + bộ nạp (features/contract.py) — feature giả, không đụng LLM."""

try:
    import pytest
except ImportError:
    pytest = None

from agent.tools import Tool, ToolRegistry
from features.contract import (Feature, FeatureContext, SPEC_CHARS_BUDGET,
                               load_features)


def _tool(name, description="mô tả ngắn"):
    return Tool(name=name, description=description,
                input_schema={"type": "object", "properties": {}},
                handler=lambda: "xong")


def _feature(name, tool_names, **kwargs):
    """Feature giả đăng ký sẵn một số tool tên cho trước."""
    def register(reg, ctx):
        for tool_name in tool_names:
            reg.register(_tool(tool_name))
    return Feature(name=name, register=register, **kwargs)


# --- điều kiện nạp -----------------------------------------------------------------

def test_thieu_dependency_thi_bo_qua_khong_crash():
    reg = ToolRegistry()
    ctx = FeatureContext(browser=None)          # thiếu browser
    feat = _feature("place", ["find_nearby"], requires=("browser",))

    report = load_features(reg, ctx, [feat])

    assert report.loaded == []
    assert report.skipped == [("place", "thiếu browser")]
    assert not reg.has("find_nearby")           # không đăng ký nửa vời


def test_du_dependency_thi_nap():
    reg = ToolRegistry()
    ctx = FeatureContext(browser=object(), location=object())
    feat = _feature("place", ["find_nearby"], requires=("browser", "location"))

    report = load_features(reg, ctx, [feat])

    assert [f.name for f in report.loaded] == ["place"]
    assert reg.has("find_nearby")


def test_tat_bang_config_thi_bo_qua():
    reg = ToolRegistry()
    feat = _feature("screen", ["take_screenshot"], enabled=lambda: False)

    report = load_features(reg, FeatureContext(), [feat])

    assert report.skipped == [("screen", "tắt bằng config")]
    assert not reg.has("take_screenshot")


def test_requires_go_sai_ten_thi_nem_ngay():
    """Gõ sai tên dependency làm feature tắt vĩnh viễn trong im lặng -> phải ném."""
    with pytest.raises(ValueError) as err:
        Feature(name="place", requires=("brower",))     # thiếu chữ 's'

    assert "brower" in str(err.value)


# --- suy ra CASE_TOOLS -------------------------------------------------------------

def test_case_tools_suy_ra_dung_tool_cua_tung_feature():
    """Điểm chính của refactor: router không còn bảng chép tay lệch pha với registry."""
    reg = ToolRegistry()
    features = [_feature("weather", ["get_weather"]),
                _feature("web", ["web_search", "open_website"])]

    report = load_features(reg, FeatureContext(), features)

    assert report.case_tools() == {"weather": ["get_weather"],
                                   "web": ["web_search", "open_website"]}


def test_feature_khong_co_tool_thi_khong_thanh_case():
    reg = ToolRegistry()
    features = [_feature("web", ["web_search"]),
                Feature(name="general", prompt="cứ trò chuyện bình thường")]

    report = load_features(reg, FeatureContext(), features)

    assert "general" not in report.case_tools()
    assert ("general", "cứ trò chuyện bình thường") in report.prompt_fragments()


# --- thứ tự (ràng buộc hiệu suất) --------------------------------------------------

def test_thu_tu_tool_bam_theo_thu_tu_danh_sach_feature():
    """Thứ tự quyết định tiền tố prompt -> quyết định KV cache. Phải bám danh sách."""
    features = [_feature("a", ["a1", "a2"]), _feature("b", ["b1"])]

    reg1 = ToolRegistry()
    load_features(reg1, FeatureContext(), features)

    reg2 = ToolRegistry()
    load_features(reg2, FeatureContext(), list(reversed(features)))

    assert reg1.names() == ["a1", "a2", "b1"]
    assert reg2.names() == ["b1", "a1", "a2"]       # đảo danh sách -> đảo tiền tố


def test_nap_hai_lan_cho_ket_qua_giong_het():
    """Cùng danh sách -> cùng thứ tự, mọi lần. Nền của test khoá tiền tố (việc 2)."""
    features = [_feature("a", ["a1", "a2"]), _feature("b", ["b1"])]

    reg1, reg2 = ToolRegistry(), ToolRegistry()
    r1 = load_features(reg1, FeatureContext(), features)
    r2 = load_features(reg2, FeatureContext(), features)

    assert reg1.names() == reg2.names()
    assert r1.case_tools() == r2.case_tools()
    assert r1.spec_chars == r2.spec_chars


# --- ngân sách ---------------------------------------------------------------------

def test_dem_spec_chars_theo_tung_feature():
    reg = ToolRegistry()
    report = load_features(reg, FeatureContext(), [_feature("web", ["web_search"])])

    assert report.loaded[0].spec_chars > 0
    assert report.spec_chars == report.loaded[0].spec_chars


def test_vuot_tran_van_nap_nhung_co_canh_bao(caplog):
    """Vượt trần làm prompt đắt lên, không làm sai chức năng -> cảnh báo, không ném.
    Cổng cứng nằm ở test ngân sách, không nằm ở đường chạy của người dùng."""
    reg = ToolRegistry()
    feat = _feature("phinh", ["tool_dai"], max_spec_chars=10)

    report = load_features(reg, FeatureContext(), [feat])

    assert reg.has("tool_dai")                       # vẫn nạp
    assert "vượt trần specs" in caplog.text


def test_ngan_sach_tong_la_mot_con_so_duong():
    """Khoá hằng số lại — sửa nó phải là hành động có chủ đích, kèm đo lại."""
    assert SPEC_CHARS_BUDGET == 20_000
