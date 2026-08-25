"""
Ngân sách payload tool specs — chặn hệ thống đắt lên âm thầm khi thêm tính năng.

Con số này là chi phí LLM trả lại MỖI LƯỢT, mãi mãi: 47 tool = 19.351 ký tự ≈ 6.450
token đọc lại từ đầu mỗi lần gọi. Không có triệu chứng nào ngoài "sao dạo này chậm thế".

Hai lớp bắt hai loại lỗi khác nhau — xem `features/contract.py::SPEC_CHARS_BUDGET`.
"""

import dataclasses
import json
from unittest.mock import MagicMock

from agent.tools import ToolRegistry
from features.catalog import FEATURES
from features.contract import SPEC_CHARS_BUDGET, FeatureContext, load_features


def _report():
    ctx = {f.name: MagicMock() for f in dataclasses.fields(FeatureContext)}
    ctx["mcp"] = None       # tool MCP sinh động từ server -> mock vào là lệch phép đếm
    return load_features(ToolRegistry(), FeatureContext(**ctx), FEATURES)


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
