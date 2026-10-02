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

    CHỤP LẠI LẦN NĂM (2026-09-19): Phase 2 của SQLite memory thêm hai thao tác kiểm
    soát dữ liệu ở cuối feature `profile`: manage_user_memory với hai action export và
    delete_all. Tool mới chèn ngay sau các tool profile hiện hữu; thứ tự toàn registry
    vẫn tất định và ảnh chụp mới khóa chủ đích thay đổi này.

    CHỤP LẠI LẦN SÁU (2026-09-20): Phase A+B của Activity Insights thêm đúng một tool
    read-only ở CUỐI catalog. Toàn bộ 53 tool cũ giữ nguyên vị trí và nội dung; chỉ nối
    `activity_insights` vào cuối nên tiền tố cache cũ được giữ dài nhất có thể.

    CHỤP LẠI LẦN BẢY (2026-09-21): Phase C mở rộng chính `activity_insights` bằng action
    phân loại/exclude/reset/xóa lịch sử, không thêm tool thứ 55. 53 tool đứng trước giữ
    nguyên từng byte; tool cuối đổi có chủ đích và vẫn nằm trong ngân sách catalog.

    CHỤP LẠI LẦN BỐN (2026-09-12): thêm nốt Tầng 1 — `kill_process`, `keep_awake`,
    `audio_device` (`docs/system_admin_spec.md` §4). Cùng kiểu dịch chỗ như lần ba: chúng
    vào vị trí 10-12 nên đẩy 40 tool phía sau, tiền tố chung còn 9 tool. Nội dung tool cũ
    không đổi ký tự nào.

    Và từ lần này chi phí đó NHỎ HƠN HẲN, vì bề mặt mặc định không còn là `AllTools`: với
    `IndexedTools`, thứ gửi đi mỗi lượt là bộ lõi (19 tool) — cả ba tool mới đều nằm NGOÀI
    lõi nên tiền tố của đường chạy THẬT không hề đổi. Ảnh chụp này giờ canh đường dự phòng.

    CHỤP LẠI LẦN BA (2026-09-11): thêm `list_processes` + `power`
    (`docs/system_admin_spec.md` §4). Lần chụp lại TỐN KÉM NHẤT từ trước tới nay, ghi rõ
    để lần sau cân nhắc trước chứ không phát hiện sau:

    Hai tool này thuộc feature `system`, mà `system` đứng ĐẦU `catalog.py::FEATURES`. Nên
    chúng chèn vào vị trí 8-9 và đẩy CẢ 40 TOOL PHÍA SAU xuống hai chỗ — tiền tố chung với
    ảnh chụp cũ rơi từ 47 tool xuống còn 7. Nội dung từng tool cũ không đổi một ký tự (đã
    kiểm: diff của chính file fixture này là +49/−1, thuần chèn thêm), chỉ vị trí đổi.

    Vì sao vẫn chấp nhận: chi phí là MỘT LẦN, không phải mỗi lượt. Thứ ~16-20s/lượt mà file
    này canh là thứ tự đổi GIỮA HAI LẦN CHẠY (vd `os.listdir` không hứa thứ tự) — cache
    nguội vĩnh viễn. Đây thì mọi lượt sau khi cập nhật đều dùng chung một tiền tố mới, nên
    chỉ lượt đầu tiên phải đọc lại. `test_specs_giong_het_tung_byte_giua_hai_lan_dung` vẫn
    xanh, tức tính tất định — thứ thật sự quan trọng — còn nguyên.

    Cách tránh nếu lần sau muốn rẻ hơn: đặt tool mới ở feature nằm CUỐI `FEATURES`, khi đó
    tiền tố của toàn bộ tool cũ giữ nguyên từng byte. Không làm lần này vì spec nói rõ đây
    là "mở rộng feature `system`", và bẻ tính năng ra một package riêng chỉ để chiều cache
    là để chi tiết hiệu năng nắn kiến trúc.

    CHỤP LẠI LẦN HAI (2026-08-29, đợt 3 của vá bảo mật): `browser_close_tab` bỏ tham số
    `confirm` khỏi lược đồ và rút gọn mô tả. Tool này từng tự làm hai pha bằng `confirm`,
    với luật "đừng tự đặt confirm=true" viết trong MÔ TẢ TOOL — tức nằm đúng trong thứ mà
    prompt injection ghi đè được, và mô phỏng tấn công đã chứng minh nó lọt. Nay việc chặn
    thuộc về `registry.gate()` ở tầng code, nên tham số đó phải BIẾN MẤT khỏi tầm nhìn của
    model. Đã kiểm trước khi chụp lại: vẫn đúng 47 tool, và `browser_close_tab` là tool DUY
    NHẤT khác đi. Tổng payload giảm 19.351 -> 19.028 ký tự.

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


# --------------------------- IndexedTools: nền phải cố định --------------------------- #
#
# `IndexedTools` mở thêm nhóm GIỮA LƯỢT, tức là đụng thẳng vào thứ file này canh. Hai tính
# chất phải giữ, nếu không thì cái tiết kiệm được về ký tự bị trả lại bằng thời gian nạp
# lại cache: nền giống hệt từng byte giữa các lượt, và mở nhóm chỉ NỐI VÀO CUỐI.

def _json_list(specs):
    """`_specs_json` ở trên nhận REGISTRY; bề mặt tool trả về một LIST spec."""
    return json.dumps(specs, ensure_ascii=False)


def _indexed():
    import dataclasses
    from unittest.mock import MagicMock

    from agent.surface import IndexedTools
    from features.contract import FeatureContext
    from features.registry import build_registry

    ctx = {f.name: MagicMock() for f in dataclasses.fields(FeatureContext)}
    ctx["mcp"] = None
    reg, report = build_registry(FeatureContext(**ctx))
    return reg, IndexedTools("SYS", report)


def test_nen_indexed_giong_het_tung_byte_giua_hai_luot():
    reg, ix = _indexed()
    s1, t1 = ix.select("mở chrome", reg)
    s2, t2 = ix.select("thời tiết Hà Nội thế nào", reg)
    assert s1 == s2                                   # prompt + mục lục
    assert _json_list(t1) == _json_list(t2)           # khối tool


def test_mo_nhom_chi_NOI_VAO_CUOI_khong_sua_phan_da_co():
    reg, ix = _indexed()
    _, nen = ix.select("tìm quán cà phê", reg)
    truoc = _json_list(nen)
    moi = ix.expand("mo_nhom", {"nhom": "place"}, reg)
    assert moi
    # Phần đầu của mảng sau khi nối phải khớp TỪNG BYTE với nền.
    assert _json_list((nen + moi)[:len(nen)]) == truoc


def test_thu_tu_muc_luc_khong_doi_giua_hai_lan_dung():
    """Mục lục dựng từ `features/catalog.py` (thứ tự xác định), không từ dict/set."""
    reg1, ix1 = _indexed()
    reg2, ix2 = _indexed()
    assert ix1.select("x", reg1)[0] == ix2.select("x", reg2)[0]


def test_mo_nhom_khong_tra_tool_da_co_trong_bo_loi():
    """Nối trùng một tool đã nằm trong nền là vừa tốn ký tự vừa đưa LLM hai spec cùng tên."""
    reg, ix = _indexed()
    _, nen = ix.select("x", reg)
    co_san = {s["name"] for s in nen}
    for nhom in ("web", "place", "system"):
        ix.select("x", reg)                            # reset trạng thái lượt
        moi = ix.expand("mo_nhom", {"nhom": nhom}, reg) or []
        assert not ({s["name"] for s in moi} & co_san), nhom
