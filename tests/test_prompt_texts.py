"""
Test prompt được LẮP RÁP từ các mảnh feature góp vào.

Trước đây file này chốt việc chuyển prompt từ JSON sang Python (Phase 0.5) bằng cách so
`prompt_texts.CASES`/`ROUTER` với bản JSON cũ. Bản JSON đã xoá, và các hằng đó cũng
không còn: mỗi feature nay mang theo đoạn prompt của mình, `llm/prompts.py` ghép lại từ
`LoadReport`. Vì vậy test ở đây kiểm PHẦN ĐÃ GHÉP, không kiểm hằng số rời.
"""

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))

from llm import prompt_texts, prompts                    # noqa: E402
from conftest import full_case_tools, full_report        # noqa: E402

CT = full_case_tools()


def _data():
    return prompts.load(full_report())


# --------------------------- bất biến cấu trúc --------------------------- #

def test_load_returns_expected_shape():
    data = _data()
    assert set(data) == {"base", "router", "cases"}
    assert data["base"] == prompt_texts.BASE


def test_base_matches_load():
    assert prompts.base() == _data()["base"]


def test_load_returns_fresh_cases_copy():
    """Router giữ `self.data` — sửa nó không được làm hỏng dữ liệu dùng chung."""
    a = _data()
    a["cases"]["web"] = "ĐÃ SỬA"
    assert _data()["cases"]["web"] != "ĐÃ SỬA"


def test_case_keys_match_case_tools():
    """Mỗi case có tool phải có fragment prompt — lệch = case không dùng được."""
    assert set(_data()["cases"]) == set(CT)


def test_prompts_not_empty():
    assert prompt_texts.BASE.strip()
    assert _data()["router"].strip()


# --------------------------- prompt phân loại --------------------------- #

def test_router_prompt_lists_every_case():
    """Prompt phân loại phải mô tả MỌI case, kể cả 'general'."""
    router_text = _data()["router"]
    for name in CT:
        assert f"- {name}:" in router_text, f"prompt ROUTER thiếu mô tả case '{name}'"


def test_router_keyword_list_khop_voi_phan_mo_ta():
    """Danh sách từ khoá ở đầu prompt phải khớp đúng các case được mô tả bên dưới.

    HỒI QUY: bản viết tay từng liệt kê 10 từ khoá nhưng THIẾU `pim`, dù `pim` được mô tả
    ngay bên dưới — model bị bảo "chỉ trả về một trong các từ này" mà từ đó không có
    trong danh sách. Nay danh sách sinh từ chính các feature đã nạp nên không lệch được;
    test khoá lại điều đó.
    """
    router_text = _data()["router"]
    dau = router_text[router_text.index("(") + 1:router_text.index(")")]
    assert set(dau.split("/")) == set(CT)


def test_router_giu_luu_y_phan_biet_lien_case():
    """Phần đuôi phân biệt các cặp dễ lẫn là chuyện LIÊN case, không thuộc feature nào."""
    router_text = _data()["router"]
    assert "LƯU Ý phân biệt" in router_text
    assert router_text.rstrip().endswith(prompt_texts.ROUTER_TAIL)


# --------------------------- prompt gộp (chế độ không router) --------------------------- #

def test_merged_contains_base():
    assert prompt_texts.BASE in prompts.merged(full_report())


def test_merged_keeps_every_non_empty_fragment():
    """Bẫy chính khi bỏ router: mất chỉ dẫn theo case. Test này chặn đúng chỗ đó."""
    merged = prompts.merged(full_report())
    for name, fragment in _data()["cases"].items():
        if fragment.strip():
            assert fragment in merged, f"prompt gộp làm MẤT fragment '{name}'"


def test_merged_preserves_critical_instructions():
    """Chốt cụ thể các fix dễ mất nhất khi gộp (7.1 đọc kết quả, danh bạ, remind vs do)."""
    merged = prompts.merged(full_report())
    assert "ĐÁNH SỐ" in merged                 # fix 7.1: đọc nguyên văn kết quả tìm web
    assert "gws_contacts_search" in merged     # tra danh bạ trước khi soạn mail
    assert "schedule_action" in merged or "TỰ LÀM" in merged   # phân biệt nhắc vs tự làm


def test_merged_labels_each_group():
    merged = prompts.merged(full_report())
    for name, fragment in _data()["cases"].items():
        if fragment.strip():
            assert f"[{name}]" in merged


def test_merged_skips_empty_fragment():
    # 'general' rỗng -> không tạo nhãn trống vô nghĩa
    assert not _data()["cases"]["general"].strip()
    assert "[general]" not in prompts.merged(full_report())


# --------------------------- DoD: thêm feature chỉ tốn một thư mục --------------------------- #

def test_them_feature_khong_phai_sua_prompt_texts():
    """Feature mới góp prompt qua hợp đồng, KHÔNG phải sửa `prompt_texts`.

    Đây là tiêu chí chấp nhận của đợt refactor: thêm tính năng = tạo một thư mục dưới
    `features/` + một dòng trong `catalog.py`. Trước khi có việc này, còn phải thêm case
    vào `prompt_texts.CASES` VÀ thêm một dòng mô tả vào hằng `ROUTER` — hai chỗ dễ quên,
    mà quên thì tính năng chết lặng.

    Kiểm bằng một feature dựng tại chỗ: nó phải tự xuất hiện đủ trong cả ba đầu ra.
    """
    from agent.tools import ToolRegistry
    from features.contract import Feature, FeatureContext, load_features

    demo = Feature(name="demo", prompt="Chỉ dẫn riêng của demo.",
                   router_hint="- demo: người dùng nói 'ping'")
    report = load_features(ToolRegistry(), FeatureContext(), [demo])
    data = prompts.load(report)

    assert data["cases"]["demo"] == "Chỉ dẫn riêng của demo."
    assert "- demo: người dùng nói 'ping'" in data["router"]
    assert "(demo/general)" in data["router"], "danh sách từ khoá phải tự có case mới"
    assert "[demo] Chỉ dẫn riêng của demo." in prompts.merged(report)


def test_feature_bi_tat_thi_bien_khoi_prompt_phan_loai():
    """Tắt feature bằng config cũng gỡ nó khỏi prompt — trước đây prompt vẫn mô tả nhóm
    không còn tool nào, tức dạy model chọn một case rồi thu hẹp xuống rỗng."""
    from agent.tools import ToolRegistry
    from features.contract import Feature, FeatureContext, load_features

    tat = Feature(name="demo", prompt="x", router_hint="- demo: y",
                  enabled=lambda: False)
    data = prompts.load(load_features(ToolRegistry(), FeatureContext(), [tat]))

    assert "demo" not in data["cases"]
    assert "- demo:" not in data["router"]
