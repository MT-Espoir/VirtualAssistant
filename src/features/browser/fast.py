"""Fast-path của feature `browser` — điều khiển trình phát đang chạy sẵn trên Chrome."""

import re

from features.system.fast import VOL_DOWN, VOL_UP
from utils.text_norm import norm

MEDIA_CONTEXT = ("video", "youtube", "nhac", "clip", "phim", "bai hat", "bai nhac")

_MEDIA_RULES = [
    (["bai tiep theo", "video tiep theo", "bai ke tiep", "bai ke", "chuyen bai",
      "qua bai", "bai sau", "video sau", "clip sau"], "next", False),
    (["bai truoc", "video truoc", "quay lai bai", "lui bai", "bai ke truoc"], "prev", False),
    (["phat tiep", "tiep tuc", "choi tiep", "phat lai", "chay tiep"], "play", True),
    (["tam dung", "tam ngung", "ngung", "dung phat", "dung video", "dung nhac",
      "dung lai", "dung phim", "dung clip"], "pause", True),
]

# Chỉ các từ ngữ cảnh dùng cho ÂM LƯỢNG trình phát. Hẹp hơn MEDIA_CONTEXT có chủ đích:
# giữ đúng bộ từ mà bản gốc dùng cho nhánh âm lượng ("bai hat"/"bai nhac" không tính).
_VOL_CONTEXT = ("video", "youtube", "clip", "nhac", "phim")


def match_media_volume(text):
    """Âm lượng TRÌNH PHÁT (Chrome). Extension tự đọc mức hiện tại rồi cộng/trừ."""
    t = norm(text)
    if "am luong" not in t and "volume" not in t:
        return None
    if not any(w in t for w in _VOL_CONTEXT):
        return None                     # âm lượng máy -> features/system/fast.py
    num = re.search(r"\d+", t)
    if num:
        return "browser_media_control", {"action": "set_volume", "value": int(num.group())}
    if any(w in t for w in VOL_UP):
        return "browser_media_control", {"action": "adjust_volume", "value": 10}
    if any(w in t for w in VOL_DOWN):
        return "browser_media_control", {"action": "adjust_volume", "value": -10}
    return None


def match_media(text):
    """Tạm dừng / phát tiếp / chuyển bài -> (tool, args). None nếu không khớp."""
    t = norm(text)
    if not t:
        return None
    has_context = any(c in t for c in MEDIA_CONTEXT)
    for kws, action, needs_context in _MEDIA_RULES:
        if any(k in t for k in kws) and (has_context or not needs_context):
            return "browser_media_control", {"action": action}
    return None


FAST_PATHS = (match_media_volume, match_media)
