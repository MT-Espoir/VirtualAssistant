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

# Trần payload MỘT LƯỢT của `IndexedTools` — prompt + specs, tức đúng thứ model nhận.
# Đây là con số THẬT SỰ quyết định độ trễ từ 2026-09-12, thay chỗ `SPEC_CHARS_BUDGET` cũ.
# Đo được 18.996; đặt trần sát mức thật như mọi trần khác trong file này.
#
# Từng là 13.000 khi nền mới có 12.029. Nới lên sau khi eval thật cho thấy nền đó mua độ
# rẻ bằng ĐỘ CHÍNH XÁC — thiếu chỉ dẫn của nhóm có tool trong lõi thì tool-acc tụt 4 điểm
# (`docs/indexed_tools_spec.md` §7e). Đây là lần nới có SỐ ĐO đứng sau, không phải nới cho
# hết đỏ; và nó vẫn còn cách `AllTools` (31.356) rất xa.
PAYLOAD_LUOT_BUDGET = 19_500


def test_payload_moi_luot_cua_be_mat_mac_dinh():
    """Đo qua BỀ MẶT chứ không qua registry: đây mới là thứ model thật sự nhận mỗi lượt.

    Ngày viết file này (2026-08-25) con số đây bằng đúng tổng catalog, vì bề mặt mặc định
    gửi hết. Từ 2026-09-12 hai số đã TÁCH RA — đúng như docstring đầu file dự đoán — và
    đây là lý do hai test cùng tồn tại chứ không phải một cái thừa.

    Cố ý đo CẢ HAI bề mặt thay vì hỏi `config.surface_mode()`: một test đổi ý nghĩa theo
    biến môi trường của máy đang chạy thì không canh được gì.
    """
    from agent.surface import IndexedTools
    from llm import prompts
    reg, report = _registry_va_report()

    # Đường dự phòng (`AllTools`, và case `general` của Router) — vẫn phải có trần.
    _, specs = AllTools("").select("câu bất kỳ", reg)
    assert _chars(specs) <= SPEC_CHARS_BUDGET

    # Đường MẶC ĐỊNH với provider mạnh. `base()` chứ không `merged()`, giống app.py.
    ix = IndexedTools(prompts.base(), report)
    system, specs = ix.select("câu bất kỳ", reg)
    tong = len(system) + _chars(specs)
    assert tong <= PAYLOAD_LUOT_BUDGET, (
        f"Payload mỗi lượt của IndexedTools phình lên {tong} (trần {PAYLOAD_LUOT_BUDGET}). "
        f"Thủ phạm thường là BỘ LÕI to ra — xem tests/test_bo_loi.py.")


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

# Ngưỡng cảnh báo sớm cho ĐƯỜNG DỰ PHÒNG. 500 -> 250 (2026-09-11) -> 900 (2026-09-12).
#
# Lần này NÂNG chứ không hạ, và lý do khác hẳn hai lần trước: trần tổng vừa được nới lên
# 21.500 vì nó không còn canh payload mỗi lượt nữa (xem `features/contract.py`). Ngưỡng
# cảnh báo đi theo để giữ nguyên VAI TRÒ của nó — báo trước khi đường dự phòng hết chỗ —
# thay vì giữ nguyên CON SỐ, vốn chỉ có nghĩa với cái trần cũ.
#
# Ghi lại lập luận cũ vì nó vẫn đúng cho đường dự phòng:
#
# Ngưỡng cũ 500 ("còn đủ chỗ cho một feature nhỏ cỡ `weather`") đã hoàn thành đúng việc
# của nó: nó đỏ lên khi `list_processes` + `power` (698 ký tự) được thêm vào, đúng lúc
# đáng đỏ. Không hạ ngưỡng để làm nó im — hạ vì thứ nó cảnh báo ĐÃ XẢY RA và đã được
# quyết: ngân sách coi như cạn, tool tiếp theo phải đợi `IndexedTools` bật mặc định
# (`docs/system_admin_spec.md` §2, §10 mục 1).
#
# 250 không phải con số đẹp mà là con số THẬT: một tool trung bình tốn ~400 ký tự, nên
# dưới 400 thì tool kế tiếp sẽ vỡ trần CỨNG ở `test_ngan_sach` bên trên chứ không dừng ở
# cảnh báo. Giữ 250 để còn một vạch báo trước khi đâm vào tường, thay vì bỏ hẳn test.
NGUONG_CANH_BAO = 900


def test_con_du_dia_cho_it_nhat_mot_feature_nho():
    """CẢNH BÁO SỚM, không phải cổng chặn.

    Đỏ ở đây KHÔNG chặn tính năng nào: hoặc nén bớt, hoặc chỉnh `NGUONG_CANH_BAO` xuống
    một cách có ý thức và ghi lại lý do — xem khối chú thích ngay trên.
    """
    report = _report()
    con_lai = SPEC_CHARS_BUDGET - report.spec_chars
    assert con_lai >= NGUONG_CANH_BAO, (
        f"Chỉ còn {con_lai} ký tự trống trong ngân sách. Ngân sách đã cạn từ 2026-09-11: "
        f"tool mới phải đợi `IndexedTools` bật mặc định, đừng nới ngưỡng này thêm nữa."
        + _bang(report))
