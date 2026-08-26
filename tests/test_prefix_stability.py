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

from conftest import full_registry, full_report
from llm import prompts


def _registry():
    """Registry đầy đủ — xem `conftest.full_registry` (tự suy tham số còn lại)."""
    return full_registry()


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
    assert prompts.merged(full_report()) == prompts.merged(full_report())


def test_prompt_gop_bat_dau_bang_base():
    """BASE phải ở ngay đầu; các fragment case xếp sau."""
    assert prompts.merged(full_report()).startswith(prompts.base())


def test_moi_case_deu_co_mat_trong_prompt_gop():
    """Router tắt thì không ai chọn fragment nữa -> gộp thiếu case là mất chỉ dẫn riêng."""
    merged = prompts.merged(full_report())
    for name, fragment in prompts.load(full_report())["cases"].items():
        if fragment.strip():
            assert f"[{name}]" in merged, f"case {name} rơi khỏi prompt gộp"


# --- ảnh chụp gốc: chứng minh refactor KHÔNG đổi hành vi ---------------------------

def test_specs_khop_anh_chup_truoc_refactor():
    """So với ảnh chụp `specs()` — bằng chứng refactor không đụng vào hành vi.

    Cùng cách làm đã dùng ở Phase 0.5 khi chuyển prompt từ JSON sang Python: so từng
    byte với bản gốc thay vì "chạy thử thấy ổn". Đổi tức là đã lỡ tay đụng vào hành vi —
    hoặc thứ tự nạp feature vừa xê dịch.

    ĐÃ CHỤP LẠI MỘT LẦN (2026-08-25, bước cuối việc 4). Suốt đợt migrate ảnh chụp giữ
    nguyên nhờ rút khối đăng ký CUỐI CÙNG trước; riêng nhóm lõi thì không giữ được:
    system/web/weather cài răng lược trong một khối `reg.register` liên tiếp, tách theo
    case tất yếu đổi thứ tự. Đã kiểm trước khi chụp lại: vẫn đúng 47 tool, nội dung TỪNG
    tool giống hệt, chỉ `get_weather` đổi vị trí. Prompt cũng nguyên vẹn — 11/11 case,
    BASE và ROUTER giống từng byte so với bản trong git.
    """
    import pathlib
    goc = pathlib.Path(__file__).parent / "fixtures" / "tool_specs_baseline.json"
    mong_doi = json.loads(goc.read_text(encoding="utf-8"))

    assert _registry().specs() == mong_doi, (
        "specs() lệch khỏi ảnh chụp trước refactor. Nếu KHÔNG cố ý đổi tool nào, đây là "
        "dấu hiệu thứ tự nạp feature vừa xê dịch -> mất KV cache mỗi lượt."
    )
