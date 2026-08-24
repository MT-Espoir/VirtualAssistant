"""Test tra địa điểm — khoá lại các lỗi THẬT đã gặp.

Mọi ca ở đây đều bắt nguồn từ dữ liệu thật, không phải tình huống tưởng tượng:
- Maps nới bán kính trong im lặng (Mường Tè -> kết quả cách 1.350 km)
- Tên khớp lỏng ("Nhà sách Nguyễn Văn Cừ" vs "Nhà sách Fahasa Nguyễn Văn Cừ")
- Trang chi tiết (/maps/place/) không có feed -> 1 kết quả là ĐỦ, không phải thiếu
"""

import pytest

from actions.places import (GENERIC_TOKENS, PlacesService, apply_policy,
                            build_overpass_query, haversine_km, name_score,
                            osm_filters, parse_overpass, tokens)
from services.browser_protocol import (SAYS_CANNOT_LOOK_UP, SAYS_NOTHING_FOUND,
                                       build_maps_read, parse_maps_response,
                                       summarize_places)

HANOI = (21.0313, 105.7908)
SAIGON = (10.7769, 106.7009)
MUONG_TE = (22.37, 102.83)


def _item(name, lat, lng):
    return {"name": name, "url": "https://maps/x", "lat": lat, "lng": lng,
            "rating": None, "address": None}


# --------------------------- khoảng cách ---------------------------

def test_haversine_khop_khoang_cach_thuc_te():
    d = haversine_km(HANOI[0], HANOI[1], SAIGON[0], SAIGON[1])
    assert 1100 < d < 1200          # Hà Nội - Sài Gòn ~1150 km đường chim bay


def test_ket_qua_xa_bi_loai_khi_co_rang_buoc():
    """Ca THẬT: tra ở Mường Tè, Maps trả nhà thuốc Sài Gòn cách 1.350 km."""
    raw = [_item("Nhà Thuốc FPT Long Châu", 10.768, 106.679)]
    outcome, rows, diag = apply_policy("RAW", raw, center=MUONG_TE, radius_km=5)
    assert outcome == "OUT_OF_AREA"
    assert rows == []
    assert diag["nearest_km"] > 1000        # để nói được "gần nhất cách ~1350 km"


def test_ket_qua_gan_duoc_giu():
    raw = [_item("Nhà Thuốc Văn Minh", 10.7680, 106.6796)]
    outcome, rows, _ = apply_policy("RAW", raw, center=SAIGON, radius_km=5)
    assert outcome == "OK" and len(rows) == 1
    assert rows[0]["distance_km"] < 5


def test_khong_rang_buoc_thi_khong_loc_khoang_cach():
    """'X ở đâu' KHÔNG có ràng buộc -> không được lặng lẽ bỏ chỗ ở xa (yêu cầu của user)."""
    raw = [_item("Nhà sách Fahasa Nguyễn Văn Cừ", 10.76, 106.68)]
    outcome, rows, _ = apply_policy("RAW", raw, center=HANOI, radius_km=0,
                                    match_name="Nhà sách Fahasa Nguyễn Văn Cừ")
    assert outcome == "OK"
    assert len(rows) == 1
    assert rows[0]["distance_km"] > 1000     # vẫn báo khoảng cách để nói "cách bạn ~1150 km"


# --------------------------- khớp tên ---------------------------

def test_token_chung_chung_khong_duoc_ganh_viec_khop_ten():
    """Thước khớp tên quá lỏng: hai chuỗi khác hẳn nhau vẫn qua ngưỡng."""
    score, missing, exact = name_score("Nhà sách Fahasa Nguyễn Văn Cừ",
                                       "Nhà sách Nguyễn Văn Cừ")
    assert not exact
    assert "fahasa" in missing               # nêu đúng cái gì thiếu
    assert score < 1.0


def test_khop_du_token_dac_trung_la_exact():
    score, missing, exact = name_score("Nhà sách Fahasa Nguyễn Văn Cừ",
                                       "Nhà sách FAHASA Nguyễn Văn Cừ")
    assert exact and missing == [] and score == 1.0


def test_truy_van_toan_tu_chung_thi_lui_ve_cham_moi_token():
    _, _, exact = name_score("nhà sách", "Nhà sách Nguyễn Văn Cừ")
    assert exact                             # không còn token đặc trưng nào để đòi hỏi


def test_van_khong_bi_coi_la_tu_chung():
    """'văn' là chữ đệm rất phổ biến — coi nó là từ chung sẽ làm mất token của tên người."""
    assert "van" not in GENERIC_TOKENS


def test_chi_khop_mot_phan_thi_bao_APPROX_MATCH_khong_nhan_vo():
    raw = [_item("Nhà sách Nguyễn Văn Cừ", 21.03, 105.79)]
    outcome, rows, _ = apply_policy("RAW", raw, center=HANOI, radius_km=0,
                                    match_name="Nhà sách Fahasa Nguyễn Văn Cừ")
    assert outcome == "APPROX_MATCH"
    assert rows[0]["match"] == "approx"


def test_ten_khac_han_thi_NO_RESULTS():
    raw = [_item("Cửa hàng điện thoại cellphone S", 21.03, 105.79)]
    outcome, rows, _ = apply_policy("RAW", raw, center=HANOI, radius_km=0,
                                    match_name="Nhà sách Fahasa Nguyễn Văn Cừ")
    assert outcome == "NO_RESULTS" and rows == []


def test_khop_ten_duoc_uu_tien_hon_khoang_cach():
    """Sai chỗ thì gần hay xa cũng vô nghĩa -> lọc tên TRƯỚC."""
    raw = [_item("Quán bún chả", 21.0314, 105.7909),                 # rất gần, sai tên
           _item("Nhà sách Fahasa Nguyễn Văn Cừ", 10.76, 106.68)]    # rất xa, đúng tên
    outcome, rows, _ = apply_policy("RAW", raw, center=HANOI, radius_km=0,
                                    match_name="Nhà sách Fahasa Nguyễn Văn Cừ")
    assert outcome == "OK" and len(rows) == 1
    assert rows[0]["name"].startswith("Nhà sách Fahasa")


# --------------------------- mã cấp trang ---------------------------

@pytest.mark.parametrize("page", ["BLOCKED", "SCRAPE_FAILED", "PARSER_ERROR",
                                  "SOURCE_UNAVAILABLE"])
def test_ma_hong_cap_trang_giu_nguyen(page):
    outcome, rows, _ = apply_policy(page, [], center=HANOI, radius_km=5)
    assert outcome == page and rows == []


def test_trang_rong_that_su_moi_la_NO_RESULTS():
    assert apply_policy("EMPTY", [], center=HANOI, radius_km=5)[0] == "NO_RESULTS"


def test_RAW_ma_khong_boc_duoc_gi_la_PARSER_ERROR():
    assert apply_policy("RAW", [], center=HANOI, radius_km=5)[0] == "PARSER_ERROR"


def test_mot_ket_qua_o_trang_chi_tiet_van_la_OK():
    """Trang /maps/place/ chỉ chứa MỘT chỗ — đó là câu trả lời đầy đủ, không phải thiếu."""
    raw = [_item("California Fitness & Yoga", 16.0678, 108.2208)]
    outcome, rows, _ = apply_policy("RAW", raw, center=(16.0678, 108.2208), radius_km=5)
    assert outcome == "OK" and len(rows) == 1


# ============ QUY TẮC PHÁT NGÔN — bất biến quan trọng nhất (G8) ============

_NGHIA_LA_KHONG_CO = ("không có", "không tìm thấy", "không thấy")


@pytest.mark.parametrize("code", SAYS_CANNOT_LOOK_UP)
def test_ma_hong_TUYET_DOI_khong_duoc_noi_khong_co(code):
    """Nguồn hỏng bị diễn đạt thành 'không có quán nào' là nói dối người dùng một cách
    trơn tru — đúng cái bẫy mà bảng mã kết quả sinh ra để chặn."""
    câu = summarize_places(code, [], "quán ăn").lower()
    for cụm in _NGHIA_LA_KHONG_CO:
        assert cụm not in câu, f"{code} nói '{cụm}': {câu}"


@pytest.mark.parametrize("code", SAYS_NOTHING_FOUND)
def test_chi_ba_ma_nay_moi_duoc_noi_khong_co(code):
    câu = summarize_places(code, [{"name": "Chỗ gần giống"}], "quán ăn").lower()
    assert any(c in câu for c in _NGHIA_LA_KHONG_CO)


def test_hai_nhom_ma_khong_chong_nhau_va_phu_het():
    assert not set(SAYS_NOTHING_FOUND) & set(SAYS_CANNOT_LOOK_UP)


def test_OUT_OF_AREA_co_khu_vuc_thi_bao_dung_khu_vuc_do():
    """Yêu cầu của user: 'tìm X ở quận 9' mà không có thì VẪN PHẢI báo không có."""
    câu = summarize_places("OUT_OF_AREA", [], "Fahasa Nguyễn Văn Cừ",
                           {"nearest_km": 12.3}, area="quận 9")
    assert "quận 9" in câu
    assert "không có" in câu.lower()
    assert "12 km" in câu                    # nói thêm chỗ gần nhất SAU khi đã báo không có


def test_APPROX_MATCH_phai_noi_ro_la_khong_dung_cai_duoc_hoi():
    câu = summarize_places("APPROX_MATCH", [{"name": "Nhà sách Nguyễn Văn Cừ"}],
                           "Fahasa Nguyễn Văn Cừ")
    assert "không thấy đúng" in câu.lower()
    assert "Nhà sách Nguyễn Văn Cừ" in câu


def test_nguon_du_phong_duoc_noi_ro_la_tho_hon():
    câu = summarize_places("OK", [{"name": "Nhà thuốc X", "distance_km": 1.2}],
                           "hiệu thuốc", source="osm")
    assert "bản đồ mở" in câu


# --------------------------- giao thức ---------------------------

def test_build_maps_read_bat_buoc_co_toa_do():
    with pytest.raises(ValueError):
        build_maps_read("quán cà phê", None, None)
    with pytest.raises(ValueError):
        build_maps_read("", 21.0, 105.0)


def test_loi_van_chuyen_thanh_SOURCE_UNAVAILABLE_chu_khong_phai_mang_rong():
    page, items, _ = parse_maps_response({"type": "ERROR", "message": "not connected"})
    assert page == "SOURCE_UNAVAILABLE" and items == []
    assert parse_maps_response(None)[0] == "SOURCE_UNAVAILABLE"


def test_muc_thieu_toa_do_bi_bo_vi_khong_kiem_chung_duoc():
    page, items, _ = parse_maps_response({"pageOutcome": "RAW", "items": [
        {"name": "Có toạ độ", "lat": 1.0, "lng": 2.0},
        {"name": "Thiếu toạ độ"},
        {"lat": 1.0, "lng": 2.0}]})
    assert page == "RAW" and [i["name"] for i in items] == ["Có toạ độ"]


# --------------------------- nguồn OSM ---------------------------

def test_osm_khop_loai_dia_diem_va_lui_ve_tim_theo_ten():
    assert osm_filters("hiệu thuốc") == ['["amenity"="pharmacy"]']
    assert "name" in osm_filters("Fahasa Nguyễn Văn Cừ")[0]


def test_overpass_bo_muc_khong_ten_hoac_khong_toa_do():
    page, items, _ = parse_overpass({"elements": [
        {"type": "node", "id": 1, "lat": 21.0, "lon": 105.8, "tags": {"name": "Nhà thuốc X"}},
        {"type": "node", "id": 2, "lat": 21.0, "lon": 105.8, "tags": {}}]})
    assert page == "RAW" and len(items) == 1


def test_overpass_rong_la_EMPTY_con_hong_la_SOURCE_UNAVAILABLE():
    assert parse_overpass({"elements": []})[0] == "EMPTY"
    assert parse_overpass(None)[0] == "SOURCE_UNAVAILABLE"


def test_build_overpass_query_thuan_khong_can_mang():
    ql = build_overpass_query("hiệu thuốc", 21.03, 105.79, 5000)
    assert "amenity" in ql and "around:5000,21.03,105.79" in ql


# --------------------------- định tuyến nguồn ---------------------------

class _FakeHTTP:
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def __call__(self, url, params):
        self.calls += 1
        payload = self.payload

        class R:
            def json(self):
                return payload
        return R()


def test_bridge_tat_thi_lui_ve_OSM():
    osm = {"elements": [{"type": "node", "id": 1, "lat": 21.031, "lon": 105.791,
                         "tags": {"name": "Nhà thuốc Gần"}}]}
    svc = PlacesService(bridge=None, source="maps", http_get=_FakeHTTP(osm))
    out = svc.find_nearby("hiệu thuốc", HANOI)
    assert out["outcome"] == "OK" and out["source"] == "osm"


def test_ca_hai_nguon_hong_thi_giu_ket_luan_cua_nguon_chinh():
    svc = PlacesService(bridge=None, source="maps", http_get=_FakeHTTP({"elements": []}))
    out = svc.find_nearby("hiệu thuốc", HANOI)
    assert out["outcome"] == "SOURCE_UNAVAILABLE"      # KHÔNG phải 'không có quán'
    assert out["diagnostics"]["fallback_tried"] == "NO_RESULTS"


def test_khu_vuc_khong_tra_duoc_thi_khong_bia():
    svc = PlacesService(bridge=None, geocoder=lambda name: None)
    out = svc.find_place("Fahasa", area="Xyzzy không tồn tại")
    assert out["diagnostics"]["unknown_area"] == "Xyzzy không tồn tại"


def test_find_place_khong_biet_vi_tri_thi_khong_doan():
    svc = PlacesService(bridge=None)
    out = svc.find_place("Fahasa Nguyễn Văn Cừ", origin=None)
    assert out["outcome"] == "SOURCE_UNAVAILABLE"


# ============ Giải địa danh — lỗi phát hiện khi chạy thật ============
# Người dùng nói "quán cà phê gần Vinhomes Grand Park" -> trợ lý trả lời không tra được.
# Nguyên nhân: danh bạ Open-Meteo chỉ biết địa danh HÀNH CHÍNH, và bản cũ luôn BỎ DẤU
# trước khi tra nên hỏng cả với "Thủ Đức".

def test_token_chu_so_khong_bi_bo_du_chi_mot_ky_tu():
    """'quận 9' phân biệt với 'quận 1' bằng đúng chữ số — bỏ nó đi là mất hết ý nghĩa."""
    assert "9" in tokens("quận 9")
    score, _, exact = name_score("quận 9", "Quận 9")
    assert exact and score == 1.0
    _, missing, exact9 = name_score("quận 9", "Quận 1")
    assert not exact9 and "9" in missing


class _FakeGeo:
    """Danh bạ giả: chỉ trả kết quả cho ĐÚNG biến thể được cấu hình."""

    def __init__(self, table):
        self.table, self.asked = table, []

    def __call__(self, url, params):
        self.asked.append(params["name"])
        hits = self.table.get(params["name"], [])

        class R:
            def json(self):
                return {"results": hits}
        return R()


def test_gazetteer_tra_ca_hai_bien_the_co_dau_va_bo_dau():
    """'Thủ Đức' CHỈ ra kết quả khi giữ dấu — bỏ dấu thì trả None."""
    geo = _FakeGeo({"Thủ Đức": [{"name": "Thủ Đức", "latitude": 10.849, "longitude": 106.772}]})
    svc = PlacesService(bridge=None, http_get=geo)
    assert svc.resolve_area("Thủ Đức")[2] == "Thủ Đức"
    assert "Thủ Đức" in geo.asked and "Thu Duc" in geo.asked      # đã thử cả hai


def test_gazetteer_chon_theo_do_khop_ten_chu_khong_theo_thu_tu():
    """'Đà Lạt' có dấu trả nhầm 'Đã Tịch' — phải xếp hạng theo tên, không lấy cái đầu tiên."""
    geo = _FakeGeo({
        "Đà Lạt": [{"name": "Đã Tịch", "latitude": 16.7, "longitude": 107.0}],
        "Da Lat": [{"name": "Ðà Lạt", "latitude": 11.94, "longitude": 108.44}],
    })
    svc = PlacesService(bridge=None, http_get=geo)
    lat = svc.resolve_area("Đà Lạt")[0]
    assert 11 < lat < 12                       # Lâm Đồng, không phải Quảng Trị


def test_khong_ten_nao_khop_thi_tra_None_chu_khong_nhan_bua():
    geo = _FakeGeo({"Xyzzy": [{"name": "Nơi Khác Hẳn", "latitude": 1.0, "longitude": 2.0}]})
    svc = PlacesService(bridge=None, http_get=geo)
    assert svc.resolve_area("Xyzzy") is None


class _AnchorBridge:
    """Bridge giả trả về một POI (chế độ trang chi tiết của Maps)."""

    connected = True

    def __init__(self, name, lat, lng):
        self.payload = {"name": name, "url": "u", "lat": lat, "lng": lng}
        self.sent = []

    def send_command(self, action, timeout=None, **kwargs):
        self.sent.append(kwargs)
        return {"pageOutcome": "RAW", "items": [self.payload], "diagnostics": {"mode": "place"}}


def test_danh_ba_khong_co_thi_hoi_chinh_Maps():
    """POI như 'Vinhomes Grand Park' không nằm trong danh bạ hành chính — Maps thì có."""
    geo = _FakeGeo({})
    bridge = _AnchorBridge("Vinhomes Grand Park", 10.8444, 106.8379)
    svc = PlacesService(bridge=bridge, http_get=geo)
    spot = svc.resolve_area("Vinhomes Grand Park")
    assert spot is not None
    assert spot[2] == "Vinhomes Grand Park"
    assert round(spot[0], 2) == 10.84


def test_maps_tra_ve_cho_KHAC_thi_khong_nhan_lam_diem_neo():
    geo = _FakeGeo({})
    bridge = _AnchorBridge("Quán phở Hà Nội", 21.0, 105.8)
    svc = PlacesService(bridge=bridge, http_get=geo)
    assert svc.resolve_area("Vinhomes Grand Park") is None


def test_khong_co_bridge_thi_khong_treo_o_tang_maps():
    svc = PlacesService(bridge=None, http_get=_FakeGeo({}))
    assert svc.resolve_area("Vinhomes Grand Park") is None


# ====== Đọc ít / giữ nhiều + zoom theo bán kính ======
# Người dùng: "chỉ lựa 3 quán trong khi bản đồ có ít nhất 8".

def test_zoom_khop_voi_ban_kinh():
    """Bảng Maps luôn bị cắt ở vài mục; zoom quyết định LẤY ĐƯỢC MỤC NÀO."""
    from services.browser_protocol import zoom_for_radius
    assert zoom_for_radius(1) == 17          # quanh đây rất gần -> khung chặt
    assert zoom_for_radius(5) == 15
    assert zoom_for_radius(20) == 13
    assert zoom_for_radius(0) == 13          # không ràng buộc -> khung rộng
    assert zoom_for_radius("hỏng") == 15     # đầu vào lạ -> mặc định an toàn


def test_zoom_duoc_gui_kem_khi_co_ban_kinh():
    assert build_maps_read("cà phê", 10.8, 106.8, radius_km=1)["zoom"] == 17
    assert "zoom" not in build_maps_read("cà phê", 10.8, 106.8)


def test_doc_it_nhung_noi_that_tong_so():
    """Đọc 6-8 tên qua TTS thì quá dài — nhưng giấu bớt mà không nói là làm sai lệch."""
    rows = [{"name": f"Quán {i}", "distance_km": 0.2 * i} for i in range(1, 7)]
    câu = summarize_places("OK", rows, "quán cà phê", speak_limit=3)
    assert "6 chỗ" in câu                    # nói thật là tìm được 6
    assert "Quán 3" in câu and "Quán 4" not in câu    # nhưng chỉ đọc 3
    assert "còn 3 chỗ nữa" in câu


def test_du_it_hon_nguong_thi_khong_noi_thua():
    rows = [{"name": "Quán A", "distance_km": 0.3}]
    câu = summarize_places("OK", rows, "quán cà phê", speak_limit=3)
    assert "chỗ nữa" not in câu


def test_service_giu_nhieu_hon_so_doc_len():
    """Giữ 8 để 'mở cái thứ 5' còn chạy, dù chỉ đọc 3."""
    items = [_item(f"Quán {i}", 10.8444 + i * 0.001, 106.8379) for i in range(1, 9)]

    class _B:
        connected = True

        def send_command(self, action, timeout=None, **kw):
            return {"pageOutcome": "RAW", "items": items, "diagnostics": {}}

    svc = PlacesService(bridge=_B(), source="maps", limit=8)
    out = svc.find_nearby("quán cà phê", (10.8444, 106.8379), radius_km=5)
    assert out["outcome"] == "OK"
    assert len(out["results"]) == 8          # giữ đủ, không cắt còn 3


# ============ S1: đặc trưng đi xuyên tầng chính sách + câu đọc ============

_OLEOLEO_LINES = ["Oleoleo Coffee & Cats", "4,8(646) · 1-100.000 ₫",
                  "Quán cà phê ·  · 5t2 Ngõ 62", "Đang mở cửa · Đóng cửa vào 22:30",
                  '"Quán yên tĩnh hợp học bài."']


def test_dac_trung_duoc_gan_khi_qua_chinh_sach():
    raw = [{"name": "Oleoleo", "url": "u", "lat": 21.032, "lng": 105.7915,
            "lines": _OLEOLEO_LINES, "aria": ["4,8 sao 646 bài đánh giá"]}]
    outcome, rows, _ = apply_policy("RAW", raw, center=(21.0313, 105.7908), radius_km=5)
    assert outcome == "OK"
    r = rows[0]
    assert r["rating"] == 4.8 and r["reviews"] == 646
    assert r["opening"]["closes_at"] == (22, 30)
    assert r["price"]["max"] == 100000
    assert "yên tĩnh" in r["quote"]


def test_cau_doc_neu_sap_dong_cua_khi_co_du_lieu():
    rows = [{"name": "Balan", "distance_km": 0.3,
             "opening": {"state": "closing_soon", "closes_at": (22, 0)}}]
    câu = summarize_places("OK", rows, "quán cà phê")
    assert "sắp đóng cửa lúc 22:00" in câu


def test_cau_doc_KHONG_bia_gi_khi_thieu_du_lieu_gio():
    """Không biết giờ mở cửa thì im lặng, không suy ra 'đang mở'."""
    rows = [{"name": "Quán X", "distance_km": 0.3, "opening": {"state": "unknown"}}]
    câu = summarize_places("OK", rows, "quán cà phê")
    assert "mở" not in câu.lower().replace("bạn muốn mở chỗ", "")
    assert "đóng" not in câu.lower()


def test_cau_doc_neu_mo_ca_ngay():
    rows = [{"name": "HARU", "distance_km": 0.4, "opening": {"state": "open_24h"}}]
    assert "mở cả ngày" in summarize_places("OK", rows, "quán cà phê")


# ====== Khung nhìn quyết định kết quả ======

def test_khung_nhin_hep_khi_ban_kinh_nho():
    """Cùng một tâm, khung rộng bỏ qua hẳn các chỗ sát bên; khung hẹp thì lấy được —
    6 chỗ cách 0,20-0,63 km. Khung rộng KHÔNG cho nhiều lựa chọn hơn — nó giấu mất cụm
    quán ngay cạnh người dùng."""
    from services.browser_protocol import zoom_for_radius
    assert zoom_for_radius(1.0) > zoom_for_radius(5.0)


def test_ban_kinh_mac_dinh_du_hep_de_thay_quan_gan():
    from utils.config import config
    from services.browser_protocol import zoom_for_radius
    assert config.PLACES_RADIUS_KM <= 1.0
    assert zoom_for_radius(config.PLACES_RADIUS_KM) >= 17


class _CountingBridge:
    connected = True

    def __init__(self, items_by_call):
        self.items_by_call, self.calls, self.zooms = items_by_call, 0, []

    def send_command(self, action, timeout=None, **kw):
        self.zooms.append(kw.get("zoom"))
        items = self.items_by_call[min(self.calls, len(self.items_by_call) - 1)]
        self.calls += 1
        return {"pageOutcome": "RAW", "items": items, "diagnostics": {}}


def test_vung_thua_thi_tu_noi_MOT_lan():
    xa = [_item("Quán xa", 21.20, 105.90)]          # ngoài bán kính 1 km
    bridge = _CountingBridge([xa, xa])
    svc = PlacesService(bridge=bridge, source="maps", http_get=lambda u, p: (_ for _ in ()).throw(OSError()))
    out = svc.find_nearby("quán cà phê", HANOI, radius_km=1.0)
    assert bridge.calls == 2                         # đã thử nới
    assert out["outcome"] == "OUT_OF_AREA"           # nới vẫn không ra -> nói thật
    assert bridge.zooms[1] < bridge.zooms[0]         # lần hai khung rộng hơn


def test_co_ket_qua_ngay_thi_KHONG_noi_them():
    gan = [_item("Quán gần", 21.0320, 105.7915)]
    bridge = _CountingBridge([gan])
    svc = PlacesService(bridge=bridge, source="maps")
    out = svc.find_nearby("quán cà phê", HANOI, radius_km=1.0)
    assert out["outcome"] == "OK" and bridge.calls == 1
