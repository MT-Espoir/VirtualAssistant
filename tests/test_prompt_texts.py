"""Test prompt_texts / prompts — chốt việc chuyển JSON -> Python KHÔNG đổi nội dung.

Test chính (`test_matches_legacy_json_byte_for_byte`) so từng byte với bản JSON cũ còn
giữ trong repo làm bản tham chiếu. Nếu ai đó xoá file JSON, test tự bỏ qua (skip) —
lúc đó các test bất biến còn lại vẫn bảo vệ cấu trúc.
"""

import json
import os
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))

from llm import prompt_texts, prompts          # noqa: E402
from agent.router import CASE_TOOLS            # noqa: E402

_LEGACY_JSON = _SRC / "components" / "data" / "system_prompt.json"


def test_matches_legacy_json_byte_for_byte():
    """Refactor JSON -> Python phải giữ nội dung Y HỆT (không 'tin là đúng')."""
    if not os.path.exists(_LEGACY_JSON):
        pytest.skip("Đã xoá bản JSON tham chiếu")
    with open(_LEGACY_JSON, encoding="utf-8") as f:
        legacy = json.load(f)

    assert prompt_texts.BASE == legacy["base"]
    assert prompt_texts.ROUTER == legacy["router"]
    assert set(prompt_texts.CASES) == set(legacy["cases"])
    for name, text in legacy["cases"].items():
        assert prompt_texts.CASES[name] == text, f"case '{name}' lệch nội dung"


# --------------------------- bất biến cấu trúc --------------------------- #

def test_load_returns_expected_shape():
    data = prompts.load()
    assert set(data) == {"base", "router", "cases"}
    assert data["base"] == prompt_texts.BASE
    assert data["router"] == prompt_texts.ROUTER


def test_base_matches_load():
    assert prompts.base() == prompts.load()["base"]


def test_load_returns_fresh_cases_copy():
    """Router giữ `self.data` — sửa nó không được làm hỏng hằng dùng chung."""
    a = prompts.load()
    a["cases"]["web"] = "ĐÃ SỬA"
    assert prompts.load()["cases"]["web"] != "ĐÃ SỬA"


def test_case_keys_match_router_case_tools():
    """Khoá fragment phải khớp CASE_TOOLS — lệch = có case không bao giờ được dùng."""
    assert set(prompt_texts.CASES) == set(CASE_TOOLS)


def test_prompts_not_empty():
    assert prompt_texts.BASE.strip()
    assert prompt_texts.ROUTER.strip()


# --------------------------- prompt gộp (chế độ không router) --------------------------- #

def test_merged_contains_base():
    assert prompt_texts.BASE in prompts.merged()


def test_merged_keeps_every_non_empty_fragment():
    """Bẫy chính khi bỏ router: mất chỉ dẫn theo case. Test này chặn đúng chỗ đó."""
    merged = prompts.merged()
    for name, fragment in prompt_texts.CASES.items():
        if fragment.strip():
            assert fragment in merged, f"prompt gộp làm MẤT fragment '{name}'"


def test_merged_preserves_critical_instructions():
    """Chốt cụ thể các fix dễ mất nhất khi gộp (7.1 đọc kết quả, danh bạ, remind vs do)."""
    merged = prompts.merged()
    assert "ĐÁNH SỐ" in merged                 # fix 7.1: đọc nguyên văn kết quả tìm web
    assert "gws_contacts_search" in merged     # tra danh bạ trước khi soạn mail
    assert "schedule_action" in merged or "TỰ LÀM" in merged   # phân biệt nhắc vs tự làm


def test_merged_labels_each_group():
    merged = prompts.merged()
    for name, fragment in prompt_texts.CASES.items():
        if fragment.strip():
            assert f"[{name}]" in merged


def test_merged_skips_empty_fragment():
    # 'general' rỗng -> không tạo nhãn trống vô nghĩa
    assert not prompt_texts.CASES["general"].strip()
    assert "[general]" not in prompts.merged()


def test_router_prompt_lists_every_case():
    """Prompt phân loại phải nhắc tới mọi case (trừ 'general' là mặc định)."""
    router_text = prompt_texts.ROUTER
    for name in CASE_TOOLS:
        assert f"- {name}:" in router_text, f"ROUTER thiếu mô tả case '{name}'"
