"""
Xếp hạng địa điểm — TẤT ĐỊNH, thuần, không LLM.

Nguyên tắc kế thừa từ `weather._advice`: mọi thứ ĐỊNH LƯỢNG tính bằng code với ngưỡng
đọc được, LLM chỉ diễn đạt lại. Nhờ vậy thứ hạng test được và giải thích được, thay vì
phụ thuộc vào việc model hôm nay "cảm thấy" quán nào hay.

THIẾU DỮ LIỆU KHÁC VỚI KÉM: thành phần không có dữ liệu nhận điểm TRUNG TÍNH và cờ
`known=False`. Cho 0 sẽ đẩy mọi quán thiếu trường xuống đáy một cách vô lý; và cờ
`known` là thứ tầng giải thích dùng để biết cái gì được phép nói ra.
"""

from actions.place_features import minutes_until_close
from utils.text_norm import strip_accents

NEUTRAL = 0.5

# Ngưỡng lượt đánh giá cho trung bình Bayes. Càng lớn càng "nghi ngờ" quán ít lượt.
RATING_PRIOR_COUNT = 30

# Mốc kỳ vọng cho một quán CHƯA BIẾT GÌ.
#
# KHÔNG dùng trung bình của tập ứng viên làm prior — đó là mẫu ĐÃ BỊ CHỌN LỌC: Maps chỉ
# trả về những chỗ điểm cao, nên trung bình của nó ~4,8. Lấy nó làm prior nghĩa là mặc
# định "một quán lạ cũng tốt ngang quán tốt nhất", và khi đó bằng chứng mỏng KHÔNG bị
# phạt — một quán 5,0 với vài lượt vẫn đè quán 4,7 với hàng trăm lượt. Mốc thận trọng
# thấp hơn hẳn trung bình mẫu mới kéo được thứ hạng về đúng chiều.
RATING_PRIOR_MEAN = 4.2
_RATING_FLOOR, _RATING_CEIL = 3.0, 5.0     # dải rating thực tế trên Maps

DEFAULT_WEIGHTS = {"distance": 0.35, "quality": 0.35, "open": 0.20, "evidence": 0.10}

# Ý định -> từ khoá cần tìm trong TRÍCH ĐOẠN REVIEW. Heuristic, cần bộ test riêng.
INTENT_LEXICON = {
    "hoc_lam_viec": (("hoc bai", "hoc", "lam viec", "wifi", "o cam", "yen tinh", "laptop"),
                     ("hoc bai", "hoc", "lam viec", "ngoi lau", "wifi")),
    "yen_tinh": (("yen tinh", "chill", "thoang", "khong gian", "thu gian", "yen"),
                 ("yen tinh", "chill", "yen", "thu gian", "thoang")),
    "gia_re": (("re", "binh dan", "gia hop ly", "gia tot"),
               ("re", "binh dan", "gia hop ly", "gia tot")),
}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def bayesian_quality(rating, reviews, prior_mean, prior_count=RATING_PRIOR_COUNT):
    """Trung bình Bayes: `(v*R + m*C) / (v + m)`.

    BẮT BUỘC dùng thay rating thô — nếu không, một quán điểm tuyệt đối với vài lượt sẽ
    đè quán điểm thấp hơn chút mà có hàng trăm lượt.
    """
    if rating is None:
        return None
    v = reviews or 0
    m = max(1, int(prior_count))
    c = prior_mean if prior_mean is not None else RATING_PRIOR_MEAN
    return (v * rating + m * c) / (v + m)


def distance_score(distance_km, radius_km):
    """Càng gần càng cao. Không có ràng buộc bán kính -> lấy 5 km làm thước quy chiếu."""
    if distance_km is None:
        return NEUTRAL, False
    scale = radius_km if radius_km and radius_km > 0 else 5.0
    return _clamp(1.0 - (distance_km / scale)), True


def quality_score(place, prior_mean):
    if place.get("rating") is None:
        return NEUTRAL, False
    bayes = bayesian_quality(place["rating"], place.get("reviews"), prior_mean)
    span = _RATING_CEIL - _RATING_FLOOR
    return _clamp((bayes - _RATING_FLOOR) / span), True


def open_score(place, now):
    """Đang mở và còn mở lâu là tốt; sắp đóng cửa bị phạt nặng.

    Đây KHÔNG phải ràng buộc do người dùng nêu — nó là lẽ thường: gợi ý một quán còn mở
    10 phút nữa thì gợi ý đó vô dụng. Không biết giờ -> trung tính, không đoán.
    """
    opening = place.get("opening") or {}
    state = opening.get("state")
    if state == "open_24h":
        return 1.0, True
    if state == "closed":
        return 0.0, True
    if state in ("open", "closing_soon"):
        left = minutes_until_close(opening, now)
        if left is None:
            return (0.3, True) if state == "closing_soon" else (0.8, True)
        if left <= 30:
            return 0.15, True
        if left <= 60:
            return 0.6, True
        return 1.0, True
    return NEUTRAL, False


def intent_keys(text):
    """Câu người dùng -> các nhóm ý định cần tìm bằng chứng."""
    low = strip_accents((text or "").lower())
    keys = []
    for name, (triggers, _) in INTENT_LEXICON.items():
        if any(t in low for t in triggers):
            keys.append(name)
    return keys


def evidence_score(place, wanted_keys):
    """Trích đoạn review có khớp ý định không.

    Không có trích đoạn -> TRUNG TÍNH, không phải 0: im lặng khác với không phù hợp.
    """
    if not wanted_keys:
        return NEUTRAL, False
    quote = place.get("quote")
    if not quote:
        return NEUTRAL, False
    low = strip_accents(quote.lower())
    hits = sum(1 for k in wanted_keys
               if any(w in low for w in INTENT_LEXICON[k][1]))
    return _clamp(hits / len(wanted_keys)), True


def score_place(place, ctx):
    """-> {'total': float, 'components': {tên: {'score','known','weight'}}}. Hàm THUẦN."""
    weights = ctx.get("weights") or DEFAULT_WEIGHTS
    parts = {
        "distance": distance_score(place.get("distance_km"), ctx.get("radius_km")),
        "quality": quality_score(place, ctx.get("prior_mean")),
        "open": open_score(place, ctx.get("now")),
        "evidence": evidence_score(place, ctx.get("intent_keys") or []),
    }
    components, total, wsum = {}, 0.0, 0.0
    for name, (value, known) in parts.items():
        w = float(weights.get(name, 0.0))
        components[name] = {"score": round(value, 3), "known": known, "weight": w}
        total += value * w
        wsum += w
    return {"total": round(total / wsum, 4) if wsum else 0.0, "components": components}


def rank(places, ctx=None):
    """Chấm điểm và sắp xếp giảm dần. Trả BẢN SAO, không sửa đầu vào."""
    ctx = dict(ctx or {})
    ctx.setdefault("prior_mean", RATING_PRIOR_MEAN)
    out = []
    for p in places:
        row = dict(p)
        row["ranking"] = score_place(row, ctx)
        out.append(row)
    out.sort(key=lambda r: (-r["ranking"]["total"],
                            r.get("distance_km") if r.get("distance_km") is not None else 0))
    return out
