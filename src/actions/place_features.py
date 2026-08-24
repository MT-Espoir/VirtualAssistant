"""
Bóc ĐẶC TRƯNG của một địa điểm từ các dòng text thô trên thẻ kết quả Maps.

Vì sao parser nằm ở Python chứ không ở extension: mỗi lần sửa parser trong extension là
một lần người dùng phải RELOAD extension thủ công. Để JS chỉ gửi dòng thô, ta sửa cách
hiểu dữ liệu mà không cần đụng trình duyệt — và test được không cần Chrome.

Hình dạng dòng thô mà thẻ kết quả cho:
    "Oleoleo Coffee & Cats"
    "4,8(646) · 1-100.000 ₫"
    "Quán cà phê ·  · 5t2 Ngõ 62 Nguyễn Chí Thanh"
    "Đang mở cửa · Đóng cửa vào 22:30"
    '"Đồ uống ngon'
    'Quán có những trò chơi cho ae solo cùng bạn bè."'
aria-label: "4,8 sao 646 bài đánh giá", "1 ₫ – 100.000 ₫", "Lối vào cho xe lăn"

LƯU Ý: các chuỗi này phụ thuộc NGÔN NGỮ. Ta ép `hl=vi` khi mở Maps nên chúng ổn định,
nhưng đây vẫn là điểm dễ vỡ — mọi hàm ở đây phải suy biến an toàn về None/'unknown'.
"""

import re

from utils.text_norm import strip_accents

# --- rating: "4,8(646)" hoặc aria "4,8 sao 646 bài đánh giá" ---
_RATING_LINE = re.compile(r"^(\d[.,]\d)\s*\((\d[\d.,]*)\)")
_RATING_ARIA = re.compile(r"(\d[.,]\d)\D+(\d[\d.,]*)")

# --- giá: "1-100.000 ₫", "1 ₫ – 100.000 ₫", "100.000-200.000₫" ---
_PRICE = re.compile(r"(\d[\d.]*)\s*(?:₫|đ)?\s*[-–—]\s*(\d[\d.]*)\s*(?:₫|đ)")

# --- giờ: bắt "22:30", "7:00" ---
_TIME = re.compile(r"(\d{1,2}):(\d{2})")

_OPEN_24H = ("mo ca ngay", "24 gio", "mo 24")
_CLOSING_SOON = ("sap dong cua",)
_CLOSED = ("da dong cua", "dong cua vinh vien", "tam thoi dong cua")
_OPEN = ("dang mo cua", "mo cua")


def _num(text):
    """'100.000' / '1,970' -> int. Bỏ mọi dấu phân cách nghìn."""
    try:
        return int(re.sub(r"[.,\s]", "", text))
    except (TypeError, ValueError):
        return None


def parse_rating(lines, aria=None):
    """-> (rating float|None, số lượt đánh giá int|None)."""
    for line in lines or []:
        m = _RATING_LINE.match(line.strip())
        if m:
            return float(m.group(1).replace(",", ".")), _num(m.group(2))
    for label in aria or []:
        low = strip_accents(label).lower()
        if "sao" in low or "star" in low:
            m = _RATING_ARIA.search(label)
            if m:
                return float(m.group(1).replace(",", ".")), _num(m.group(2))
    return None, None


def parse_price(lines, aria=None):
    """Dải giá -> {'min','max','raw'} hoặc None. Thỉnh thoảng Maps không có trường này."""
    for text in list(lines or []) + list(aria or []):
        m = _PRICE.search(text)
        if not m:
            continue
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if lo is None or hi is None or hi < lo:
            continue
        return {"min": lo, "max": hi, "raw": m.group(0).strip()}
    return None


def parse_category_address(lines):
    """Dòng dạng 'Quán cà phê ·  · 5t2 Ngõ 62...' -> ('Quán cà phê', '5t2 Ngõ 62...').

    Địa chỉ là BEST-EFFORT: có thẻ đặt câu mô tả vào đúng chỗ này thay vì địa chỉ.
    """
    for line in lines or []:
        if "·" not in line:
            continue
        if _RATING_LINE.match(line.strip()):        # dòng rating cũng chứa '·'
            continue
        low = strip_accents(line).lower()
        if any(k in low for k in _CLOSING_SOON + _CLOSED + _OPEN + _OPEN_24H):
            continue                                 # dòng giờ mở cửa
        parts = [p.strip() for p in line.split("·") if p.strip()]
        if not parts:
            continue
        category = parts[0]
        address = parts[-1] if len(parts) > 1 else None
        return category, address
    return None, None


def parse_opening(lines):
    """Dòng giờ mở cửa -> {state, closes_at, opens_at, raw}.

    state: open_24h | open | closing_soon | closed | unknown

    Thứ tự kiểm tra QUAN TRỌNG: 'Sắp đóng cửa' và 'Đã đóng cửa' đều chứa 'đóng cửa',
    'Đang mở cửa' chứa 'mở cửa' — kiểm cụm dài trước, nếu không sẽ phân loại nhầm hết.

    Ví dụ thật:
        "Mở cả ngày"                                  -> open_24h
        "Đang mở cửa · Đóng cửa vào 22:30"            -> open,         closes 22:30
        "Sắp đóng cửa · 22:00 · Mở cửa lúc 6:30 Thứ 7" -> closing_soon, closes 22:00, opens 6:30
        "Đã đóng cửa · Mở cửa lúc 7:00 Thứ 7"         -> closed,       opens 7:00
    """
    for line in lines or []:
        low = strip_accents(line).lower()
        if not any(k in low for k in ("mo cua", "dong cua", "mo ca ngay", "24 gio")):
            continue

        out = {"state": "unknown", "closes_at": None, "opens_at": None, "raw": line.strip()}
        if any(k in low for k in _OPEN_24H):
            out["state"] = "open_24h"
            return out

        segments = [s.strip() for s in line.split("·") if s.strip()]
        for seg in segments:
            seg_low = strip_accents(seg).lower()
            t = _TIME.search(seg)
            time_val = (int(t.group(1)), int(t.group(2))) if t else None

            if "sap dong cua" in seg_low:
                out["state"] = "closing_soon"
                if time_val:
                    out["closes_at"] = time_val
            elif any(k in seg_low for k in _CLOSED):
                out["state"] = "closed"
            elif "dang mo cua" in seg_low:
                if out["state"] == "unknown":
                    out["state"] = "open"
            elif "dong cua" in seg_low and time_val:
                out["closes_at"] = time_val
                if out["state"] == "unknown":
                    out["state"] = "open"
            elif "mo cua" in seg_low and time_val:
                out["opens_at"] = time_val
            elif time_val and out["state"] == "closing_soon" and out["closes_at"] is None:
                out["closes_at"] = time_val          # "Sắp đóng cửa · 22:00"
        return out
    return {"state": "unknown", "closes_at": None, "opens_at": None, "raw": None}


def minutes_until_close(opening, now):
    """Số phút còn lại tới giờ đóng cửa; None nếu không biết hoặc mở cả ngày.

    Qua nửa đêm (đóng lúc 00:30) thì tính sang ngày hôm sau thay vì ra số âm.
    """
    if not opening or opening.get("state") == "open_24h":
        return None
    closes = opening.get("closes_at")
    if not closes or now is None:
        return None
    minutes = (closes[0] * 60 + closes[1]) - (now.hour * 60 + now.minute)
    if minutes < -120:            # đóng cách đây hơn 2 tiếng -> hiểu là mốc của ngày mai
        minutes += 24 * 60
    return minutes


def parse_quote(lines):
    """Trích đoạn review trên thẻ (nếu có) -> chuỗi, hoặc None.

    Đây là BẰNG CHỨNG DUY NHẤT cho các thuộc tính mềm (yên tĩnh, hợp học bài): không có
    nó thì không được nhắc tới thuộc tính mềm.
    """
    buf = []
    for line in lines or []:
        text = line.strip()
        if not text:
            continue
        if '"' in text or "\u201c" in text or "\u201d" in text:
            buf.append(text.strip('"\u201c\u201d').strip())
        elif buf:
            buf.append(text)
    quote = " ".join(x for x in buf if x).strip()
    return quote or None


def extract_features(item):
    """Mục thô từ extension -> mục kèm đặc trưng. Không ném lỗi: thiếu gì thì để None."""
    lines = item.get("lines") or []
    aria = item.get("aria") or []
    rating, reviews = parse_rating(lines, aria)
    category, address = parse_category_address(lines)
    out = dict(item)
    out.update({
        "rating": rating if rating is not None else item.get("rating"),
        "reviews": reviews,
        "category": category,
        "address": address or item.get("address"),
        "price": parse_price(lines, aria),
        "opening": parse_opening(lines),
        "quote": parse_quote(lines),
        "wheelchair": any("xe lan" in strip_accents(a).lower() and
                          "khong co" not in strip_accents(a).lower() for a in aria),
    })
    out.pop("lines", None)
    out.pop("aria", None)
    return out
