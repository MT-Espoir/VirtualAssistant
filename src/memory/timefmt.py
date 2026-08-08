"""Mốc thời gian cho trí nhớ — các hàm THUẦN, test được.

Lý do tồn tại: trợ lý trước đây không hề biết "bây giờ" là lúc nào (system prompt không
có ngày giờ, cũng không có tool hỏi giờ) NÊN không thể phân biệt việc đã qua với việc
sắp tới. Kết quả: một ghi chú kiểu "Đang phỏng vấn với anh Nam" bị đóng băng vĩnh viễn
và trợ lý cứ nhắc như đang diễn ra. Các hàm ở đây cung cấp mốc "bây giờ" + cách mô tả
một sự kiện là đã qua hay chưa.
"""

from datetime import datetime, timedelta

# Sự kiện chỉ tính là ĐÃ QUA sau khi trôi thêm ngần này giờ — buổi phỏng vấn lúc 12h thì
# 12h05 vẫn đang diễn ra, đừng vội coi là xong.
DEFAULT_GRACE_HOURS = 2

_WEEKDAYS_VI = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật"]


def now_or(now=None):
    return now or datetime.now()


def parse_iso(value):
    """Chuỗi ISO -> datetime. None nếu rỗng/không đọc được (không ném lỗi)."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def format_now(now=None):
    """Câu mô tả thời điểm hiện tại để bơm vào system prompt.

    Vd: 'Bây giờ là 21:45 thứ Sáu, ngày 08/08/2026.'
    """
    dt = now_or(now)
    return (f"Bây giờ là {dt.strftime('%H:%M')} {_WEEKDAYS_VI[dt.weekday()]}, "
            f"ngày {dt.strftime('%d/%m/%Y')}.")


def is_past(event_time, now=None, grace_hours=DEFAULT_GRACE_HOURS):
    """Sự kiện đã qua chưa (có cộng thêm khoảng ân hạn). Không rõ thời điểm -> False.

    Không rõ mà trả False là chiều AN TOÀN: thà giữ lại một việc có thể đã xong còn hơn
    xoá nhầm một việc sắp tới.
    """
    dt = parse_iso(event_time)
    if dt is None:
        return False
    return now_or(now) > dt + timedelta(hours=grace_hours)


def describe_age(when, now=None):
    """Mô tả độ cũ theo lối nói thường: 'hôm nay' | 'hôm qua' | 'N ngày trước' | 'ngày DD/MM'."""
    dt = parse_iso(when)
    if dt is None:
        return ""
    days = (now_or(now).date() - dt.date()).days
    if days <= 0:
        return "hôm nay"
    if days == 1:
        return "hôm qua"
    if days < 7:
        return f"{days} ngày trước"
    return f"ngày {dt.strftime('%d/%m')}"


def older_than_days(when, days, now=None):
    """True nếu `when` cũ hơn `days` ngày. Không rõ thời điểm -> False (giữ lại)."""
    dt = parse_iso(when)
    if dt is None:
        return False
    return (now_or(now) - dt) > timedelta(days=days)
