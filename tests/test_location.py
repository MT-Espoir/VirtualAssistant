"""Kho vị trí runtime + tầng tool tra địa điểm."""

import json
import os

from features.places.service import PlacesService
from agent.router import Router
from conftest import full_case_tools

CT = full_case_tools()
from agent.tools import ToolRegistry
from features.contract import FeatureContext
from features.places.tools import register as register_place_tools
from services.location import LocationStore

CAU_GIAY = {"latitude": 21.0313, "longitude": 105.7908, "name": "Cầu Giấy",
            "admin1": "Hà Nội", "admin2": "Cầu Giấy"}


def _store(tmp_path=None, hit=CAU_GIAY):
    path = str(tmp_path / "loc.json") if tmp_path else None
    return LocationStore(path=path, geocoder=lambda name: hit)


# --------------------------- kho vị trí ---------------------------

def test_chua_biet_vi_tri_thi_khong_doan_bua():
    s = _store()
    assert not s.has() and s.coords() is None and s.coarse() == ""


def test_luu_toa_do_va_ngu_canh_tho():
    s = _store()
    assert s.set_place("Cầu Giấy") == "Cầu Giấy"
    assert s.coords() == (21.0313, 105.7908)
    assert s.coarse("province") == "Hà Nội"
    assert s.coarse("district") == "Cầu Giấy"


def test_granularity_none_khong_bom_gi_vao_prompt():
    s = _store()
    s.set_place("Cầu Giấy")
    assert s.coarse("none") == ""
    assert s.coarse("lung tung") == ""       # giá trị lạ -> mặc định an toàn: không bơm


def test_toa_do_chinh_xac_KHONG_nam_trong_phan_tho():
    """Bất biến quyền riêng tư: thứ được phép vào prompt không mang toạ độ."""
    s = _store()
    s.set_place("Cầu Giấy")
    for g in ("province", "district", "none"):
        assert "21.03" not in s.coarse(g)
        assert "105.79" not in s.coarse(g)


def test_geocode_that_bai_thi_khong_ghi_gi():
    s = _store(hit=None)
    assert s.set_place("Xyzzy") is None
    assert not s.has()


def test_song_qua_phien_khi_co_duong_dan(tmp_path):
    s = _store(tmp_path)
    s.set_place("Cầu Giấy")
    lại = LocationStore(path=str(tmp_path / "loc.json"))
    assert lại.coords() == (21.0313, 105.7908)


def test_file_hong_thi_suy_bien_an_toan(tmp_path):
    p = tmp_path / "loc.json"
    p.write_text("{ hỏng", encoding="utf-8")
    assert not LocationStore(path=str(p)).has()


# --------------------------- tầng tool ---------------------------

class _FakePlaces:
    radius_km = 5.0

    def __init__(self, out=None, area=None):
        self.out = out or {"outcome": "OK", "results": [], "diagnostics": {}, "source": "maps"}
        self.area = area
        self.calls = []

    def find_nearby(self, query, center, radius_km=None):
        self.calls.append(("nearby", query, center, radius_km))
        return dict(self.out)

    def find_place(self, name, origin=None, area=None):
        self.calls.append(("place", name, origin, area))
        return dict(self.out, area=area)

    def resolve_area(self, name, origin=None):
        self.calls.append(("area", name, origin, None))
        return self.area


def _reg(places, location):
    reg = ToolRegistry()
    register_place_tools(reg, FeatureContext(places=places, location=location))
    return reg


def test_chua_biet_vi_tri_thi_HOI_LAI_chu_khong_dung_mac_dinh_cung():
    """Rơi về 'Hà Nội' rồi trả lời trơn tru là kiểu sai tệ nhất — không ai phát hiện."""
    places = _FakePlaces()
    reg = _reg(places, _store())
    câu = reg.get("find_nearby").handler(query="quán cà phê")
    assert "khu vực" in câu.lower()
    assert places.calls == []                # KHÔNG được gọi nguồn khi chưa biết ở đâu


def test_near_de_trong_thi_dung_vi_tri_hien_tai():
    places, loc = _FakePlaces(), _store()
    loc.set_place("Cầu Giấy")
    _reg(places, loc).get("find_nearby").handler(query="quán cà phê")
    assert places.calls[0][2] == (21.0313, 105.7908)


def test_near_co_gia_tri_thi_giai_theo_khu_vuc_do():
    places = _FakePlaces(area=(16.0678, 108.2208, "Hải Châu"))
    _reg(places, _store()).get("find_nearby").handler(query="quán ăn", near="Đà Nẵng")
    nearby = [c for c in places.calls if c[0] == "nearby"][0]
    assert nearby[2] == (16.0678, 108.2208)


def test_find_place_chuyen_tiep_khu_vuc_nguoi_dung_neu():
    places, loc = _FakePlaces(), _store()
    loc.set_place("Cầu Giấy")
    _reg(places, loc).get("find_place").handler(name="Fahasa Nguyễn Văn Cừ", in_area="quận 9")
    assert places.calls[0][0] == "place" and places.calls[0][3] == "quận 9"


def test_danh_sach_KHONG_duoc_luu_khi_luot_do_that_bai():
    """Nếu lưu, câu 'mở cái thứ 2' sẽ trỏ vào danh sách của lượt TRƯỚC."""
    ok = {"outcome": "OK", "diagnostics": {}, "source": "maps",
          "results": [{"name": "Quán A", "url": "u1", "distance_km": 1.0}]}
    places, loc = _FakePlaces(ok), _store()
    loc.set_place("Cầu Giấy")
    reg = _reg(places, loc)
    reg.get("find_nearby").handler(query="quán cà phê")
    places.out = {"outcome": "SCRAPE_FAILED", "results": [], "diagnostics": {}, "source": "maps"}
    reg.get("find_nearby").handler(query="hiệu thuốc")
    assert "chưa có" in reg.get("open_place_result").handler(index=1).lower()


def test_open_place_result_chan_so_ngoai_pham_vi():
    ok = {"outcome": "OK", "diagnostics": {}, "source": "maps",
          "results": [{"name": "Quán A", "url": "u1", "distance_km": 1.0}]}
    places, loc = _FakePlaces(ok), _store()
    loc.set_place("Cầu Giấy")
    reg = _reg(places, loc)
    reg.get("find_nearby").handler(query="quán cà phê")
    assert "không có số 5" in reg.get("open_place_result").handler(index=5)
    assert "số thứ tự" in reg.get("open_place_result").handler(index="abc")


def test_set_my_location_ghi_vao_kho_runtime():
    loc = _store()
    places = _FakePlaces(area=(21.0313, 105.7908, "Cầu Giấy"))
    reg = _reg(places, loc)
    assert "Cầu Giấy" in reg.get("set_my_location").handler(place="Cầu Giấy")
    assert loc.coords() == (21.0313, 105.7908)


def test_set_my_location_dung_CHUNG_bo_giai_dia_danh_voi_find_nearby():
    """Lỗi thật: "Vinhomes Grand Park Thủ Đức" — find_nearby giải được (qua
    bản đồ) nhưng set_my_location trượt (dùng danh bạ hành chính cũ), khiến trợ lý nói
    "đã ghi nhớ" trong khi không lưu được gì."""
    loc = _store()
    places = _FakePlaces(area=(10.8444, 106.8379, "Vinhomes Grand Park"))
    reg = _reg(places, loc)
    câu = reg.get("set_my_location").handler(place="Vinhomes Grand Park Thủ Đức")
    assert "nhớ rồi" in câu
    assert loc.coords() == (10.8444, 106.8379)
    assert any(c[0] == "area" for c in places.calls)      # đi qua resolve_area, không rẽ lối khác


def test_giai_qua_ban_do_thi_KHONG_dien_ngu_canh_tho():
    """Tên một khu đô thị cụ thể không phải 'ngữ cảnh thô' — không được rơi vào prompt."""
    loc = _store()
    loc.set_coords(10.8444, 106.8379, "Vinhomes Grand Park")
    assert loc.coarse("province") == ""
    assert loc.coarse("district") == ""


def test_set_my_location_that_bai_thi_KHONG_noi_da_nho():
    loc = _store()
    reg = _reg(_FakePlaces(area=None), loc)
    câu = reg.get("set_my_location").handler(place="Xyzzy không tồn tại")
    assert "nhớ rồi" not in câu
    assert loc.coords() is None


# --------------------------- router ---------------------------

def test_case_place_ton_tai_va_thu_hep_dung_tool():
    assert "place" in CT
    assert set(CT["place"]) == {"find_nearby", "find_place", "research_places",
                                        "refine_places", "open_place_result",
                                        "set_my_location"}


def test_classify_khong_con_phu_thuoc_thu_tu_case():
    """Trước đây `place` PHẢI đứng trước `web` trong bảng vì classify khớp chuỗi con.

    Ràng buộc đó đã gỡ: `match_case` khớp tên DÀI NHẤT trước. Kiểm bằng cách đảo ngược
    hẳn bảng — kết quả phải không đổi. Nhờ vậy thứ tự `FEATURES` được tự do phục vụ
    hiệu suất (thứ tự tool trong prompt) mà không kéo theo hệ quả đúng/sai nào.
    """
    xuoi = Router(llm=None, case_tools=CT)
    nguoc = Router(llm=None, case_tools=dict(reversed(list(CT.items()))))
    for cau in ("place", "web", "weather", "Nhóm: place ạ", "khong-biet-gi"):
        assert xuoi.match_case(cau) == nguoc.match_case(cau)


def test_match_case_uu_tien_ten_dai_hon():
    """Bộ tên hiện tại không có cặp chuỗi con nào, nên dựng cặp giả để khoá hành vi."""
    r = Router(llm=None, case_tools={"mail": [], "email": [], "general": None})
    assert r.match_case("email") == "email"      # không bị 'mail' nuốt


def test_router_thu_hep_xuong_dung_bo_tool_place():
    places, loc = _FakePlaces(), _store()
    reg = _reg(places, loc)
    _, specs = Router(llm=None, case_tools=CT).select_for_case("place", reg)
    assert {s["name"] for s in specs} == set(CT["place"])


# --------------------------- xuyên tầng ---------------------------

class _FakeBridge:
    """Bridge giả: nhận payload MAPS_READ thật, trả phản hồi đúng định dạng extension."""

    connected = True

    def __init__(self, items, page="RAW"):
        self.items, self.page, self.sent = items, page, []

    def send_command(self, action, timeout=None, **kwargs):
        self.sent.append((action, kwargs))
        return {"type": "STATUS", "action": "MAPS_READ", "pageOutcome": self.page,
                "items": self.items, "diagnostics": {"mode": "list"}}


def _maps_item(name, lat, lng):
    return {"name": name, "url": "https://www.google.com/maps/place/x",
            "lat": lat, "lng": lng, "rating": 4.5, "address": "Đâu đó"}


def test_xuyen_tang_tool_den_bridge_giu_dung_giao_thuc():
    bridge = _FakeBridge([_maps_item("Oleoleo Coffee", 21.0320, 105.7915)])
    loc = _store()
    loc.set_place("Cầu Giấy")
    reg = _reg(PlacesService(bridge=bridge, source="maps"), loc)

    câu = reg.get("find_nearby").handler(query="quán cà phê")

    action, kwargs = bridge.sent[0]
    assert action == "MAPS_READ"
    assert kwargs["lat"] == 21.0313 and kwargs["lng"] == 105.7908   # tâm BẮT BUỘC
    assert "action" not in kwargs                                    # không gửi lặp khoá
    assert "Oleoleo Coffee" in câu
    assert reg.get("open_place_result").handler(index=1).startswith("Chỗ số 1")


def test_xuyen_tang_ket_qua_xa_bi_chan_va_noi_dung_su_that():
    """Maps trả kết quả Sài Gòn cho người ở Lai Châu."""
    bridge = _FakeBridge([_maps_item("Nhà Thuốc FPT Long Châu", 10.768, 106.679)])
    loc = LocationStore(geocoder=lambda n: {"latitude": 22.37, "longitude": 102.83,
                                            "name": "Mường Tè", "admin1": "Lai Châu"})
    loc.set_place("Mường Tè")
    def _no_network(url, params):
        raise OSError("test không được gọi mạng")

    reg = _reg(PlacesService(bridge=bridge, source="maps", http_get=_no_network), loc)

    câu = reg.get("find_nearby").handler(query="hiệu thuốc")
    assert "không thấy" in câu.lower()
    assert "Long Châu" not in câu              # tuyệt đối không đọc lên chỗ cách 1350 km
    assert "1350 km" in câu                    # nhưng vẫn nói thật là gần nhất cách bao xa


def test_xuyen_tang_nguon_hong_khong_bi_bien_thanh_khong_co():
    bridge = _FakeBridge([], page="SCRAPE_FAILED")
    loc = _store()
    loc.set_place("Cầu Giấy")
    # source=osm bị tắt bằng http_get lỗi -> cả hai nguồn hỏng
    svc = PlacesService(bridge=bridge, source="maps",
                        http_get=lambda u, p: (_ for _ in ()).throw(OSError("mạng hỏng")))
    câu = _reg(svc, loc).get("find_nearby").handler(query="quán cà phê")
    assert "không có" not in câu.lower() and "không tìm thấy" not in câu.lower()
    assert "chưa" in câu.lower()
