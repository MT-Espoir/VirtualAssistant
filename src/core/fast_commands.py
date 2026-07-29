"""
Fast-path lệnh trực tiếp — logic THUẦN, để test được.

Vài câu lệnh cố định, không mơ hồ (cuộn lên/xuống, chụp màn hình) được ánh xạ THẲNG
sang (tên tool, tham số) và chạy ngay, KHÔNG qua LLM — tránh độ trễ "suy nghĩ" của
model local với những lệnh vốn không cần suy luận. Câu khác trả None -> để agent/LLM xử lý.

match_fast_command(text) -> (tool_name, args) | None
"""

import re

from utils.text_norm import norm as _norm


def _first_match(text, rules):
    """rules: list tuple mà phần tử [0] là danh sách cụm khoá. Trả tuple khớp đầu tiên."""
    t = _norm(text)
    if not t:
        return None
    for entry in rules:
        if any(p in t for p in entry[0]):
            return entry
    return None


# Mỗi mục: (danh sách cụm khoá đã chuẩn hoá, tool_name, args).
# Khớp nếu text (đã chuẩn hoá) CHỨA một trong các cụm khoá. Đặt cụm dài/đặc thù trước.
_RULES = [
    (["cuon xuong", "luot xuong", "keo xuong", "scroll xuong", "xuong tiep",
      "cuon xuong tiep", "keo xuong tiep"], "scroll_screen", {"direction": "down"}),
    (["cuon len", "luot len", "keo len", "scroll len", "len tren", "keo len tren"],
     "scroll_screen", {"direction": "up"}),
    (["chup man hinh", "chup lai man hinh", "chup hinh man hinh", "chup screen",
      "screenshot"], "take_screenshot", {}),
]


def _match_volume(text):
    """Lệnh chỉnh âm lượng -> (tool, args). Có số -> mức tuyệt đối; không -> ±10.

    Chạy thẳng tool (không qua LLM) để đảm bảo đổi mọi lần — model 3B hay ngừng gọi
    tool sau lần đầu. Có từ 'video/youtube/nhạc' -> âm lượng trình phát (Chrome).
    """
    t = _norm(text)
    if "am luong" not in t and "volume" not in t:
        return None
    num = re.search(r"\d+", t)
    if any(w in t for w in ("video", "youtube", "clip", "nhac", "phim")):
        return ("browser_media_control", {"action": "set_volume", "value": int(num.group())}) \
            if num else None
    if num:
        return "set_volume", {"level": int(num.group())}
    if any(w in t for w in ("tang", "len", "to hon", "cao hon", "to len")):
        return "set_volume", {"change": 10}
    if any(w in t for w in ("giam", "xuong", "nho hon", "nho di", "bot", "thap hon")):
        return "set_volume", {"change": -10}
    return None


# Ngữ cảnh media: chỉ coi là lệnh điều khiển trình phát khi câu có nhắc tới video/nhạc
# — tránh cướp nhầm các câu "dừng"/"ngừng" nói về việc khác.
_MEDIA_CONTEXT = ("video", "youtube", "nhac", "clip", "phim", "bai hat", "bai nhac")

# Mỗi mục: (cụm khoá đã chuẩn hoá, action, cần_ngữ_cảnh_media?). Đặt cụm ĐẶC THÙ trước:
# 'tiep theo' (next) phải kiểm trước 'tiep tuc'/'phat tiep' (play) để không lẫn.
# next/prev tự hàm ý media ("bài trước", "chuyển bài") -> không cần context; còn
# pause/play dùng từ chung chung ("ngừng", "tiếp tục") -> cần context để khỏi cướp nhầm.
_MEDIA_RULES = [
    (["bai tiep theo", "video tiep theo", "bai ke tiep", "bai ke", "chuyen bai",
      "qua bai", "bai sau", "video sau", "clip sau"], "next", False),
    (["bai truoc", "video truoc", "quay lai bai", "lui bai", "bai ke truoc"], "prev", False),
    (["phat tiep", "tiep tuc", "choi tiep", "phat lai", "chay tiep"], "play", True),
    (["tam dung", "tam ngung", "ngung", "dung phat", "dung video", "dung nhac",
      "dung lai", "dung phim", "dung clip"], "pause", True),
]


def _match_media(text):
    """Lệnh điều khiển trình phát media (video/nhạc) -> (tool, args). None nếu không khớp.

    Chạy thẳng tool (không qua LLM) vì model hay chỉ nói 'đã dừng' mà KHÔNG gọi tool —
    dừng/phát tiếp/bài kế là lệnh tất định, đảm bảo luôn chạy. Với pause/play (từ chung
    chung) chỉ nhận khi câu có ngữ cảnh media để không cướp nhầm 'dừng lại' nói việc khác.
    """
    t = _norm(text)
    if not t:
        return None
    has_context = any(c in t for c in _MEDIA_CONTEXT)
    for kws, action, needs_context in _MEDIA_RULES:
        if any(k in t for k in kws) and (has_context or not needs_context):
            return "browser_media_control", {"action": action}
    return None


def match_fast_command(text):
    """Trả (tool_name, args) nếu `text` là lệnh trực tiếp đã biết; ngược lại None.

    Chỉ dành cho lệnh TẤT ĐỊNH, đơn giản (âm lượng, media, cuộn, chụp) — chạy thẳng tool
    cho tức thì + đảm bảo chạy. Yêu cầu phức tạp (tìm YouTube, web...) để ROUTER + LLM
    lo, tránh 'hijack' bằng luật cứng.
    """
    vol = _match_volume(text)
    if vol is not None:
        return vol
    media = _match_media(text)
    if media is not None:
        return media
    m = _first_match(text, _RULES)
    return (m[1], dict(m[2])) if m else None


# Lệnh chỉnh GIAO DIỆN avatar (đổi kích thước / độ mờ) — trả dict lệnh UI cho bus.
_UI_RULES = [
    (["nho hon", "nho lai", "thu nho", "be lai", "be hon", "nho di"],
     {"scale_delta": -0.15}),
    (["to hon", "lon hon", "phong to", "to len", "to ra"],
     {"scale_delta": 0.15}),
    (["mo hon", "mo di", "mo hon nua", "trong suot hon", "lam mo"],
     {"opacity_delta": -0.15}),
    (["ro hon", "dam hon", "bot mo", "ro rang hon", "net hon"],
     {"opacity_delta": 0.15}),
]


def match_avatar_command(text):
    """Trả dict lệnh giao diện (vd {'scale_delta': -0.15}) nếu khớp; ngược lại None."""
    m = _first_match(text, _UI_RULES)
    return dict(m[1]) if m else None
