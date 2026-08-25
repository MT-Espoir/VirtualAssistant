"""
Tra cứu ĐỊA ĐIỂM — hai ý định, hai cách kiểm chứng.

- `find_nearby`  : tìm theo LOẠI quanh một điểm  -> kiểm chứng bằng KHOẢNG CÁCH
- `find_place`   : tìm ĐÚNG MỘT CHỖ có tên       -> kiểm chứng bằng TÊN

Ràng buộc không gian đến từ LỜI NGƯỜI DÙNG, không từ mặc định của hệ thống: hỏi
"quanh đây" thì bán kính là ràng buộc; hỏi "X ở đâu" thì KHÔNG có ràng buộc nào, và áp
bán kính vào đó là bịa ra một yêu cầu họ không đặt.

Toàn bộ CHÍNH SÁCH ở đây là hàm THUẦN (test không cần Chrome/mạng); phần chạm DOM nằm
trong extension, phần gọi mạng nằm ở cuối file. Nhờ vậy nguồn Maps và nguồn OSM dùng
chung đúng một hiện thực của luật.

Vì sao phải kiểm chứng: Google Maps NỚI BÁN KÍNH TRONG IM
LẶNG (tra ở Mường Tè trả kết quả cách 1.350 km, trông hoàn toàn bình thường), và tên
khớp lỏng lẻo ("Nhà sách Nguyễn Văn Cừ" khớp 0,83 với "Nhà sách Fahasa Nguyễn Văn Cừ"
dù là chuỗi khác). Không kiểm chứng thì bộ trích chạy đúng mà vẫn giao ra dữ liệu sai.
"""

import math

from utils.logger import get_logger
from features.places.attributes import extract_features
from features.places.ranking import intent_keys, rank
from utils.text_norm import strip_accents

logger = get_logger(__name__)

# Từ chỉ LOẠI địa điểm — không được phép gánh việc khớp tên. Heuristic, còn thiếu;
# xem tests/test_places.py. Ca đã biết là mơ hồ: 'van' (chữ đệm vs "văn phòng").
GENERIC_TOKENS = frozenset("""
nha sach quan cua hang tiem phong kham sieu thi cay xang benh vien cafe ca phe an
gym trung tam cho shop store bar tra sua nha hang diem quan an thuoc atm ngan
""".split())

MIN_NAME_SCORE = 0.5          # dưới ngưỡng này thì không nhắc tới, kể cả kiểu "gần giống"


def haversine_km(lat1, lng1, lat2, lng2):
    """Khoảng cách vòng lớn giữa hai toạ độ, km."""
    r = 6371.0
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2)
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def tokens(text):
    """Chuỗi -> danh sách token đã bỏ dấu, bỏ ký tự lạ, bỏ token 1 ký tự."""
    cleaned = "".join(c if c.isalnum() else " " for c in strip_accents((text or "").lower()))
    return [t for t in cleaned.split() if len(t) > 1 or t.isdigit()]


def name_score(want, got):
    """So tên NGƯỜI DÙNG HỎI với tên TRẢ VỀ -> (điểm, token đặc trưng còn thiếu, khớp đủ?).

    Chấm trên token ĐẶC TRƯNG (đã bỏ từ chỉ loại). Nếu tính cả từ chung chung thì
    "Nhà sách Nguyễn Văn Cừ" đạt 0,83 so với "Nhà sách Fahasa Nguyễn Văn Cừ" — vượt
    ngưỡng dù là chuỗi khác hẳn.
    Truy vấn gồm TOÀN từ chung ("nhà sách") -> lùi về chấm trên mọi token.
    """
    want_all = tokens(want)
    if not want_all:
        return 1.0, [], True
    distinctive = [t for t in want_all if t not in GENERIC_TOKENS]
    base = distinctive or want_all
    got_set = set(tokens(got))
    missing = [t for t in base if t not in got_set]
    score = (len(base) - len(missing)) / len(base)
    return round(score, 2), missing, not missing


def apply_policy(page_outcome, items, center=None, radius_km=0.0,
                 match_name=None, min_name_score=MIN_NAME_SCORE):
    """Dữ liệu THÔ + ràng buộc -> (outcome, kết quả, chẩn đoán). Hàm THUẦN.

    `radius_km <= 0` = không ràng buộc khoảng cách (ý định 'đúng chỗ này').
    `match_name`     = bật kiểm chứng theo tên (ý định 'đúng chỗ này').
    """
    diag = {"parsed": len(items), "filtered_out": 0, "nearest_km": None,
            "exact": 0, "approx": 0, "best_name_score": None}

    if page_outcome == "EMPTY":
        return "NO_RESULTS", [], diag
    if page_outcome != "RAW":
        return page_outcome, [], diag          # BLOCKED / SCRAPE_FAILED / ... giữ nguyên
    if not items:
        return "PARSER_ERROR", [], diag

    # Bóc đặc trưng NGAY khi vào chính sách: mọi tầng sau (lọc cứng, chấm điểm, giải
    # thích) đều làm việc trên cùng một hình dạng dữ liệu.
    rows = [extract_features(it) for it in items]

    # Khoảng cách: tính cho MỌI mục (kể cả khi không lọc) để nói được "cách bạn N km".
    if center:
        for r in rows:
            r["distance_km"] = round(haversine_km(center[0], center[1], r["lat"], r["lng"]), 2)
        diag["nearest_km"] = min(r["distance_km"] for r in rows)

    # Kiểm chứng TÊN trước: sai chỗ thì gần hay xa cũng vô nghĩa.
    if match_name:
        for r in rows:
            sc, missing, exact = name_score(match_name, r["name"])
            r["name_score"], r["name_missing"] = sc, missing
            r["match"] = "exact" if exact else "approx"
        diag["best_name_score"] = max(r["name_score"] for r in rows)
        rows = [r for r in rows if r["name_score"] >= min_name_score]
        if not rows:
            return "NO_RESULTS", [], diag
        exact_rows = [r for r in rows if r["match"] == "exact"]
        diag["exact"], diag["approx"] = len(exact_rows), len(rows) - len(exact_rows)
        if not exact_rows:
            # Có chỗ tên gần giống nhưng KHÔNG đúng cái được hỏi -> phải nói rõ, không nhận vơ.
            return "APPROX_MATCH", rows, diag
        rows = exact_rows

    # Khoảng cách chỉ RÀNG BUỘC khi người dùng đã nêu ràng buộc.
    if center and radius_km and radius_km > 0:
        keep = [r for r in rows if r["distance_km"] <= radius_km]
        diag["filtered_out"] = len(rows) - len(keep)
        if not keep:
            return "OUT_OF_AREA", [], diag
        rows = keep

    rows.sort(key=lambda r: (r.get("distance_km") if r.get("distance_km") is not None else 0))
    return "OK", rows, diag


# ======================== NGUỒN DỮ LIỆU ========================
# Hai nguồn dùng CHUNG một giao diện (page_outcome, items, diag) để việc đổi nguồn khi
# phải từ bỏ Maps là sửa cấu hình, không phải viết lại tính năng.

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_UA = "AI-Assistant/1.0 (personal assistant; contact via local user)"

# Loại địa điểm tiếng Việt -> thẻ OSM. OSM phủ POI quán xá VN khá thưa, nên đây là
# nguồn DỰ PHÒNG: tốt cho hạ tầng (ATM, cây xăng, bệnh viện), yếu cho quán ăn.
_OSM_TAGS = {
    "quan an": ['["amenity"="restaurant"]', '["amenity"="fast_food"]'],
    "nha hang": ['["amenity"="restaurant"]'],
    "ca phe": ['["amenity"="cafe"]'],
    "cafe": ['["amenity"="cafe"]'],
    "atm": ['["amenity"="atm"]'],
    "ngan hang": ['["amenity"="bank"]'],
    "hieu thuoc": ['["amenity"="pharmacy"]'],
    "nha thuoc": ['["amenity"="pharmacy"]'],
    "sieu thi": ['["shop"="supermarket"]', '["shop"="convenience"]'],
    "cay xang": ['["amenity"="fuel"]'],
    "benh vien": ['["amenity"="hospital"]'],
    "phong kham": ['["amenity"="clinic"]', '["amenity"="doctors"]'],
    "nha sach": ['["shop"="books"]'],
    "sua xe": ['["shop"="motorcycle_repair"]', '["shop"="car_repair"]'],
    "gym": ['["leisure"="fitness_centre"]'],
}


def osm_filters(query):
    """Truy vấn tiếng Việt -> danh sách bộ lọc OSM. Không khớp loại nào -> tìm theo TÊN."""
    q = " ".join(tokens(query))
    for key, filters in _OSM_TAGS.items():
        if key in q:
            return filters
    safe = q.replace('"', "").replace("\\", "")
    return [f'["name"~"{safe}",i]'] if safe else []


def build_overpass_query(query, lat, lng, radius_m, limit=20):
    """Dựng câu Overpass QL. Hàm THUẦN để test không cần mạng."""
    filters = osm_filters(query)
    if not filters:
        return None
    parts = []
    for f in filters:
        for kind in ("node", "way"):
            parts.append(f'{kind}{f}(around:{int(radius_m)},{lat},{lng});')
    return ("[out:json][timeout:20];(" + "".join(parts) + f");out center {int(limit)};")


def parse_overpass(data):
    """JSON Overpass -> (page_outcome, items, diag). Bỏ mục không tên/không toạ độ."""
    if not isinstance(data, dict):
        return "SOURCE_UNAVAILABLE", [], {"badPayload": True}
    elements = data.get("elements")
    if elements is None:
        return "SOURCE_UNAVAILABLE", [], {"badPayload": True}
    items = []
    for e in elements:
        tags = e.get("tags") or {}
        name = (tags.get("name") or "").strip()
        lat = e.get("lat") if e.get("lat") is not None else (e.get("center") or {}).get("lat")
        lng = e.get("lon") if e.get("lon") is not None else (e.get("center") or {}).get("lon")
        if not name or lat is None or lng is None:
            continue
        addr = " ".join(x for x in (tags.get("addr:housenumber"), tags.get("addr:street")) if x)
        items.append({"name": name, "url": f"https://www.openstreetmap.org/{e.get('type')}/{e.get('id')}",
                      "lat": float(lat), "lng": float(lng), "rating": None,
                      "address": addr or None})
    if not items:
        return "EMPTY", [], {"elements": len(elements)}
    return "RAW", items, {"elements": len(elements)}


# Mã KHÔNG cần thử nguồn dự phòng: OK là xong; APPROX_MATCH đã có thứ để nói với người
# dùng, và OSM phủ POI VN thưa nên gần như không cứu được gì.
_NO_FALLBACK = ("OK", "APPROX_MATCH")
_OSM_WIDE_KM = 50.0
# Điểm neo khi CHƯA biết người dùng ở đâu — chỉ để Maps có tâm mà tra, KHÔNG phải
# câu trả lời. Kết quả vẫn phải qua kiểm chứng TÊN.
_VN_ANCHOR = (16.0, 108.0)          # bán kính TRUY VẤN khi không có ràng buộc (khác ràng buộc)


class PlacesService:
    """Tra địa điểm qua nguồn chính + nguồn dự phòng, rồi áp chính sách kiểm chứng.

    TÂM BẢN ĐỒ và RÀNG BUỘC là hai thứ KHÁC NHAU: tâm quyết định tìm ở đâu (Maps bắt
    buộc phải có, thiếu là rơi vào 'limited view'); ràng buộc quyết định kết quả nào
    được chấp nhận. Hỏi "X ở đâu" vẫn cần tâm để tra, nhưng KHÔNG có ràng buộc.
    """

    def __init__(self, bridge=None, source="maps", radius_km=5.0, area_radius_km=10.0,
                 limit=8, http_get=None, geocoder=None, timeout=45, weights=None):
        self.bridge = bridge
        self.source = (source or "maps").strip().lower()
        self.radius_km = float(radius_km)
        self.area_radius_km = float(area_radius_km)
        self.limit = int(limit)        # số chỗ GIỮ lại cho "mở cái thứ N"
        self._http_get = http_get
        self._geocoder = geocoder
        self.timeout = timeout
        self.weights = weights          # None -> DEFAULT_WEIGHTS trong place_ranking

    # ---------- HTTP ----------
    def _fetch(self, url, params):
        """Một quy ước DUY NHẤT cho mọi lệnh HTTP của module: `http_get(url, params)`.

        Trước đây phần geocode mượn `weather._get` (nhận URL đã ghép sẵn) còn Overpass gọi
        (url, params) — cùng một chỗ tiêm mà hai cách gọi, nên bản giả trong test im lặng
        trả về sai. Gom về một quy ước để không tái diễn.
        """
        if self._http_get is not None:
            return self._http_get(url, params)
        import requests
        return requests.get(url, params=params, timeout=25, headers={"User-Agent": _UA})

    # ---------- nguồn ----------
    def _read_maps(self, query, center, limit, radius_km=None):
        from services import browser_protocol as bp
        if self.bridge is None or not getattr(self.bridge, "connected", False):
            return "SOURCE_UNAVAILABLE", [], {"reason": "bridge chưa kết nối"}
        # Bán kính quyết định ZOOM: khung nhìn khớp ràng buộc thì 6 chỗ Maps trả về là 6 chỗ
        # GẦN, thay vì 6 chỗ rải rác.
        payload = bp.build_maps_read(query, center[0], center[1], limit=max(limit, 10),
                                     radius_km=radius_km)
        payload.pop("action", None)
        resp = self.bridge.send_command("MAPS_READ", timeout=self.timeout, **payload)
        return bp.parse_maps_response(resp)

    def _read_osm(self, query, center, radius_km, limit):
        ql = build_overpass_query(query, center[0], center[1],
                                  max(float(radius_km), 1.0) * 1000, limit=max(limit, 20))
        if not ql:
            return "EMPTY", [], {"reason": "không dựng được truy vấn OSM"}
        try:
            return parse_overpass(self._fetch(_OVERPASS_URL, {"data": ql}).json())
        except Exception as e:
            logger.warning("places: Overpass lỗi: %s", e)
            return "SOURCE_UNAVAILABLE", [], {"error": str(e)}

    def _read(self, source, query, center, radius_km, limit):
        if source == "osm":
            return self._read_osm(query, center, radius_km or _OSM_WIDE_KM, limit)
        return self._read_maps(query, center, limit, radius_km=radius_km)

    # ---------- geocode ----------
    def _gazetteer(self, name):
        """Tra danh bạ địa danh (Open-Meteo). Thử CẢ hai biến thể có dấu / bỏ dấu rồi chọn
        theo độ KHỚP TÊN.

        Không thể đoán trước biến thể nào đúng: "Thủ Đức" chỉ ra kết quả khi CÓ dấu, còn
        "Đà Lạt" có dấu lại ra nhầm "Đã Tịch" — nên tra cả hai rồi xếp hạng, thay vì chọn
        cứng một hướng — tên có tiền tố hành chính ('Thủ Đức' vs 'phường Thủ Đức') hỏng theo
        cả hai chiều.
        """
        variants, seen = [], set()
        for v in (str(name).strip(), strip_accents(str(name).strip())):
            if v and v not in seen:
                seen.add(v)
                variants.append(v)

        best, best_score = None, 0.0
        for v in variants:
            params = {"name": v, "count": 5, "language": "vi", "format": "json"}
            try:
                resp = self._fetch(_GEOCODE_URL, params)
                hits = (resp.json() or {}).get("results") or []
            except Exception as e:
                logger.warning("places: geocode '%s' lỗi: %s", v, e)
                continue
            for hit in hits:
                score, _, _ = name_score(name, hit.get("name") or "")
                if score > best_score:
                    best, best_score = hit, score
        if best is None or best_score < 0.5:
            return None
        return (best.get("latitude"), best.get("longitude"), best.get("name") or str(name))

    def _landmark_via_maps(self, name, origin=None):
        """Danh bạ không có (toà nhà, khu đô thị, POI) -> hỏi chính Maps.

        Maps biết POI mà danh bạ hành chính không có ('Vinhomes Grand Park'). Vẫn kiểm
        chứng bằng TÊN để không nhận nhầm một chỗ khác.
        """
        if self.bridge is None or not getattr(self.bridge, "connected", False):
            return None
        anchor = origin or _VN_ANCHOR
        page, items, _ = self._read_maps(name, anchor, 5)
        outcome, rows, _ = apply_policy(page, items, anchor, 0.0, match_name=name)
        if outcome not in ("OK", "APPROX_MATCH") or not rows:
            return None
        top = rows[0]
        return (top["lat"], top["lng"], top["name"])

    def resolve_area(self, name, origin=None):
        """Tên khu vực/địa danh -> (lat, lng, tên hiển thị) hoặc None."""
        if not name or not str(name).strip():
            return None
        if self._geocoder is not None:                 # tiêm để test
            hit = self._geocoder(str(name).strip())
            if hit:
                return (hit.get("latitude"), hit.get("longitude"),
                        hit.get("name") or str(name))
            return None
        return self._gazetteer(name) or self._landmark_via_maps(name, origin)

    # ---------- ý định ----------
    def _rank_ctx(self, query, radius_km, rows):
        """Ngữ cảnh xếp hạng — ý định lấy từ CHÍNH câu người dùng, không bịa thêm."""
        import datetime as _dt
        crowd_words = ("khong dong", "vang", "it nguoi", "dong khach", "dong duc")
        low = strip_accents((query or "").lower())
        distances = [r["distance_km"] for r in rows if r.get("distance_km") is not None]
        return {"radius_km": radius_km, "now": _dt.datetime.now(),
                "intent_keys": intent_keys(query), "weights": self.weights,
                "asked_about_crowd": any(w in low for w in crowd_words),
                "nearest_km": min(distances) if distances else None}

    def _lookup(self, query, center, radius_km, match_name=None):
        """Chạy nguồn chính, áp chính sách; không OK thì thử nguồn dự phòng."""
        limit = self.limit
        primary = self.source if self.source in ("maps", "osm") else "maps"
        page, items, pdiag = self._read(primary, query, center, radius_km, limit)
        outcome, rows, diag = apply_policy(page, items, center, radius_km, match_name)
        ctx = self._rank_ctx(query, radius_km, rows)
        if outcome == "OK":
            rows = rank(rows, ctx)
        diag.update({"page": page, "source": primary, "page_diag": pdiag, "rank_ctx": ctx})
        if outcome in _NO_FALLBACK or primary == "osm":
            return {"outcome": outcome, "results": rows[:limit], "diagnostics": diag,
                    "source": primary}

        page2, items2, pdiag2 = self._read("osm", query, center, radius_km, limit)
        outcome2, rows2, diag2 = apply_policy(page2, items2, center, radius_km, match_name)
        if outcome2 == "OK":
            rows2 = rank(rows2, self._rank_ctx(query, radius_km, rows2))
        diag2.update({"page": page2, "source": "osm", "page_diag": pdiag2,
                      "fallback_from": outcome})
        if outcome2 == "OK":
            return {"outcome": outcome2, "results": rows2[:limit], "diagnostics": diag2,
                    "source": "osm"}
        # Dự phòng cũng không cứu được -> giữ kết luận của nguồn chính (đúng ngữ cảnh hơn).
        diag["fallback_tried"] = outcome2
        return {"outcome": outcome, "results": rows[:limit], "diagnostics": diag,
                "source": primary}

    # Khung nhìn hẹp cho kết quả GẦN hơn hẳn, nhưng vùng thưa có thể ra rỗng -> nới MỘT
    # lần rồi thôi. Mỗi lần tra tốn ~12 giây nên không nới nhiều bậc.
    WIDEN_FACTOR = 4.0
    WIDEN_MAX_KM = 15.0

    def find_nearby(self, query, center, radius_km=None):
        """Tìm theo LOẠI quanh một điểm. Bán kính là RÀNG BUỘC."""
        r = self.radius_km if radius_km is None else float(radius_km)
        r = max(r, 0.1)
        out = self._lookup(query, center, r)
        if out["outcome"] in ("OUT_OF_AREA", "NO_RESULTS") and r < self.WIDEN_MAX_KM:
            wider = min(self.WIDEN_MAX_KM, r * self.WIDEN_FACTOR)
            retry = self._lookup(query, center, wider)
            if retry["outcome"] == "OK":
                retry.setdefault("diagnostics", {})["widened_from_km"] = r
                return retry
        return out

    def find_place(self, name, origin=None, area=None):
        """Tìm ĐÚNG MỘT CHỖ có tên. Không nêu khu vực -> KHÔNG ràng buộc khoảng cách."""
        if area:
            spot = self.resolve_area(area)
            if not spot:
                return {"outcome": "NO_RESULTS", "results": [],
                        "diagnostics": {"unknown_area": area}, "source": None,
                        "area": area}
            center, radius = (spot[0], spot[1]), self.area_radius_km
            out = self._lookup(f"{name} {spot[2]}", center, radius, match_name=name)
            out["area"] = spot[2]
            return out
        if not origin:
            return {"outcome": "SOURCE_UNAVAILABLE", "results": [],
                    "diagnostics": {"reason": "chưa biết vị trí để tra"}, "source": None}
        out = self._lookup(name, origin, 0.0, match_name=name)   # 0 = không ràng buộc
        out["area"] = None
        return out
