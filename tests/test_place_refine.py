"""Tinh chỉnh theo ngữ cảnh lượt trước.

Lỗi THẬT: "có chỗ nào mở muộn hơn không" bị model biến
thành từ khoá tìm kiếm `find_nearby(query="quán cà phê mở muộn")`. Maps tra chữ đó như
văn bản, nên kết quả KHÔNG hề được lọc theo giờ — trong khi hệ thống đã có `closes_at`
của từng quán và lọc được trong ~1 giây.
"""

import datetime as dt

import pytest

from features.places.refine import CHANGES, EXPANDING, apply_refinement, needs_requery

NOW = dt.datetime(2026, 8, 21, 21, 40)


def _p(name, **kw):
    base = {"name": name, "distance_km": 1.0, "rating": None, "price": None,
            "quote": None, "opening": {"state": "unknown"}}
    base.update(kw)
    return base


ROWS = [
    _p("Sắp đóng", opening={"state": "closing_soon", "closes_at": (22, 0)},
       distance_km=0.1, rating=4.8, price={"max": 100000}),
    _p("Mở tới 23:30", opening={"state": "open", "closes_at": (23, 30)},
       distance_km=0.6, rating=4.6, price={"max": 50000}),
    _p("Mở cả ngày", opening={"state": "open_24h"}, distance_km=1.2, rating=4.7),
    _p("Không rõ giờ", distance_km=0.3, rating=4.9),
]


# --------------------------- thu hẹp vs mở rộng ---------------------------

def test_thu_hep_lam_tren_du_lieu_da_co_khong_can_tra_lai():
    """Chỉ những thuộc tính ĐÃ bóc được cho từng ứng viên mới lọc tại chỗ được."""
    for change in ("open_later", "open_now", "cheaper", "better_rated", "quieter"):
        assert needs_requery(change) is False


def test_mo_rong_pham_vi_thi_BUOC_phai_tra_lai():
    """Không được bịa ra ứng viên mới ngoài danh sách đã có."""
    assert needs_requery("farther") is True


# --------------------------- mở muộn hơn ---------------------------

def test_mo_muon_hon_loc_theo_GIO_THAT_chu_khong_theo_tu_khoa():
    kept, meta = apply_refinement(ROWS, "open_later", now=NOW)
    tên = [r["name"] for r in kept]
    assert "Sắp đóng" not in tên              # đóng sau 20 phút -> loại
    assert "Mở cả ngày" in tên and "Mở tới 23:30" in tên
    assert meta["requery"] is False


def test_mo_ca_ngay_xep_truoc_khi_loc_theo_gio():
    kept, _ = apply_refinement(ROWS, "open_later", now=NOW)
    assert kept[0]["name"] == "Mở cả ngày"


def test_khong_ro_gio_thi_BO_QUA_va_noi_ro_da_bo_qua():
    """Thiếu dữ liệu khác với không đạt — người dùng cần biết sự khác biệt đó."""
    kept, meta = apply_refinement(ROWS, "open_later", now=NOW)
    assert "Không rõ giờ" not in [r["name"] for r in kept]
    assert meta["unknown"] == 1
    assert "không có dữ liệu" in meta["note"]


def test_moc_gio_cu_the_duoc_ton_trong():
    kept, _ = apply_refinement(ROWS, "open_later", value="23", now=NOW)
    assert [r["name"] for r in kept] == ["Mở cả ngày", "Mở tới 23:30"]


# --------------------------- các hướng khác ---------------------------

def test_gan_hon_phai_TRA_LAI_o_khung_hep_hon_chu_khong_chi_loc():
    """Khung rộng KHÔNG cho thêm lựa chọn — nó chỉ đổi sang cụm quán xa hơn và KHÔNG chỗ
    nào dưới 500 m; khung 1 km trả 6 chỗ cách 0,20-0,63 km — hai tập KHÔNG trùng nhau một
    cái tên. Lọc 'nửa gần hơn' của tập cũ không thể tìm ra quán cách 200 m vì nó chưa bao
    giờ được lấy về."""
    from features.places.refine import radius_factor
    assert needs_requery("closer") is True
    assert radius_factor("closer") < 1.0        # thu hẹp khung nhìn
    assert radius_factor("farther") > 1.0


def test_re_hon_bo_qua_cho_khong_co_du_lieu_gia():
    kept, meta = apply_refinement(ROWS, "cheaper", now=NOW)
    assert [r["name"] for r in kept] == ["Mở tới 23:30"]
    assert meta["unknown"] == 2              # hai chỗ không có dải giá


def test_diem_cao_hon_theo_moc_cu_the():
    kept, _ = apply_refinement(ROWS, "better_rated", value="4.8", now=NOW)
    assert {r["name"] for r in kept} == {"Sắp đóng", "Không rõ giờ"}


# --------------------------- chống bịa ---------------------------

def test_yen_tinh_hon_KHONG_co_bang_chung_thi_khong_nhan_bua():
    kept, meta = apply_refinement(ROWS, "quieter", now=NOW)
    assert kept == []
    assert "không có dữ liệu" in meta["note"]
    assert "không có chỗ nào" not in meta["note"].lower()   # KHÔNG khẳng định là không có


def test_yen_tinh_hon_chi_giu_cho_CO_trich_dan_review():
    rows = ROWS + [_p("Có review", quote="Không gian yên tĩnh, dễ ngồi lâu")]
    kept, _ = apply_refinement(rows, "quieter", now=NOW)
    assert [r["name"] for r in kept] == ["Có review"]


def test_loc_het_thi_phan_biet_KHONG_CO_voi_KHONG_BIET():
    """Hai câu khác hẳn nhau về nghĩa, không được gộp làm một."""
    co_du_lieu = [_p("A", rating=3.0), _p("B", rating=3.1)]
    _, meta1 = apply_refinement(co_du_lieu, "better_rated", value="4.5", now=NOW)
    assert "không có chỗ nào" in meta1["note"].lower()

    khong_du_lieu = [_p("A"), _p("B")]
    _, meta2 = apply_refinement(khong_du_lieu, "better_rated", value="4.5", now=NOW)
    assert "không có dữ liệu" in meta2["note"]


def test_huong_tinh_chinh_la_thi_khong_lam_gi_ca():
    kept, meta = apply_refinement(ROWS, "lung tung", now=NOW)
    assert len(kept) == len(ROWS)
    assert "chưa biết cách" in meta["note"]


# ============ Tầng tool: phiên nhớ ngữ cảnh lượt trước ============

from features.places.service import PlacesService          # noqa: E402
from agent.tools import ToolRegistry                          # noqa: E402
from features.contract import FeatureContext                  # noqa: E402
from features.places.tools import register as register_place_tools  # noqa: E402
from unittest.mock import patch                               # noqa: E402
from utils.config import config                               # noqa: E402
from services.location import LocationStore       # noqa: E402

_LINES = {
    "som": ["Quán Sớm", "4,5(120)", "Quán cà phê ·  · S1", "Sắp đóng cửa · 22:00"],
    "muon": ["Quán Muộn", "4,7(300)", "Quán cà phê ·  · S2", "Đang mở cửa · Đóng cửa vào 23:59"],
    "caday": ["Quán Cả Ngày", "4,6(90)", "Quán cà phê · S3", "Mở cả ngày"],
}


def _items():
    return [
        {"name": "Quán Sớm", "url": "u1", "lat": 10.845, "lng": 106.838,
         "lines": _LINES["som"], "aria": ["4,5 sao 120 bài đánh giá"]},
        {"name": "Quán Muộn", "url": "u2", "lat": 10.848, "lng": 106.840,
         "lines": _LINES["muon"], "aria": ["4,7 sao 300 bài đánh giá"]},
        {"name": "Quán Cả Ngày", "url": "u3", "lat": 10.852, "lng": 106.843,
         "lines": _LINES["caday"], "aria": ["4,6 sao 90 bài đánh giá"]},
    ]


class _Bridge:
    connected = True

    def __init__(self):
        self.calls = 0
        self.sent_zoom = []

    def send_command(self, action, timeout=None, **kw):
        self.calls += 1
        self.sent_zoom.append(kw.get("zoom"))
        return {"pageOutcome": "RAW", "items": _items(), "diagnostics": {}}

    @property
    def sent_radius(self):
        """Zoom càng LỚN thì khung càng hẹp -> dùng nghịch đảo làm thước bán kính."""
        return [-z if z is not None else 0 for z in self.sent_zoom]


def _setup():
    bridge = _Bridge()
    loc = LocationStore(geocoder=lambda n: {"latitude": 10.8444, "longitude": 106.8379,
                                            "name": "Vinhomes Grand Park"})
    loc.set_place("Vinhomes Grand Park")
    reg = ToolRegistry()
    # Ghim PLACES_LIMIT lúc đăng ký: `register` đọc config một lần rồi đóng gói vào
    # closure, nên test khỏi phụ thuộc biến môi trường của máy chạy.
    with patch.object(config, "PLACES_LIMIT", 3):
        register_place_tools(reg, FeatureContext(places=PlacesService(bridge=bridge,
                                                                     source="maps"),
                                                 location=loc))
    return reg, bridge


def test_chua_tim_gi_ma_da_tinh_chinh_thi_khong_doan():
    reg, bridge = _setup()
    câu = reg.get("refine_places").handler(change="open_later")
    assert "tìm gì trước" in câu
    assert bridge.calls == 0                  # KHÔNG được tự tra bừa


def test_tinh_chinh_KHONG_tra_lai_mang():
    """Đây là điểm ăn tiền của S3: trả lời trong ~1 giây thay vì ~12."""
    reg, bridge = _setup()
    reg.get("find_nearby").handler(query="quán cà phê")
    assert bridge.calls == 1
    reg.get("refine_places").handler(change="open_later")
    assert bridge.calls == 1                  # vẫn 1 — không gọi Maps lần nữa


@pytest.mark.parametrize("change", ["farther", "closer"])
def test_doi_KHUNG_NHIN_thi_phai_tra_lai(change):
    """Cả hai hướng đều đổi khung nhìn — mà retrieval của Maps phụ thuộc khung nhìn."""
    reg, bridge = _setup()
    reg.get("find_nearby").handler(query="quán cà phê")
    reg.get("refine_places").handler(change=change)
    assert bridge.calls == 2


def test_gan_hon_tra_lai_voi_ban_kinh_NHO_hon():
    reg, bridge = _setup()
    reg.get("find_nearby").handler(query="quán cà phê", radius_km=2)
    reg.get("refine_places").handler(change="closer")
    assert bridge.sent_radius[-1] < bridge.sent_radius[0]


def test_tinh_chinh_giu_nguyen_khu_vuc_va_loai_dia_diem_cua_luot_truoc():
    reg, _ = _setup()
    reg.get("find_nearby").handler(query="quán cà phê")
    câu = reg.get("refine_places").handler(change="open_later")
    assert "quán cà phê" in câu                # không đổi sang truy vấn khác
    assert "mở muộn hơn" in câu


def test_so_thu_tu_sau_khi_loc_tro_dung_danh_sach_vua_doc():
    reg, _ = _setup()
    reg.get("find_nearby").handler(query="quán cà phê")
    reg.get("refine_places").handler(change="open_later")
    mở = reg.get("open_place_result").handler(index=1)
    assert "Quán Sớm" not in mở               # chỗ đã bị lọc ra không còn là số 1


def test_loc_het_thi_GIU_danh_sach_cu_de_con_loc_kieu_khac():
    reg, _ = _setup()
    reg.get("find_nearby").handler(query="quán cà phê")
    câu = reg.get("refine_places").handler(change="quieter")
    assert "rộng ra" in câu
    # danh sách cũ vẫn còn -> lọc kiểu khác vẫn chạy
    tiếp = reg.get("refine_places").handler(change="open_later")
    assert "Quán" in tiếp


def test_huong_tinh_chinh_khong_hop_le_thi_hoi_lai():
    reg, _ = _setup()
    reg.get("find_nearby").handler(query="quán cà phê")
    assert "hướng nào" in reg.get("refine_places").handler(change="mập mờ")
