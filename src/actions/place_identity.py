"""
DANH TÍNH địa điểm — khoá gộp bằng chứng (L3-2, `docs/research_lane_spec.md` §9).

Đây là phần RIÊNG của miền địa điểm; lõi `research/` không được biết gì về nó.

Vì sao phải có TRƯỚC khi thu thập bằng chứng: web cho **tên**, không cho toạ độ. Blog
viết "Cà phê Cộng — 152 Triệu Việt Vương", Maps có "Cộng Cà Phê Triệu Việt Vương". Không
nối được hai thứ đó thì nhận định thẩm mỹ gắn vào một cái tên không dẫn đường tới được.

Và có HAI tầng, không phải một:

    Nhận định thẩm mỹ  đúng ở cấp THƯƠNG HIỆU  (Cộng chi nhánh nào cũng bao cấp)
    Khoảng cách        chỉ đúng ở cấp CHI NHÁNH

Lưu phẳng là sai: sẽ phải research lại từng chi nhánh cho một nhận định chỉ cần biết một
lần.

DRY: mọi thứ về so tên và khoảng cách lấy từ `actions/places.py`. Bài học đắt nhất của
S2 (phụ lục `smart_places_spec.md`) là để HAI đường giải địa danh tồn tại song song —
cùng một chuỗi cho hai kết quả khác nhau. Không lặp lại ở đây.
"""

from actions.places import GENERIC_TOKENS, haversine_km, name_score, tokens

# Lưới toạ độ ~20 m. Cùng con số với đề xuất khử trùng ở `smart_places_spec` §11.
COORD_PRECISION_M = 20.0
_M_PER_DEG_LAT = 111_320.0

# Ngưỡng coi hai bản ghi là CÙNG một chỗ.
SAME_PLACE_KM = 0.05          # 50 m — trong một toà nhà
SAME_PLACE_NAME_SCORE = 0.6

# Dấu hiệu TƯỜNG MINH của phần chi nhánh trong tên. Chỉ cắt khi thấy các dấu hiệu này —
# xem ghi chú giới hạn ở `brand_key`.
_BRANCH_MARKERS = ("chi nhanh", "cn ", "co so", "so ", "quan ", "chinhanh")
_BRANCH_SEPARATORS = ("–", "—", " - ", "|", "(", "@", ":", ",")


def coord_cell(lat, lng, meters=COORD_PRECISION_M):
    """(lat, lng) -> ô lưới nguyên (i, j) cạnh ~`meters`. None nếu thiếu toạ độ.

    Kinh độ co lại theo vĩ độ nên bước kinh độ phải chia cho cos(lat); dùng chung một
    bước cho cả hai sẽ cho ô dẹt ~10 m ở vĩ độ Việt Nam.
    """
    if lat is None or lng is None:
        return None
    import math
    lat, lng = float(lat), float(lng)
    step_lat = meters / _M_PER_DEG_LAT
    step_lng = meters / max(1.0, _M_PER_DEG_LAT * math.cos(math.radians(lat)))
    return (int(round(lat / step_lat)), int(round(lng / step_lng)))


def normalize_name(name):
    """Tên -> chuỗi khoá đã bỏ dấu, bỏ từ chỉ LOẠI. Rỗng nếu toàn từ chung chung.

    Bỏ từ chỉ loại vì "Quán cà phê Trill" và "Trill Bistro" phải cùng một khoá — dùng
    đúng `GENERIC_TOKENS` mà `name_score` đang dùng, không định nghĩa lại danh sách.
    """
    distinctive = [t for t in tokens(name) if t not in GENERIC_TOKENS]
    return " ".join(distinctive)


def brand_key(name):
    """Tên -> khoá THƯƠNG HIỆU (best-effort). Rỗng nếu không rút được gì.

    GIỚI HẠN ĐÃ BIẾT — đọc trước khi tin vào kết quả:

    Chỉ cắt được phần chi nhánh khi tên có dấu hiệu TƯỜNG MINH ("chi nhánh", "cơ sở",
    dấu gạch, ngoặc). Dạng "<Thương hiệu> <Tên đường>" viết liền không dấu hiệu gì —
    ví dụ "Cộng Cà Phê Triệu Việt Vương" — thì KHÔNG tách được bằng chuỗi, và hàm này
    trả về cả cụm.

    Không cố đoán thêm là CÓ CHỦ ĐÍCH: đoán sai sẽ gộp nhầm hai quán khác nhau và mọi
    bằng chứng sau đó dính vào sai chỗ — hỏng im lặng, đúng loại lỗi tệ nhất mà Phase 0
    đã dạy. Danh tính chuỗi đáng tin phải đến từ dữ liệu nhà cung cấp (trường chain/brand),
    không phải từ việc bổ chuỗi. Xem `research_lane_spec.md` §14.
    """
    text = (name or "").strip()
    if not text:
        return ""
    low = " " + " ".join(tokens(text)) + " "
    cut = len(text)
    for sep in _BRANCH_SEPARATORS:                 # cắt ở dấu ngăn đầu tiên
        i = text.find(sep)
        if 0 < i < cut:
            cut = i
    head = text[:cut].strip() or text
    for marker in _BRANCH_MARKERS:                 # có từ khoá chi nhánh -> cắt trước nó
        j = low.find(" " + marker.strip() + " ")
        if j > 0:
            head_tokens = low[:j].split()
            if head_tokens:
                return " ".join(t for t in head_tokens if t not in GENERIC_TOKENS)
    return normalize_name(head)


def canonical_id(name, lat=None, lng=None):
    """Khoá gộp cho MỘT CHI NHÁNH: tên chuẩn hoá + ô lưới ~20 m.

    Thiếu toạ độ -> chỉ theo tên; kém tin cậy hơn nên gọi ra là `name:` để tầng trên
    biết mà không trộn lẫn với khoá đầy đủ.
    """
    key = normalize_name(name)
    cell = coord_cell(lat, lng)
    if cell is None:
        return "name:" + key if key else ""
    return "geo:%s@%d,%d" % (key, cell[0], cell[1])


def same_place(a, b, max_km=SAME_PLACE_KM, min_name_score=SAME_PLACE_NAME_SCORE):
    """Hai bản ghi {name, lat, lng} có phải cùng một chỗ không.

    KHÔNG so khoá lưới bằng `==`: hai điểm cách nhau 1 m vẫn có thể rơi vào hai ô nếu
    nằm sát mép. Lưới chỉ để CHIA RỔ cho nhanh; kết luận thì dùng khoảng cách thật cộng
    độ khớp tên — đúng cặp tiêu chí mà `apply_policy` đã dùng.
    """
    if not a or not b:
        return False
    score, _, _ = name_score(a.get("name") or "", b.get("name") or "")
    if score < min_name_score:
        return False
    lat1, lng1, lat2, lng2 = a.get("lat"), a.get("lng"), b.get("lat"), b.get("lng")
    if None in (lat1, lng1, lat2, lng2):
        return score >= 1.0            # không có toạ độ -> chỉ nhận khi tên khớp HOÀN TOÀN
    return haversine_km(lat1, lng1, lat2, lng2) <= max_km


def merge_duplicates(rows):
    """Danh sách {name, lat, lng, ...} -> danh sách đã gộp trùng, giữ thứ tự xuất hiện.

    Bản ghi đầu tiên của mỗi nhóm được giữ; các tên khác gom vào `aliases` để tra ngược
    được về nguồn đã dùng tên nào.
    """
    out = []
    for row in rows or []:
        for kept in out:
            if same_place(kept, row):
                alias = (row.get("name") or "").strip()
                if alias and alias != kept.get("name"):
                    kept.setdefault("aliases", [])
                    if alias not in kept["aliases"]:
                        kept["aliases"].append(alias)
                break
        else:
            item = dict(row)
            item.setdefault("canonical_id",
                            canonical_id(item.get("name"), item.get("lat"), item.get("lng")))
            item.setdefault("brand_key", brand_key(item.get("name")))
            out.append(item)
    return out
