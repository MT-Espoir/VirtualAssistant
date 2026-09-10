"""
Ngân sách payload tool specs — chặn hệ thống đắt lên âm thầm khi thêm tính năng.

Con số này là chi phí LLM trả lại MỖI LƯỢT, mãi mãi: 47 tool = 19.351 ký tự ≈ 6.450
token đọc lại từ đầu mỗi lần gọi. Không có triệu chứng nào ngoài "sao dạo này chậm thế".

Thứ phải canh là PAYLOAD MỖI LƯỢT, không phải kích thước catalog — hôm nay hai số đó
bằng nhau vì bề mặt mặc định (`agent/surface.py::AllTools`) gửi hết, nhưng chúng sẽ tách
ra khi có `IndexedTools`/`CodeTools`. Các test dưới đây đo qua BỀ MẶT chứ không qua
registry, nên khi bề mặt đổi thì con số tự đi theo. Xem `docs/tool_surface_spec.md`.

Hai lớp bắt hai loại lỗi khác nhau — xem `features/contract.py::SPEC_CHARS_BUDGET`.
"""

import dataclasses
import json
from unittest.mock import MagicMock

from agent.router import Router, case_tools_from
from agent.surface import AllTools
from agent.tools import ToolRegistry
from features.catalog import FEATURES
from features.contract import SPEC_CHARS_BUDGET, FeatureContext, load_features

# Trần cho MỘT case đã thu hẹp. Đặt sát mức thật (`place` 3.353) như mọi trần khác trong
# file này: rộng tay thì nó không bắt được gì nữa.
CASE_CHARS_BUDGET = 4_000


def _ctx():
    ctx = {f.name: MagicMock() for f in dataclasses.fields(FeatureContext)}
    ctx["mcp"] = None       # tool MCP sinh động từ server -> mock vào là lệch phép đếm
    return FeatureContext(**ctx)


def _report():
    return load_features(ToolRegistry(), _ctx(), FEATURES)


def _registry_va_report():
    reg = ToolRegistry()
    return reg, load_features(reg, _ctx(), FEATURES)


def _chars(specs):
    return len(json.dumps(specs, ensure_ascii=False))


def _bang(report):
    """Bảng breakdown để in ra khi test đỏ — biết ngay feature nào vừa phình."""
    tran = {f.name: f.max_spec_chars for f in FEATURES}
    dong = ["", "  feature    tool   chars    trần", "  " + "-" * 34]
    for f in sorted(report.loaded, key=lambda x: -x.spec_chars):
        dong.append("  %-10s %3d %7d %7d" % (f.name, len(f.tools), f.spec_chars,
                                             tran[f.name]))
    dong.append("  " + "-" * 34)
    dong.append("  %-10s %3d %7d" % ("TỔNG", sum(len(f.tools) for f in report.loaded),
                                     report.spec_chars))
    return "\n".join(dong)


# --- lớp 1: trần tổng (con số quyết định độ trễ) ------------------------------------

def test_tong_nam_trong_ngan_sach():
    """Bắt "mọi thứ nhích dần": từng feature vẫn trong hạn mà cả hệ thống đã đắt lên."""
    report = _report()
    assert report.spec_chars <= SPEC_CHARS_BUDGET, (
        f"Tool specs phình lên {report.spec_chars}, quá trần {SPEC_CHARS_BUDGET}.\n"
        f"Nén mô tả tool, gom tool cùng nhóm ({{action}} enum), hoặc nâng trần CÓ ĐO LẠI."
        + _bang(report))


# --- lớp 2: trần từng feature (bắt phình cục bộ dù tổng còn chỗ) --------------------

def test_khong_feature_nao_vuot_tran_da_khai():
    report = _report()
    tran = {f.name: f.max_spec_chars for f in FEATURES}
    vuot = {f.name: (f.spec_chars, tran[f.name]) for f in report.loaded
            if f.spec_chars > tran[f.name]}
    assert not vuot, f"feature vượt trần đã khai: {vuot}" + _bang(report)


def test_moi_feature_deu_khai_tran():
    """Trần mặc định 2.000 là con số bịa cho tiện; feature thật phải khai theo mức đo được."""
    mac_dinh = [f.name for f in FEATURES if f.max_spec_chars == 2_000]
    assert not mac_dinh, (f"còn dùng trần mặc định, chưa đo: {mac_dinh}")


def test_khong_tool_nao_phinh_qua_muc():
    """Một tool > 1.200 ký tự gần như luôn là mô tả viết dài, không phải schema phức tạp.

    Ngưỡng đặt ngay trên mức nặng nhất hiện tại (`remember_about_user` 1.092).
    """
    ctx = {f.name: MagicMock() for f in dataclasses.fields(FeatureContext)}
    ctx["mcp"] = None
    reg = ToolRegistry()
    load_features(reg, FeatureContext(**ctx), FEATURES)
    beo = {n: len(json.dumps(reg.get(n).spec(), ensure_ascii=False)) for n in reg.names()}
    assert not {n: c for n, c in beo.items() if c > 1_200}, \
        f"tool có spec quá dài: { {n: c for n, c in beo.items() if c > 1_200} }"


# --- lớp 3: payload MỖI LƯỢT, đo qua bề mặt tool ------------------------------------

def test_payload_moi_luot_cua_be_mat_mac_dinh():
    """Đo qua `AllTools` chứ không qua registry: đây mới là thứ model thật sự nhận.

    Hôm nay bằng đúng tổng catalog (bề mặt mặc định gửi hết). Ngày có `IndexedTools`,
    test này tự đo con số mới còn `test_tong_nam_trong_ngan_sach` thì không — đó là lý do
    hai test cùng tồn tại chứ không phải một cái thừa.
    """
    reg, _ = _registry_va_report()
    _, specs = AllTools("").select("câu bất kỳ", reg)
    assert _chars(specs) <= SPEC_CHARS_BUDGET


def test_moi_case_da_thu_hep_nam_trong_tran_case():
    """Bắt MỘT case phình lên dù tổng còn chỗ — nhóm to là nhóm model chọn sai nhiều."""
    reg, report = _registry_va_report()
    bang = case_tools_from(report)
    router = Router(None, bang, {"base": "", "cases": {}, "router": ""})
    vuot = {}
    for case in bang:
        if case == "general":
            continue                    # 'general' cố ý không thu hẹp — xem test dưới
        _, specs = router.select_for_case(case, reg)
        if _chars(specs) > CASE_CHARS_BUDGET:
            vuot[case] = _chars(specs)
    assert not vuot, f"case vượt trần {CASE_CHARS_BUDGET}: {vuot}"


def test_thu_hep_theo_case_KHONG_chan_duoc_truong_hop_xau_nhat():
    """Sự thật dễ quên: bật router KHÔNG hạ được trần payload.

    Case đã thu hẹp chỉ tốn 495–3.353 ký tự, nhưng `general` (không rõ ý người dùng, hoặc
    router lỗi) không thu hẹp gì cả — vẫn gửi trọn catalog. Nên trần xấu nhất của đường
    có router BẰNG trần của đường không router, và `SPEC_CHARS_BUDGET` chưa được nới ra
    chỉ vì "đã có router".

    Test này ghim sự thật đó lại: khi làm `IndexedTools`, đây chính là ca phải chặn —
    bộ lõi + mục lục phải phủ được cả `general`, nếu không thì công cốc.
    """
    reg, report = _registry_va_report()
    router = Router(None, case_tools_from(report), {"base": "", "cases": {}, "router": ""})
    _, chi_general = router.select_for_case("general", reg)
    assert _chars(chi_general) == _chars(reg.specs())


# --- cảnh báo sớm: còn bao nhiêu chỗ trống -----------------------------------------

def test_con_du_dia_cho_it_nhat_mot_feature_nho():
    """CẢNH BÁO SỚM, không phải cổng chặn.

    Đang dùng 96% ngân sách (19.257/20.000). Thêm một feature cỡ `weather` (493 ký tự)
    là vượt. Test này đỏ TRƯỚC khi điều đó xảy ra, để việc nén payload (gom tool theo
    `action` enum — việc 12 của sprint) được lên lịch chứ không bị dồn tới lúc kẹt.

    Đỏ ở đây KHÔNG chặn tính năng nào: hoặc nén bớt, hoặc chỉnh ngưỡng này xuống một
    cách có ý thức và ghi lại lý do.
    """
    report = _report()
    con_lai = SPEC_CHARS_BUDGET - report.spec_chars
    assert con_lai >= 500, (
        f"Chỉ còn {con_lai} ký tự trống trong ngân sách — không đủ cho một feature nhỏ. "
        f"Đã tới lúc nén payload (gom tool cùng nhóm), xem docs/module_refactor_sprint.md."
        + _bang(report))
