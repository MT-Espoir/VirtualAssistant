"""
Fast-path lệnh trực tiếp — logic THUẦN, để test được.
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


_MEDIA_CONTEXT = ("video", "youtube", "nhac", "clip", "phim", "bai hat", "bai nhac")

_MEDIA_RULES = [
    (["bai tiep theo", "video tiep theo", "bai ke tiep", "bai ke", "chuyen bai",
      "qua bai", "bai sau", "video sau", "clip sau"], "next", False),
    (["bai truoc", "video truoc", "quay lai bai", "lui bai", "bai ke truoc"], "prev", False),
    (["phat tiep", "tiep tuc", "choi tiep", "phat lai", "chay tiep"], "play", True),
    (["tam dung", "tam ngung", "ngung", "dung phat", "dung video", "dung nhac",
      "dung lai", "dung phim", "dung clip"], "pause", True),
]


def _match_media(text):
    """Lệnh điều khiển trình phát media (video/nhạc) -> (tool, args). None nếu không khớp."""
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


# Chuyển chế độ nghe: "làm việc" (tắt wake word, ra lệnh trực tiếp) vs "bình thường"
# (bật lại wake word). Cụm "bình thường"/"thoát"/"tắt" phải kiểm TRƯỚC vì chúng chứa
# luôn cụm "che do lam viec" -> nếu kiểm 'work' trước sẽ khớp nhầm thành bật.
_MODE_NORMAL_KWS = ["binh thuong", "thoat che do lam viec", "tat che do lam viec",
                    "tat lam viec", "ket thuc lam viec", "che do thuong",
                    "quay lai binh thuong", "khong lam viec nua", "thoi lam viec"]
_MODE_WORK_KWS = ["che do lam viec", "sang lam viec", "bat lam viec", "vao lam viec",
                  "bat dau lam viec", "che do cong viec", "sang cong viec"]


def match_mode_command(text):
    """Trả 'work' (vào chế độ làm việc) / 'normal' (về bình thường) / None."""
    t = _norm(text)
    if not t:
        return None
    if any(k in t for k in _MODE_NORMAL_KWS):
        return "normal"
    if any(k in t for k in _MODE_WORK_KWS):
        return "work"
    return None


# Xác nhận có/không cho hành động khó hoàn tác (vd đóng app). Dùng để CHỐT TRONG CODE
# việc thực thi — chỉ một câu "có" rõ ràng mới cho chạy. Cố ý BỎ QUA cụm mơ hồ (trả
# None -> coi như yêu cầu mới, huỷ chờ), thà bắt lặp lại còn hơn lỡ tay làm nhầm.
# Không nhận token "dung" (đúng/đừng/dừng bị bỏ dấu trùng nhau -> nhập nhằng).
_CONFIRM_YES_TOKENS = {"co", "u", "um", "uh", "ok", "oke", "okay", "duoc", "phai", "vang", "yes"}
_CONFIRM_YES_PHRASES = ("dong y", "dong di", "dong luon", "lam di", "lam luon", "cu lam",
                        "chinh xac", "xac nhan", "phai roi", "dung roi", "duoc roi",
                        "co chu", "tien hanh", "chac chan")
# LƯU Ý va chạm dấu: "thời" (thời tiết/thời gian) bỏ dấu = "thoi" trùng "thôi" -> câu
# hỏi thời tiết lúc đang chờ xác nhận sẽ bị coi là 'no'. Chấp nhận: huỷ là chiều AN TOÀN
# (chỉ mất công hỏi lại), còn nhận nhầm 'yes' mới nguy hiểm nên siết chặt phía 'yes'.
_CONFIRM_NO_TOKENS = {"khong", "thoi", "huy", "khoi"}
_CONFIRM_NO_PHRASES = ("khong can", "khong lam", "khong dong", "khong muon", "thoi khoi",
                       "bo di", "de sau", "dung lai", "khoan da")


# Chỉnh NÚM tính cách bằng lời (học tường minh). Mỗi lệnh nhích một núm ±0.15 (có biên,
# kẹp [0,1]). Đặt cụm đặc thù trước. 'say' = câu xác nhận thân thiện đọc lại.
_PERSONA_RULES = [
    (["vui tinh hon", "hai huoc hon", "hai hon", "dua nhieu hon", "vui hon chut", "vui ve hon"],
     {"trait": "humor", "delta": 0.15, "say": "Được, mình sẽ vui tính hơn nhé!"}),
    (["bot dua", "nghiem tuc hon", "dung dan hon", "it dua di", "bot hai"],
     {"trait": "humor", "delta": -0.15, "say": "Ừ, mình sẽ nghiêm túc hơn."}),
    (["than thien hon", "am ap hon", "gan gui hon", "diu dang hon", "tinh cam hon"],
     {"trait": "warmth", "delta": 0.15, "say": "Mình sẽ thân thiện hơn với bạn."}),
    (["lanh lung hon", "bot than", "xa cach hon", "lanh hon"],
     {"trait": "warmth", "delta": -0.15, "say": "Được, mình sẽ tiết chế hơn."}),
    (["trang trong hon", "lich su hon", "trinh trong hon"],
     {"trait": "formality", "delta": 0.15, "say": "Vâng, tôi sẽ trang trọng hơn."}),
    (["thoai mai hon", "suong sa hon", "bot trang trong", "tu nhien hon", "than mat hon"],
     {"trait": "formality", "delta": -0.15, "say": "Oke, mình nói thoải mái hơn nhé."}),
    (["nang dong hon", "soi noi hon", "hao hung hon", "nhiet hon"],
     {"trait": "energy", "delta": 0.15, "say": "Yeah, mình sẽ sôi nổi hơn!"}),
    (["tram hon", "binh tinh hon", "nhe nhang hon", "diu lai", "cham lai"],
     {"trait": "energy", "delta": -0.15, "say": "Ừ, mình sẽ nhẹ nhàng hơn."}),
]
_PERSONA_RESET_KWS = ["reset tinh cach", "ve tinh cach mac dinh", "tinh cach mac dinh",
                      "tinh cach binh thuong", "khoi phuc tinh cach", "tinh cach ban dau"]


def match_persona_command(text):
    """Lệnh chỉnh tính cách trợ lý -> dict {trait,delta,say} | {reset,say} | None.

    Kiểm 'reset' TRƯỚC (cụm reset không chứa núm nào ở trên)."""
    t = _norm(text)
    if not t:
        return None
    if any(k in t for k in _PERSONA_RESET_KWS):
        return {"reset": True, "say": "Mình đã quay lại tính cách ban đầu."}
    m = _first_match(text, _PERSONA_RULES)
    return dict(m[1]) if m else None


def match_confirmation(text):
    """Phân loại câu trả lời xác nhận: 'yes' | 'no' | None (không rõ).

    An toàn là ưu tiên: 'no' kiểm TRƯỚC và THAM (huỷ hành động nguy hiểm); còn 'yes' bằng
    token trần ("có", "ừ", "ok") CHỈ tính khi câu NGẮN (<=3 từ) để câu dài mở đầu bằng
    "có..." (vd 'có xem giúp tôi...') không bị nhận nhầm là đồng ý. Cụm rõ nghĩa (đồng ý,
    làm đi, đúng rồi...) thì luôn tính. Không rõ -> None (coi như yêu cầu mới).
    """
    t = _norm(text)
    if not t:
        return None
    tokens = set(t.split())
    if tokens & _CONFIRM_NO_TOKENS or any(p in t for p in _CONFIRM_NO_PHRASES):
        return "no"
    if any(p in t for p in _CONFIRM_YES_PHRASES):
        return "yes"
    if len(tokens) <= 3 and tokens & _CONFIRM_YES_TOKENS:
        return "yes"
    return None
