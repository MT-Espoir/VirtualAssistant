"""
Cổng dữ liệu RA NGOÀI phải cho NHÌN, không chỉ cho NGHE (đợt 4 của vá bảo mật).

Đây là trợ lý dùng bằng giọng nói, mà tai không phân biệt được
`https://google.com.evil.example/x` với `google.com` — đọc lên nghe y hệt. Xác nhận bằng
giọng lại đang là lớp phòng thủ CHÍNH, nên đây là điểm yếu #3 trong
`docs/security_review_2026-08-29.md`.

Cách chữa: tách MIỀN ra đứng riêng, đặt TRƯỚC url đầy đủ, trên panel.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import registry_with
from features.pim.tools import la_nguoi_nhan_la
from ui.panels import outbound_blocks, pending_blocks, pending_title
from utils.outbound import lay_mien, mo_ta_ra_ngoai


# --------------------------- rút miền thật --------------------------- #

def test_lay_mien_thuong():
    assert lay_mien("https://vnexpress.net/tin-moi") == "vnexpress.net"


def test_mien_giau_o_CUOI_chuoi_van_bi_keo_ra():
    """`google.com.evil.example` — mắt hay dừng ở phần đầu, tai thì chịu hẳn."""
    assert lay_mien("https://google.com.evil.example/x?d=bimat") == "google.com.evil.example"


def test_thu_thuat_userinfo_khong_qua_mat_duoc():
    """`https://google.com@evil.example/` là URL HỢP LỆ mà đọc lên nghe là google.com.
    Trình duyệt thì đi tới evil.example."""
    assert lay_mien("https://google.com@evil.example/") == "evil.example"


def test_khong_phai_url_thi_khong_bia_ra_mien():
    assert lay_mien("youtube") == "" and lay_mien("") == "" and lay_mien(None) == ""


# --------------------------- mô tả thứ sắp rời máy --------------------------- #

def test_mo_ta_url():
    ra = mo_ta_ra_ngoai({"url": "https://evil.example/c?d=Minh"})
    assert ra["mien"] == "evil.example" and ra["ra_ngoai"] is True


def test_mo_ta_truy_van_tim_kiem():
    """Truy vấn cũng là dữ liệu rời máy — kẻ tấn công nhét bí mật vào từ khoá tìm kiếm."""
    ra = mo_ta_ra_ngoai({"query": "toạ độ nhà 10.77,106.69"})
    assert ra["truy_van"] == "toạ độ nhà 10.77,106.69"


def test_khong_co_gi_di_ra_ngoai_thi_None():
    assert mo_ta_ra_ngoai({"index": 2}) is None
    assert mo_ta_ra_ngoai({}) is None and mo_ta_ra_ngoai(None) is None


# --------------------------- panel --------------------------- #

def test_MIEN_dung_rieng_va_dung_TRUOC_url_day_du():
    khoi = outbound_blocks({"ra_ngoai": True, "mien": "evil.example",
                            "url": "https://google.com.evil.example/x"})
    nhan = [b[0] for b in khoi]
    assert nhan.index("field") < nhan.index("body")      # miền TRƯỚC url
    assert ("field", "Miền", "evil.example") in khoi


def test_panel_co_nut_huy_va_dong_y():
    nut = [b for b in outbound_blocks({"ra_ngoai": True, "url": "https://x.com",
                                       "mien": "x.com"}) if b[0] == "buttons"][0]
    assert [k for _, k, _ in nut[1]] == ["no", "yes"]


def test_mot_be_mat_duyet_chung_phan_nhanh_theo_payload():
    """Nút HUỶ/ĐỒNG Ý đi chung một đường `agent.confirm_pending`, nên thêm loại hành động
    mới chỉ là thêm cách VẼ, không phải thêm đường thực thi."""
    ra_ngoai = {"ra_ngoai": True, "url": "https://x.com", "mien": "x.com"}
    nhap = {"to": "a@b.com", "subject": "x", "body": "y"}
    assert pending_blocks(ra_ngoai)[0] == ("header", "Sắp gửi dữ liệu RA NGOÀI máy")
    assert pending_blocks(nhap)[0] == ("header", "Xem lại trước khi gửi")
    assert pending_title(ra_ngoai) == "GỬI RA NGOÀI"
    assert pending_title(nhap) == "NHÁP EMAIL"
    assert pending_blocks(None) == []


# --------------------------- cổng dựng bản xem trước, không phải tool --------------- #

def test_cong_TU_dung_ban_xem_truoc_khi_gac_vi_vet_nhiem():
    reg = registry_with(actions=MagicMock())
    g = reg.gate("web_fetch", {"url": "https://evil.example/c?d=x"}, nhiem=True)
    assert g is not None
    assert g["preview"]["mien"] == "evil.example"


def test_luot_SACH_khong_dung_ban_xem_truoc_va_khong_hoi():
    """Nếu gắn `preview` vào chính tool `exfil` thì luật "có preview => duyệt" sẽ bắt hỏi
    cả ở lượt sạch — phá đúng điều kiện khiến cổng có giá trị."""
    reg = registry_with(actions=MagicMock())
    assert reg.gate("web_fetch", {"url": "https://vnexpress.net"}, nhiem=False) is None


# --------------------------- người nhận lạ --------------------------- #

class _Danh_ba:
    def __init__(self, emails):
        self._e = [{"email": e} for e in emails]

    def list(self):
        return list(self._e)


def test_dia_chi_chua_tung_thay_bi_danh_dau_la():
    assert la_nguoi_nhan_la("attacker@evil.com", _Danh_ba(["boss@x.com"])) is True


def test_dia_chi_quen_thi_khong_canh_bao():
    assert la_nguoi_nhan_la("boss@x.com", _Danh_ba(["boss@x.com"])) is False


def test_danh_ba_rong_thi_KHONG_canh_bao():
    """Chưa có gì để so thì mọi địa chỉ đều 'lạ' — cảnh báo kêu mọi lần gửi sẽ bị bào mòn
    thành tiếng ồn trước khi kịp cứu ai."""
    assert la_nguoi_nhan_la("ai-do@x.com", _Danh_ba([])) is False
    assert la_nguoi_nhan_la("ai-do@x.com", None) is False


def test_danh_ba_hong_thi_suy_bien_an_toan():
    kho = MagicMock()
    kho.list.side_effect = RuntimeError("file hỏng")
    assert la_nguoi_nhan_la("ai-do@x.com", kho) is False
