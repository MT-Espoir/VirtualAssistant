"""
Khoá TIỀN TỐ những gì gửi lên LLM mỗi lượt: khối tool specs và prompt gộp.

Vì sao đáng một file test riêng: Ollama tái dùng KV cache theo TIỀN TỐ. Đo trên máy này
(`docs/latency_optimization_spec.md`) — prompt lặp y hệt đọc ở 18.751 tok/s, prompt lệch
ngay từ đầu chỉ 68 tok/s, chênh ~16-20 giây MỖI LƯỢT. Mà thứ tự tool đổi thì không có
triệu chứng nào ngoài "sao dạo này chậm thế": không lỗi, không test đỏ, không log.

Tiền tố system prompt (BASE+CASE ở đầu, thời gian/hồ sơ ở cuối) đã được khoá trong
`test_agent.py`. File này khoá phần CÒN LẠI — khối tool và prompt gộp — vốn sẽ bị đợt
refactor feature-module đụng vào nhiều nhất.
"""

import json

from unittest.mock import MagicMock

from agent.tools import build_default_registry
from features.contract import SPEC_CHARS_BUDGET
from llm import prompts


def _registry():
    """Registry ĐẦY ĐỦ — mọi dịch vụ đều có mặt, để đếm đúng tổng payload thật."""
    return build_default_registry(MagicMock(), scheduler=MagicMock(), browser=MagicMock(),
                                  screen=MagicMock(), profile=MagicMock(), tasks=MagicMock(),
                                  routines=MagicMock(), contacts=MagicMock(), mcp=None,
                                  places=MagicMock(), location=MagicMock(), bus=MagicMock())


def _specs_json(reg):
    return json.dumps(reg.specs(), ensure_ascii=False)


# --- khối tool: phải tất định ------------------------------------------------------

def test_specs_giong_het_tung_byte_giua_hai_lan_dung():
    """Dựng registry hai lần -> JSON specs giống HỆT.

    Đây là cổng chính của đợt refactor feature-module: khi `build_default_registry` được
    thay bằng `load_features`, chỉ cần bộ nạp duyệt set/thư mục thay vì danh sách là
    test này đỏ.
    """
    assert _specs_json(_registry()) == _specs_json(_registry())


def test_thu_tu_ten_tool_khong_doi_giua_hai_lan_dung():
    """Tách riêng khỏi test trên để khi đỏ thì biết ngay là lệch THỨ TỰ hay lệch NỘI DUNG."""
    assert _registry().names() == _registry().names()


def test_khong_co_tool_trung_ten():
    reg = _registry()
    assert len(reg.names()) == len(set(reg.names()))


# --- prompt gộp: phải tất định (carryover latency_optimization_spec.md:106) ---------

def test_prompt_gop_on_dinh_giua_cac_luot():
    """`merged()` duyệt dict CASES nên thứ tự cố định — khoá lại để nó cứ thế mà cố định.

    Prompt gộp là đường chạy khi router TẮT (provider mạnh), tức đường chạy mặc định
    hiện nay. Nó đứng ở ĐẦU system prompt nên lệch một ký tự là mất cache cả lượt.
    """
    assert prompts.merged() == prompts.merged()


def test_prompt_gop_bat_dau_bang_base():
    """BASE phải ở ngay đầu; các fragment case xếp sau."""
    assert prompts.merged().startswith(prompts.base())


def test_moi_case_deu_co_mat_trong_prompt_gop():
    """Router tắt thì không ai chọn fragment nữa -> gộp thiếu case là mất chỉ dẫn riêng."""
    merged = prompts.merged()
    for name, fragment in prompts.load()["cases"].items():
        if fragment.strip():
            assert f"[{name}]" in merged, f"case {name} rơi khỏi prompt gộp"


# --- ngân sách: chặn phình âm thầm -------------------------------------------------

def test_tong_spec_chars_nam_trong_ngan_sach():
    """Đo 2026-08-25: 47 tool = 19.351 chars. Trần 20.000.

    Vượt trần KHÔNG phải lỗi chức năng — nó là chi phí mà LLM trả lại mỗi lượt, mãi mãi.
    Muốn nâng trần thì nâng có chủ đích kèm đo lại, đừng nâng cho test xanh.
    """
    total = len(_specs_json(_registry()))
    assert total <= SPEC_CHARS_BUDGET, (
        f"Tool specs phình lên {total} chars, quá trần {SPEC_CHARS_BUDGET}. "
        f"Nén mô tả tool, gom tool cùng nhóm, hoặc nâng trần có cân nhắc."
    )


def test_khong_tool_nao_phinh_qua_muc():
    """Một tool > 1.200 chars gần như luôn là mô tả viết dài dòng, không phải schema phức tạp.

    Ngưỡng đặt trên mức nặng nhất hiện tại (`remember_about_user` 1.092) — nó đã sát trần,
    ai nới thêm sẽ phải nhìn lại con số này.
    """
    reg = _registry()
    beo = {name: len(json.dumps(reg.get(name).spec(), ensure_ascii=False))
           for name in reg.names()}
    qua_beo = {n: c for n, c in beo.items() if c > 1_200}
    assert not qua_beo, f"tool có spec quá dài: {qua_beo}"
