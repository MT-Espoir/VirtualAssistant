"""
Fast-path lệnh trực tiếp — logic THUẦN, để test được.
"""

import re

from utils.text_norm import norm as _norm, strip_accents as _strip_accents


def match_control_panel_command(text):
    """Local UI commands, available even when tool fast paths are disabled."""
    words = _norm(text)
    words = re.sub(r"^alice\s+", "", words)
    words = re.sub(r"^(?:hay|vui long|lam on)\s+", "", words)
    words = re.sub(r"\s+(?:giup toi|nhe|voi|di|a)$", "", words)
    match = re.fullmatch(r"(?:(mo|bat|hien|hien thi|dong|tat|an)\s+)?"
                         r"(?:bang dieu khien|bang chuc nang|bang cai dat|control panel)", words)
    if not match:
        return None
    return "hide" if match.group(1) in ("dong", "tat", "an") else "show"


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


# ĐÃ CHUYỂN ĐI: luật fast-path nhắm vào TOOL (âm lượng, media, cuộn, chụp) nay nằm ở
# `features/<tên>/fast.py` và khai qua `Feature.fast_paths` — xem `features/fast.py`.
# File này chỉ còn các lệnh KHÔNG phải tool: giao diện avatar, chế độ, xác nhận, tính
# cách, routine. Chúng thuộc về chính trợ lý chứ không thuộc tính năng nào.

# Lệnh chỉnh HUD phải có từ chỉ đích rõ ràng để không cướp các câu "phóng to" vốn đang
# điều khiển avatar. Giá trị là số thực liên tục: giọng nói chỉ là một nguồn input; bộ
# nhận diện pinch/gesture sau này có thể phát cùng payload ``scale_delta`` nhỏ tuỳ ý.
_HUD_CONTEXT = ("hud", "panel", "bang thong tin", "bang hien thi", "bang thong ke",
                "bang nay", "khung thong tin", "khung nay", "cua so thong tin",
                "cua so nay", "man hinh thong ke", "thong ke nay")
_AVATAR_CONTEXT = ("avatar", "nhan vat", "hinh dai dien")
_HUD_BIGGER = ("to hon", "lon hon", "phong to", "to len", "mo rong")
_HUD_SMALLER = ("nho hon", "nho lai", "thu nho", "be lai", "be hon", "thu gon")
_HUD_RESET = ("mac dinh", "ban dau", "binh thuong", "reset")
_NUMBER = r"(\d+(?:[\.,]\d+)?)"


def _number(raw):
    try:
        return float(raw.replace(",", "."))
    except (AttributeError, TypeError, ValueError):
        return None


def _mentions_hud(text, normalized):
    # Giữ chữ có dấu để phân biệt "bảng" (HUD) với "bằng" trong "phóng to bằng 120%".
    raw = (text or "").lower()
    return (re.search(r"(?<!\w)bảng(?!\w)", raw) is not None or
            any(marker in normalized for marker in _HUD_CONTEXT))


def explicit_ui_target(text):
    """Đích UI được người dùng gọi tên rõ ràng: ``hud`` / ``avatar`` / ``None``."""
    t = _norm(text)
    if not t:
        return None
    if _mentions_hud(text, t):
        return "hud"
    if any(marker in t for marker in _AVATAR_CONTEXT):
        return "avatar"
    return None


def match_hud_command(text, contextual_target=False):
    """Nhận lệnh scale HUD linh hoạt, trả payload UI hoặc ``None``.

    Ví dụ: ``HUD 137%`` đặt tuyệt đối; ``tăng panel thêm 12%`` cộng 0.12;
    ``HUD 1,25 lần`` đặt 1.25. Biên an toàn được áp ở tầng UI, không lượng tử hoá.
    """
    t = _norm(text)
    if not t or (not contextual_target and not _mentions_hud(text, t)):
        return None
    raw = _strip_accents((text or "").lower())

    if any(word in t for word in _HUD_RESET):
        return {"target": "hud", "scale": 1.0}

    percent = re.search(_NUMBER + r"\s*(?:%|phan tram)", raw)
    if percent:
        amount = _number(percent.group(1))
        if amount is None:
            return None
        delta = amount / 100.0
        if any(word in t for word in ("giam", "bot", "thu nho", "nho di")):
            return {"target": "hud", "scale_delta": -delta}
        if ("them" in t or
                any(word in t for word in ("tang", "phong to", "to them", "lon them"))):
            return {"target": "hud", "scale_delta": delta}
        return {"target": "hud", "scale": delta}

    multiple = re.search(_NUMBER + r"\s*lan", raw)
    if multiple:
        amount = _number(multiple.group(1))
        if amount is not None:
            return {"target": "hud", "scale": amount}

    if any(word in t for word in _HUD_SMALLER):
        return {"target": "hud", "scale_delta": -0.10}
    if any(word in t for word in _HUD_BIGGER):
        return {"target": "hud", "scale_delta": 0.10}
    return None


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


# Chạy routine bằng lời: "chạy routine X" -> trả tên X (đã chuẩn hoá). YÊU CẦU có từ
# "routine"/"quy trình" để KHÔNG cướp nhầm "chạy chrome". Tên khớp bỏ dấu ở RoutineStore.
_ROUTINE_RUN_KWS = ("chay routine", "khoi dong routine", "thuc hien routine",
                    "chay quy trinh", "khoi dong quy trinh", "thuc hien quy trinh")


def match_routine_command(text):
    """'chạy routine X' -> 'X' (chuẩn hoá bỏ dấu); None nếu không phải lệnh chạy routine."""
    t = _norm(text)
    if not t:
        return None
    for kw in _ROUTINE_RUN_KWS:
        if kw in t:
            name = t[t.find(kw) + len(kw):].strip()
            return name or None
    return None


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
