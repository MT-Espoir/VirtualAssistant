"""
Tính chất của BỘ LÕI `surface.CORE` — tiêu chí 1 của `docs/indexed_tools_spec.md` §7.

Khác `test_tool_surface.py`: ở đó là test CƠ CHẾ (mở nhóm có nối đúng không), ở đây là test
SỐ ĐO (bộ lõi chọn thế có đủ tốt không). Tách ra vì chúng hỏng vì hai lý do khác nhau và
người sửa cũng khác nhau.

Đo trên `evals/cases.py::CASES` (51 ca có gọi tool) chứ không trên bộ phủ catalog:
thêm một ca nhân tạo cho mỗi tool hiếm sẽ bóp méo phép đo tần suất/tỉ lệ mở nhóm. Log thật
vẫn lệch theo thói quen người dùng, nên bộ đại diện giữ vai trò mốc so sánh ổn định;
`COVERAGE_CASES` chỉ canh việc không tool nào bị bỏ quên hoàn toàn.

Trước đây phép đo cũng không dùng `logs/outcomes.jsonl`: log lệch
theo việc đang phát triển lúc ghi — nhóm `system` xuất hiện 0 lần dù là nhóm lâu đời nhất —
còn bộ ca eval được viết để phủ đều mọi feature, đúng thứ một bộ lõi cần.

HẠN CHẾ, ghi để đừng đọc nhầm mấy con số này: bộ ca eval cũng do người viết ra, không phải
phân bố dùng thật. Nó sửa được cái lệch của log nhưng không thay thế được việc đo ≥200 lượt
thật (§5). Test này canh THOÁI HOÁ, không chứng minh bộ lõi tối ưu.
"""

from conftest import full_registry, full_report

import json

from agent.surface import CORE

from evals.cases import CASES


# Trần tỉ lệ mở nhóm, tiêu chí 1 của §7. Mỗi lượt phải mở nhóm tốn THÊM MỘT VÒNG LLM, nên
# đây là ngưỡng về ĐỘ TRỄ chứ không phải về ký tự — nới nó ra là nới thứ người dùng cảm
# thấy được. Số vòng ước tính ≈ 1,84 + r.
TRAN_MO_NHOM = 0.25

# Trần ký tự của bộ lõi. Nền được trả ở MỌI vòng của MỌI lượt, nên nó là con số quan trọng
# hơn cả tổng catalog. Đặt sát mức thật (8.699) để một tool phình ra là thấy ngay.
TRAN_KY_TU_LOI = 8_800


def _ca_co_tool():
    return [c for c in CASES if c["expect"]]


def test_ti_le_mo_nhom_dat_tieu_chi():
    ca = _ca_co_tool()
    phai_mo = [c for c in ca if not set(c["expect"]) <= set(CORE)]
    r = len(phai_mo) / len(ca)
    assert r <= TRAN_MO_NHOM, (
        f"Tỉ lệ mở nhóm {r:.0%} > trần {TRAN_MO_NHOM:.0%} — mỗi lượt như vậy tốn thêm một "
        f"vòng LLM. Ca phải mở nhóm: {sorted({t for c in phai_mo for t in c['expect']})}")


def test_bo_loi_khong_phinh_qua_tran():
    reg = full_registry()
    ky_tu = sum(len(json.dumps(reg.get(n).spec(), ensure_ascii=False))
                for n in CORE if reg.has(n))
    assert ky_tu <= TRAN_KY_TU_LOI, (
        f"Bộ lõi phình lên {ky_tu} ký tự (trần {TRAN_KY_TU_LOI}). Nền được trả ở MỌI vòng, "
        f"nên thêm tool vào lõi đắt hơn nhiều so với để nó trong nhóm.")


def test_moi_tool_trong_bo_loi_deu_ton_tai():
    """Đổi tên một tool mà quên sửa `CORE` -> nó lặng lẽ biến mất khỏi lõi, tỉ lệ mở nhóm
    tăng, và không có triệu chứng nào ngoài "sao dạo này chậm thế"."""
    reg = full_registry()
    thieu = [n for n in CORE if not reg.has(n)]
    assert not thieu, f"tool trong CORE không còn trong registry: {thieu}"


def test_bo_loi_khong_trung_lap():
    assert len(CORE) == len(set(CORE))


def test_bo_loi_phu_moi_nhom_hay_dung():
    """Một nhóm KHÔNG có đại diện nào trong lõi thì mọi câu thuộc nhóm đó đều tốn thêm một
    vòng. Chấp nhận được với nhóm hiếm, nhưng phải là lựa chọn có ý thức — nên ghim danh
    sách nhóm vắng mặt lại ở đây."""
    rep = full_report()
    nhom_cua = {t: f.name for f in rep.loaded for t in f.tools}
    co_mat = {nhom_cua[t] for t in CORE if t in nhom_cua}
    vang = {f.name for f in rep.loaded if f.tools} - co_mat
    # `profile`, `pim` và `activity` đều là việc người dùng nói hẳn ra ("nhớ giúp tôi",
    # "tìm số", "xem thống kê 7 ngày"), tức câu dài và rõ nhóm. Activity Insights còn
    # là panel truy vấn không thường xuyên; mở nhóm thêm một vòng rẻ hơn cõng spec mỗi lượt.
    # IoT and camera controls have direct voice paths; their specs need not grow CORE.
    assert vang == {"profile", "pim", "activity", "iot", "camera"}, \
        f"nhóm vắng mặt trong lõi: {sorted(vang)}"


def test_so_lieu_nen_khop_voi_spec():
    """Ghim con số spec §7 dựa vào. Lệch thì spec đã nói về một hệ thống khác."""
    reg = full_registry()
    ca = _ca_co_tool()
    r = sum(1 for c in ca if not set(c["expect"]) <= set(CORE)) / len(ca)
    day_du = sum(len(json.dumps(s, ensure_ascii=False)) for s in reg.specs())
    loi = sum(len(json.dumps(reg.get(n).spec(), ensure_ascii=False))
              for n in CORE if reg.has(n))
    assert 0.18 <= r <= 0.25                 # §7 tiêu chí 1
    assert loi / day_du < 0.50               # lõi phải nhỏ hơn đáng kể so với cả catalog


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
