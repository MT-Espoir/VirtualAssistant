"""
Tinh chỉnh kết quả tìm địa điểm theo NGỮ CẢNH lượt trước (F1.5 §10).

Bài toán thật gặp khi chạy (2026-08-21): người dùng hỏi "có chỗ nào mở muộn hơn không"
sau khi đã có 7 quán. Model biến "mở muộn" thành TỪ KHOÁ tìm kiếm và tra lại từ đầu —
Maps tra chữ "mở muộn" như văn bản thường, nên kết quả không hề được lọc theo giờ đóng
cửa. Trong khi đó hệ thống ĐÃ CÓ `closes_at` của cả 7 quán và hoàn toàn lọc được.

Nguyên tắc:
- Ràng buộc THU HẸP -> lọc/xếp lại trên ứng viên ĐÃ CÓ, trả lời trong ~1 giây.
- Ràng buộc MỞ RỘNG (xa hơn, đổi loại) -> phải tra lại, không bịa ra ứng viên mới.
- Lọc xong còn 0 chỗ -> NÓI THẲNG là không có, KHÔNG âm thầm tra lại bằng từ khoá khác
  rồi trình bày như thể đó là câu trả lời cho câu hỏi cũ.
"""

from actions.place_features import minutes_until_close
from actions.place_ranking import INTENT_LEXICON
from utils.text_norm import strip_accents

# Thu hẹp trên dữ liệu ĐÃ CÓ: chỉ những thuộc tính mà ta đã bóc được cho từng ứng viên.
NARROWING = ("open_later", "open_now", "cheaper", "better_rated", "quieter")

# Phải TRA LẠI (kèm hệ số nhân bán kính) — vì retrieval của Maps phụ thuộc KHUNG NHÌN.
#
# 'closer' nằm ở đây chứ KHÔNG phải ở NARROWING: đo thật 2026-08-21, cùng một tâm, bảng
# kết quả ở khung 5 km trả 7 chỗ cách 0,96-1,41 km và KHÔNG chỗ nào dưới 500 m; khung
# 1 km trả 6 chỗ cách 0,20-0,63 km — hai tập KHÔNG trùng nhau một cái tên. Lọc "nửa gần
# hơn" của tập cũ không thể tìm ra quán cách 200 m, vì nó chưa bao giờ được lấy về.
REQUERY = {"farther": 2.0, "closer": 0.4}
EXPANDING = tuple(REQUERY)
CHANGES = NARROWING + EXPANDING

_MIN_OPEN_MINUTES = 60      # "mở muộn hơn" = còn mở ít nhất 1 tiếng nữa


def needs_requery(change):
    return change in REQUERY


def radius_factor(change):
    """Hệ số nhân bán kính khi phải tra lại. 1.0 nếu không đổi."""
    return REQUERY.get(change, 1.0)


def _median(values):
    vals = sorted(values)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def _closing_minutes(row, now):
    opening = row.get("opening") or {}
    if opening.get("state") == "open_24h":
        return 10 ** 6                      # coi như mở vô hạn
    if opening.get("state") == "closed":
        return -1
    left = minutes_until_close(opening, now)
    return left if left is not None else None


def apply_refinement(rows, change, value=None, now=None, radius_km=None):
    """-> (danh sách giữ lại, meta).

    meta: {change, requery, dropped, unknown, note} — `note` là câu giải thích TRUNG THỰC
    về việc vì sao còn ít/không còn chỗ nào, dựng từ số liệu thật.
    """
    meta = {"change": change, "requery": needs_requery(change), "dropped": 0,
            "unknown": 0, "note": None}
    if change not in CHANGES:
        meta["note"] = f"Tôi chưa biết cách tinh chỉnh kiểu '{change}'."
        return list(rows), meta
    if meta["requery"]:
        return list(rows), meta

    kept, unknown = [], 0

    if change in ("open_later", "open_now"):
        threshold = _MIN_OPEN_MINUTES if change == "open_later" else 0
        if value:
            # value là giờ cụ thể ("23") -> yêu cầu đóng cửa KHÔNG SỚM HƠN mốc đó
            try:
                want_hour = int(str(value).split(":")[0])
            except (TypeError, ValueError):
                want_hour = None
            if want_hour is not None and now is not None:
                threshold = max(threshold, want_hour * 60 - (now.hour * 60 + now.minute))
        for r in rows:
            left = _closing_minutes(r, now)
            if left is None:
                unknown += 1               # không biết giờ -> không dám khẳng định
                continue
            if left >= threshold:
                kept.append(r)
        kept.sort(key=lambda r: -(_closing_minutes(r, now) or 0))

    elif change == "cheaper":
        known = [r["price"]["max"] for r in rows if (r.get("price") or {}).get("max")]
        limit = _median(known)
        for r in rows:
            price = (r.get("price") or {}).get("max")
            if price is None:
                unknown += 1               # thiếu dữ liệu giá -> không suy ra là rẻ
            elif limit is None or price <= limit:
                kept.append(r)
        kept.sort(key=lambda r: (r.get("price") or {}).get("max") or 0)

    elif change == "better_rated":
        known = [r["rating"] for r in rows if r.get("rating") is not None]
        limit = float(value) if value else _median(known)
        for r in rows:
            if r.get("rating") is None:
                unknown += 1
            elif limit is None or r["rating"] >= limit:
                kept.append(r)
        kept.sort(key=lambda r: -(r.get("rating") or 0))

    elif change == "quieter":
        words = INTENT_LEXICON["yen_tinh"][1]
        for r in rows:
            quote = r.get("quote")
            if not quote:
                unknown += 1               # KHÔNG có bằng chứng -> không được coi là yên tĩnh
                continue
            if any(w in strip_accents(quote.lower()) for w in words):
                kept.append(r)

    meta["dropped"] = len(rows) - len(kept)
    meta["unknown"] = unknown
    meta["note"] = _note(change, kept, unknown, len(rows))
    return kept, meta


_LABEL = {
    "open_later": "mở muộn hơn", "open_now": "đang mở cửa", "closer": "gần hơn",
    "cheaper": "rẻ hơn", "better_rated": "được đánh giá cao hơn", "quieter": "yên tĩnh hơn",
}


def _note(change, kept, unknown, total):
    """Câu giải thích trung thực khi lọc xong — nêu cả số chỗ THIẾU DỮ LIỆU.

    Bỏ qua vì thiếu dữ liệu khác với loại vì không đạt; người dùng cần biết sự khác biệt
    đó để không hiểu nhầm 'không có' thành 'chắc chắn không có'.
    """
    label = _LABEL.get(change, change)
    if kept:
        if unknown:
            return (f"(Trong {total} chỗ vừa rồi, {unknown} chỗ tôi không có dữ liệu để "
                    f"so nên đã bỏ qua.)")
        return None
    if unknown >= total:
        return (f"Trong {total} chỗ vừa rồi tôi không có dữ liệu để biết chỗ nào {label}.")
    base = f"Trong {total} chỗ vừa rồi không có chỗ nào {label}."
    if unknown:
        base += f" ({unknown} chỗ tôi không có dữ liệu để so.)"
    return base
