"""
Quản trị TỰ ĐỘNG: đường trợ lý tự khởi xướng, KHÔNG có lượt nào để hỏi người dùng.

Hai thứ được canh ở đây, và chúng là hai loại test khác nhau:
  - quyết định hạ sáng (`muc_sang_khi_pin_yeu`) — logic thuần, chỉ cần đúng;
  - danh sách trắng (`Tool.tu_dong`) — RANH GIỚI AN TOÀN. Test ở dưới cố ý dựng cả các ca
    tấn công/nhầm lẫn, vì một lỗi ở đây có nghĩa là máy tự làm việc không ai bảo.

Xem `docs/system_admin_spec.md` §5.2, §5.3.
"""

from conftest import full_registry, registry_with

import pytest

from agent.tools import ActionRefused, Tool, ToolRegistry
from services.proactive import MUC_SANG_PIN_YEU, muc_sang_khi_pin_yeu


# --------------------------- quyết định hạ sáng (thuần) --------------------------- #

def test_ha_sang_khi_dang_sang_hon_muc_tieu():
    assert muc_sang_khi_pin_yeu(100) == MUC_SANG_PIN_YEU
    assert muc_sang_khi_pin_yeu(41) == MUC_SANG_PIN_YEU


def test_khong_dung_vao_khi_da_du_toi():
    """Chỉ HẠ, không bao giờ NÂNG — người để màn hình tối hơn là họ cố ý."""
    assert muc_sang_khi_pin_yeu(MUC_SANG_PIN_YEU) is None
    assert muc_sang_khi_pin_yeu(10) is None
    assert muc_sang_khi_pin_yeu(0) is None


def test_khong_doc_duoc_do_sang_thi_khong_mo():
    assert muc_sang_khi_pin_yeu(None) is None


def test_muc_tieu_doi_duoc_cho_test():
    assert muc_sang_khi_pin_yeu(80, muc_tieu=50) == 50
    assert muc_sang_khi_pin_yeu(30, muc_tieu=50) is None


# ------------------------------- danh sách trắng ---------------------------------- #

def _reg(**co):
    """Registry một tool 'viec' với các cờ rủi ro truyền vào."""
    reg = ToolRegistry()
    reg.register(Tool(name="viec", description="d", input_schema={"type": "object"},
                      handler=lambda **_: "xong", **co))
    return reg


def test_duong_tu_dong_tu_choi_tool_khong_co_co():
    reg = _reg()
    assert reg.run("viec", {}) == "xong"                 # người dùng gọi thì chạy bình thường
    with pytest.raises(ActionRefused):
        reg.run("viec", {}, tu_dong=True)


def test_duong_tu_dong_chay_tool_co_co():
    assert _reg(tu_dong=True).run("viec", {}, tu_dong=True) == "xong"


def test_confirmed_khong_mo_duoc_duong_tu_dong():
    """`confirmed=True` là "người dùng đã đồng ý" — trên đường tự động thì không có ai
    đồng ý cả, nên cờ đó không được dùng làm chìa khoá."""
    with pytest.raises(ActionRefused):
        _reg().run("viec", {}, confirmed=True, tu_dong=True)


def test_tu_dong_khong_ham_y_confirmed():
    """Tool tự động mà lỡ thành `destructive` thì phải DỪNG, không được âm thầm chạy:
    đường này không có ai để hỏi, nên im lặng chạy tiếp là kết cục tệ nhất."""
    from agent.tools import NeedsConfirmation
    reg = _reg(tu_dong=True, destructive=True)
    with pytest.raises(NeedsConfirmation):
        reg.run("viec", {}, tu_dong=True)


def test_tu_dong_khong_noi_long_luat_nhiem():
    """Hai luật từ chối cộng dồn, không triệt tiêu nhau."""
    reg = _reg(tu_dong=True, admin=True)
    with pytest.raises(ActionRefused):
        reg.run("viec", {}, nhiem=True, tu_dong=True)


def test_ly_do_tu_choi_noi_duoc_ra_mieng():
    reg = _reg()
    assert reg.tu_choi("viec", {}, tu_dong=True)
    assert reg.tu_choi("viec", {}) is None                # đường người dùng vẫn sạch


# --------------------------- ranh giới an toàn: bản kiểm kê ----------------------- #

# Danh sách này CỐ Ý viết tay. Nó là bề mặt tự động của cả hệ thống, và một dòng thêm vào
# đây phải là một quyết định có người đọc — không phải hệ quả phụ của việc thêm một tool.
# Điều kiện để một tool được vào: HOÀN TÁC ĐƯỢC BẰNG MỘT CÂU NÓI (`docs/system_admin_spec.md`
# §5.3). Nếu test này đỏ, đừng sửa danh sách cho hết đỏ — hãy hỏi tool mới có đạt điều kiện
# đó không.
TOOL_TU_DONG_MONG_DOI = {"set_brightness"}


def test_be_mat_tu_dong_dung_y_nguyen():
    reg = full_registry()
    thuc_te = {t for t in reg.names() if reg.get(t).tu_dong}
    assert thuc_te == TOOL_TU_DONG_MONG_DOI


def test_moi_tool_khac_deu_bi_chan_tren_duong_tu_dong():
    """Không liệt kê tay tool nào bị cấm: hỏi thẳng registry đầy đủ. Tool quản trị thêm về
    sau (`kill_process`, `power`) tự động bị phủ, không phải nhớ cập nhật test này."""
    reg = full_registry()
    for ten in reg.names():
        if ten in TOOL_TU_DONG_MONG_DOI:
            continue
        assert reg.tu_choi(ten, {}, tu_dong=True), f"{ten} lọt qua đường tự động"


def test_set_brightness_chay_that_duoc_tren_duong_tu_dong():
    """Ca đầu-cuối của tính năng: pin yếu -> registry thật gọi tới handler thật."""
    goi = []

    class ActionsStub:
        def control_brightness(self, level=None, change=None):
            goi.append((level, change))
            return f"Đã đặt độ sáng {level}%."

    reg = registry_with(actions=ActionsStub())
    out = reg.run("set_brightness", {"level": MUC_SANG_PIN_YEU}, tu_dong=True)
    assert goi == [(MUC_SANG_PIN_YEU, None)]
    assert str(MUC_SANG_PIN_YEU) in out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
