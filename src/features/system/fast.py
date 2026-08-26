"""Fast-path của feature `system` — khớp thẳng ra tool, không tốn lượt LLM nào."""

import re

from utils.text_norm import norm

VOL_UP = ("tang", "len", "to hon", "cao hon", "to len", "to ra", "lon hon")
VOL_DOWN = ("giam", "xuong", "nho hon", "nho di", "bot", "thap hon", "nho lai")

# Có mấy từ này thì người dùng đang nói âm lượng TRÌNH PHÁT, không phải âm lượng máy —
# phần đó thuộc feature `browser`. Hai bên loại trừ nhau nên thứ tự khớp không quan trọng.
_MEDIA_WORDS = ("video", "youtube", "clip", "nhac", "phim")


def match_volume(text):
    """Chỉnh âm lượng HỆ THỐNG -> (tool, args). Có số -> mức tuyệt đối; không -> ±10.

    Chạy thẳng tool (không qua LLM) để đảm bảo đổi mọi lần — model 3B hay ngừng gọi
    tool sau lần đầu.
    """
    t = norm(text)
    if "am luong" not in t and "volume" not in t:
        return None
    if any(w in t for w in _MEDIA_WORDS):
        return None                     # âm lượng trình phát -> features/browser/fast.py
    num = re.search(r"\d+", t)
    if num:
        return "set_volume", {"level": int(num.group())}
    if any(w in t for w in VOL_UP):
        return "set_volume", {"change": 10}
    if any(w in t for w in VOL_DOWN):
        return "set_volume", {"change": -10}
    return None


FAST_PATHS = (match_volume,)
