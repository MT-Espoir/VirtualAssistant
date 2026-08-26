"""Fast-path của feature `screen` — cuộn và chụp màn hình."""

from utils.text_norm import norm

# Khớp nếu text (đã chuẩn hoá) CHỨA một trong các cụm khoá. Đặt cụm dài/đặc thù trước.
_RULES = [
    (["cuon xuong", "luot xuong", "keo xuong", "scroll xuong", "xuong tiep",
      "cuon xuong tiep", "keo xuong tiep"], "scroll_screen", {"direction": "down"}),
    (["cuon len", "luot len", "keo len", "scroll len", "len tren", "keo len tren"],
     "scroll_screen", {"direction": "up"}),
    (["chup man hinh", "chup lai man hinh", "chup hinh man hinh", "chup screen",
      "screenshot"], "take_screenshot", {}),
]


def match_screen(text):
    t = norm(text)
    if not t:
        return None
    for kws, tool, args in _RULES:
        if any(k in t for k in kws):
            return tool, dict(args)
    return None


FAST_PATHS = (match_screen,)
