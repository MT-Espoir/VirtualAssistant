"""
Giao thức lệnh điều khiển Chrome — logic THUẦN (không mạng/websocket), để test được.

Chuyển "hành động media" cấp tool (play/pause/...) sang payload JSON gửi cho
extension, và tóm tắt phản hồi của extension thành câu tiếng Việt cho agent đọc lại.
Phần vận chuyển (WebSocket) nằm ở services/browser_bridge.py.
"""

import re

from utils.units import format_km as _km, say_distance

# Tên hành động cấp tool (LLM dùng) -> mã gửi cho extension (background.js).
MEDIA_ACTIONS = {
    "play": "PLAY",
    "pause": "PAUSE",
    "toggle": "TOGGLE",
    "next": "NEXT",
    "prev": "PREV",
    "set_volume": "SET_VOLUME",
    "adjust_volume": "ADJUST_VOLUME",
    "seek": "SEEK",
}

# Các hành động cần tham số 'value'.
_NEEDS_VALUE = {"set_volume", "adjust_volume", "seek"}


def normalize_media_action(action):
    """'Play' / ' play ' -> mã 'PLAY'; không hợp lệ -> None."""
    return MEDIA_ACTIONS.get((action or "").strip().lower())


def build_media_command(action, value=None):
    """Dựng payload CONTROL_MEDIA cho extension. Ném ValueError nếu tham số sai.

    - set_volume: value là số 0..100 (phần trăm).
    - seek:       value là số giây (âm = tua lùi).
    """
    key = (action or "").strip().lower()
    code = normalize_media_action(key)
    if code is None:
        raise ValueError(
            f"Hành động media không hợp lệ: '{action}'. "
            "Chọn: play, pause, toggle, next, prev, set_volume, seek.")

    cmd = {"action": "CONTROL_MEDIA", "mediaAction": code}

    if key in _NEEDS_VALUE:
        if value is None:
            raise ValueError(f"Hành động '{key}' cần 'value'.")
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"'value' phải là số, nhận: {value!r}.")
        if key == "set_volume":
            num = max(0.0, min(100.0, num))
        elif key == "adjust_volume":
            num = max(-100.0, min(100.0, num))
        cmd["value"] = num

    return cmd


def summarize_media_response(resp, action, value=None):
    """Chuyển phản hồi extension thành câu tiếng Việt cho agent."""
    if not isinstance(resp, dict):
        return "Không nhận được phản hồi hợp lệ từ Chrome."

    if resp.get("type") == "ERROR":
        msg = str(resp.get("message", "lỗi không rõ"))
        if "no media" in msg.lower() or "no active" in msg.lower() or "no video" in msg.lower():
            return "Không tìm thấy tab Chrome đang phát media (YouTube)."
        if "not connected" in msg.lower() or "chưa kết nối" in msg:
            return ("Chrome chưa kết nối — hãy chắc extension 'AI Assistant Bridge' "
                    "đã được bật trong Chrome.")
        return f"Không điều khiển được media trên Chrome: {msg}"

    if resp.get("success"):
        key = (action or "").strip().lower()
        labels = {
            "play": "Đã phát media",
            "pause": "Đã tạm dừng media",
            "toggle": "Đã bật/tắt phát media",
            "next": "Đã chuyển bài/video kế tiếp",
            "prev": "Đã quay về bài/video trước",
            "set_volume": f"Đã đặt âm lượng trình phát {int(value)}%" if value is not None
                          else "Đã đặt âm lượng trình phát",
            "adjust_volume": ("Đã tăng" if (value or 0) >= 0 else "Đã giảm")
                             + " âm lượng trình phát",
            "seek": f"Đã tua {'+' if (value or 0) >= 0 else ''}{value} giây" if value is not None
                    else "Đã tua",
        }
        return labels.get(key, "Đã thực hiện") + " trên Chrome."

    return "Chrome không thực hiện được lệnh media (không tìm thấy trình phát?)."


# --------------------------------------------------------------------------- #
# Feature 1: quản lý tab (liệt kê / đóng theo từ khoá, có xác nhận)
# --------------------------------------------------------------------------- #
def _domain(url):
    """Rút gọn URL thành tên miền cho dễ đọc."""
    u = (url or "").split("//", 1)[-1]
    return u.split("/", 1)[0] or url or ""


def _error_or_none(resp):
    """Nếu resp là lỗi/không hợp lệ, trả câu tiếng Việt; ngược lại None."""
    if not isinstance(resp, dict):
        return "Không nhận được phản hồi hợp lệ từ Chrome."
    if resp.get("type") == "ERROR":
        msg = str(resp.get("message", "lỗi không rõ"))
        if "not connected" in msg.lower() or "chưa kết nối" in msg:
            return ("Lỗi: Chrome Extension chưa kết nối. Hãy kiểm tra extension "
                    "'AI Assistant Bridge' đã được bật trong Chrome.")
        return f"Lỗi khi thao tác tab Chrome: {msg}"
    return None


def summarize_tab_list(resp, limit=20):
    """Phản hồi TAB_LIST -> danh sách tab tiếng Việt."""
    err = _error_or_none(resp)
    if err:
        return err
    tabs = resp.get("tabs") or []
    if not tabs:
        return "Hiện không có tab Chrome nào đang mở."
    lines = []
    for i, t in enumerate(tabs[:limit], 1):
        title = (t.get("title") or "(không tiêu đề)").strip()
        lines.append(f"{i}. {title} — {_domain(t.get('url'))}")
    extra = f"\n… và {len(tabs) - limit} tab nữa." if len(tabs) > limit else ""
    return f"Đang mở {len(tabs)} tab Chrome:\n" + "\n".join(lines) + extra


def summarize_close(resp, keyword, confirm):
    """Phản hồi CLOSE_TAB_BY_KEYWORD -> câu xác nhận (confirm=False) hoặc kết quả."""
    err = _error_or_none(resp)
    if err:
        return err

    matched = resp.get("matched") or []
    if not matched:
        return f"Không tìm thấy tab Chrome nào khớp '{keyword}'."

    titles = ", ".join((t.get("title") or _domain(t.get("url")) or "?").strip()
                       for t in matched[:8])

    if not confirm:      # bước xem trước — CHƯA đóng, chờ người dùng đồng ý
        return (f"Tìm thấy {len(matched)} tab khớp '{keyword}': {titles}. "
                f"Bạn có chắc muốn đóng {'chúng' if len(matched) > 1 else 'tab này'} không? "
                "(xác nhận thì tôi sẽ đóng)")

    closed = resp.get("closedCount", len(matched))
    return f"Đã đóng {closed} tab khớp '{keyword}': {titles}."


# --------------------------------------------------------------------------- #
# Feature 2: mở-hoặc-tái-dùng tab (open-or-reuse)
# --------------------------------------------------------------------------- #
def normalize_url(url):
    """Chuẩn hoá thành URL có scheme (sửa 'https//x', thêm 'https://' nếu thiếu)."""
    u = (url or "").strip()
    u = re.sub(r"^(https?)//", r"\1://", u, flags=re.IGNORECASE)   # 'https//x' -> 'https://x'
    if not re.match(r"^https?://", u, flags=re.IGNORECASE):
        u = "https://" + u.lstrip("/")
    return u


def host_of(url):
    """Tên miền để so khớp tab, bỏ tiền tố 'www.' (vd -> 'youtube.com')."""
    host = normalize_url(url).split("://", 1)[1].split("/", 1)[0].lower()
    return host[4:] if host.startswith("www.") else host


def build_open_or_reuse(url, match_domain=None):
    """Dựng payload OPEN_OR_REUSE_URL. Tự suy tên miền khớp từ url nếu không truyền."""
    if not url or not str(url).strip():
        raise ValueError("Cần URL để mở.")
    nurl = normalize_url(url)
    domain = (match_domain or host_of(nurl)).strip().lower()
    return {"action": "OPEN_OR_REUSE_URL", "targetDomain": domain, "newUrl": nurl}


# --------------------------------------------------------------------------- #
# Feature 3: tìm web + ĐỌC danh sách kết quả (extension trích DOM trang kết quả)
# --------------------------------------------------------------------------- #
_SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q=",
    "duckduckgo": "https://duckduckgo.com/?q=",
}


def build_search_read(query, engine="google", limit=5):
    """Dựng payload SEARCH_READ cho extension. Ném ValueError nếu thiếu query.

    Extension sẽ MỞ trang kết quả của `engine`, đọc DOM đã render, trả về top `limit`
    kết quả {title, url}. Engine lạ -> lùi về google.
    """
    if not query or not str(query).strip():
        raise ValueError("Cần nội dung để tìm kiếm.")
    eng = (engine or "google").strip().lower()
    if eng not in _SEARCH_ENGINES:
        eng = "google"
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 5
    return {"action": "SEARCH_READ", "query": str(query).strip(),
            "engine": eng, "limit": max(1, min(10, n))}


def parse_search_results(resp):
    """Phản hồi SEARCH_READ -> (danh sách [{title,url}], lỗi|None).

    Lọc bỏ mục thiếu url; cắt/chuẩn hoá text. Lỗi kết nối/không hợp lệ -> câu tiếng Việt.
    """
    err = _error_or_none(resp)
    if err:
        return [], err
    out = []
    for r in resp.get("results") or []:
        url = (r.get("url") or "").strip()
        if not url:
            continue
        title = (r.get("title") or _domain(url)).strip()
        out.append({"title": title, "url": url})
    return out, None


def summarize_search_results(results, query):
    """Danh sách kết quả -> câu ĐỌC cho người dùng (chỉ tiêu đề, hỏi chọn số mấy)."""
    if not results:
        return f"Không đọc được kết quả tìm kiếm cho '{query}'."
    lines = [f"{i}. {r['title']}" for i, r in enumerate(results, 1)]
    return (f"Tôi tìm được {len(results)} kết quả cho '{query}':\n" + "\n".join(lines)
            + "\nBạn muốn mở kết quả số mấy?")


def summarize_open_or_reuse(resp, url):
    """Phản hồi OPEN_OR_REUSE_URL -> câu tiếng Việt (tái dùng tab hay mở tab mới)."""
    err = _error_or_none(resp)
    if err:
        return err
    # UX: chỉ nêu tên miền, KHÔNG đọc full URL (dài, khó nghe khi TTS đọc).
    shown = resp.get("url") or normalize_url(url)
    site = host_of(shown)
    if resp.get("reused"):
        return f"Đã dùng lại tab {site} sẵn có và chuyển sang trang mới."
    return f"Đã mở tab mới trên {site}."


# ============================ MAPS_READ (địa điểm) ============================
# Bảng mã kết quả — xem PRD P0-1. Ý nghĩa của mã quyết định CÂU ĐƯỢC PHÉP NÓI, nên
# mọi mã đều phải có mặt ở đúng một trong hai nhóm dưới đây.

# Chỉ những mã này mới được diễn đạt thành "không có / không tìm thấy".
SAYS_NOTHING_FOUND = ("NO_RESULTS", "OUT_OF_AREA", "APPROX_MATCH")
# Mã báo HỆ THỐNG hỏng -> phải nói "tôi không tra được", TUYỆT ĐỐI không nói "không có".
SAYS_CANNOT_LOOK_UP = ("TIMEOUT", "BLOCKED", "SCRAPE_FAILED", "PARSER_ERROR",
                       "SOURCE_UNAVAILABLE")
PLACE_OUTCOMES = ("OK",) + SAYS_NOTHING_FOUND + SAYS_CANNOT_LOOK_UP


def zoom_for_radius(radius_km):
    """Bán kính yêu cầu -> mức zoom của URL Maps.

    Đo thật (2026-08-21): bảng kết quả Maps trả TỐI ĐA ~6 mục bất kể zoom hay cuộn, nhưng
    zoom quyết định 6 mục NÀO — 17z cho các chỗ cách 0,25-0,63 km, còn 15z cho 0,4-1,26 km.
    Vậy nên khớp khung nhìn với ràng buộc, thay vì cố định 15z.
    """
    try:
        r = float(radius_km)
    except (TypeError, ValueError):
        return 15
    if r <= 0:
        return 13          # không ràng buộc (tìm đúng một chỗ) -> khung rộng cho dễ thấy
    if r <= 1:
        return 17
    if r <= 2:
        return 16
    if r <= 5:
        return 15
    if r <= 10:
        return 14
    return 13


def build_maps_read(query, lat, lng, limit=10, radius_km=None):
    """Dựng payload MAPS_READ. Extension chỉ ĐỌC DOM và trả dữ liệu THÔ.

    Tâm bản đồ là BẮT BUỘC: thiếu nó Maps rơi vào 'limited view' và chỉ trả 1 kết quả
    (đo thật ở Phase 0). Lọc khoảng cách / khớp tên / quyết mã kết quả nằm ở
    actions/places.py — thuần, test được, dùng chung cho cả nguồn OSM.
    """
    if not query or not str(query).strip():
        raise ValueError("Cần nội dung để tìm địa điểm.")
    try:
        flat, flng = float(lat), float(lng)
    except (TypeError, ValueError):
        raise ValueError("Cần toạ độ (lat/lng) để tra địa điểm.")
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 10
    payload = {"action": "MAPS_READ", "query": str(query).strip(),
               "lat": flat, "lng": flng, "limit": max(1, min(20, n))}
    if radius_km is not None:
        payload["zoom"] = zoom_for_radius(radius_km)
    return payload


# Mã cấp TRANG do extension trả về (chỉ thứ nó nhìn thấy được từ DOM).
PAGE_OUTCOMES = ("RAW", "EMPTY", "BLOCKED", "SCRAPE_FAILED", "PARSER_ERROR",
                 "SOURCE_UNAVAILABLE")


def parse_maps_response(resp):
    """Phản hồi MAPS_READ -> (page_outcome, [mục thô], diagnostics).

    KHÔNG BAO GIỜ trả mảng trần: lỗi vận chuyển -> SOURCE_UNAVAILABLE, để tầng trên
    phân biệt được 'không có quán' với 'tôi hỏng' (PRD P0-1).
    """
    if not isinstance(resp, dict) or resp.get("type") == "ERROR":
        msg = resp.get("message", "") if isinstance(resp, dict) else ""
        return "SOURCE_UNAVAILABLE", [], {"transportError": str(msg)}

    page = resp.get("pageOutcome")
    if page not in PAGE_OUTCOMES:
        return "SCRAPE_FAILED", [], {"badOutcome": str(page)}

    items = []
    for r in resp.get("items") or []:
        name = (r.get("name") or "").strip()
        lat, lng = r.get("lat"), r.get("lng")
        if not name or lat is None or lng is None:
            continue          # thiếu tên hoặc toạ độ -> không kiểm chứng được -> bỏ
        items.append({"name": name, "url": (r.get("url") or "").strip(),
                      "lat": lat, "lng": lng,
                      # dòng THÔ để tầng Python bóc đặc trưng (F1.5 §6)
                      "lines": r.get("lines") or [], "aria": r.get("aria") or [],
                      "rating": r.get("rating"), "address": r.get("address")})
    return page, items, (resp.get("diagnostics") or {})


def _place_line(i, p):
    """Một dòng đọc: số thứ tự + tên + khoảng cách + cảnh báo sắp đóng cửa (nếu biết).

    Chỉ nêu những gì CÓ dữ liệu thật; thiếu thì im lặng bỏ qua, không suy đoán.
    """
    bits = []
    dist = say_distance(p.get("distance_km"))
    if dist:
        bits.append(dist)
    opening = p.get("opening") or {}
    if opening.get("state") == "closing_soon":
        closes = opening.get("closes_at")
        bits.append(f"sắp đóng cửa lúc {closes[0]}:{closes[1]:02d}" if closes else "sắp đóng cửa")
    elif opening.get("state") == "closed":
        bits.append("đang đóng cửa")
    elif opening.get("state") == "open_24h":
        bits.append("mở cả ngày")
    return f"{i}. {p['name']}" + (f" ({', '.join(bits)})" if bits else "")


def summarize_places(outcome, results, query, diagnostics=None, area=None, source=None,
                     speak_limit=None, top_reason=None):
    """Kết quả tra địa điểm -> câu tiếng Việt ĐỌC được.

    Đây là nơi CHỐT quy tắc bất khả xâm phạm của P0-1: chỉ NO_RESULTS / OUT_OF_AREA /
    APPROX_MATCH mới được nói 'không có'; mọi mã hỏng phải nói 'không tra được'.
    Ghép câu ở đây (không giao LLM) để quy tắc là tất định và test được.
    """
    diagnostics = diagnostics or {}
    where = f" ở {area}" if area else ""
    src_note = " (tôi tra bằng dữ liệu bản đồ mở, có thể thiếu)" if source == "osm" else ""

    if outcome == "OK" and results:
        n = len(results)
        shown = results if not speak_limit or n <= speak_limit else results[:speak_limit]
        lines = [_place_line(i, p) for i, p in enumerate(shown, 1)]
        if len(shown) < n:
            # Đọc 6-8 cái tên qua TTS thì quá dài, nhưng vẫn phải nói THẬT là có bao nhiêu.
            head = (f"Tôi tìm được {n} chỗ cho '{query}'{where}{src_note}, "
                    f"đọc bạn nghe {len(shown)} chỗ gần nhất:")
            tail = f"\nBạn muốn mở chỗ số mấy? (còn {n - len(shown)} chỗ nữa)"
        else:
            head = f"Tôi tìm được {n} chỗ cho '{query}'{where}{src_note}:"
            tail = "\nBạn muốn mở chỗ số mấy?"
        # Giải thích cho lựa chọn ĐẦU thôi: đọc lý do cho cả 3 chỗ thì câu quá dài
        # khi TTS đọc, mà giá trị thêm không đáng.
        reason = ("\n" + top_reason) if top_reason else ""
        return head + "\n" + "\n".join(lines) + reason + tail

    if outcome == "APPROX_MATCH":
        # KHÔNG được trình bày như đã tìm thấy — phải nói rõ là khác cái được hỏi.
        alt = "; ".join(p["name"] for p in results[:3]) or "một vài chỗ tên gần giống"
        return (f"Tôi không thấy đúng '{query}'{where}. Gần giống thì có: {alt}. "
                f"Có phải bạn muốn tìm một trong số này không?")

    if outcome == "OUT_OF_AREA":
        near = _km(diagnostics.get("nearest_km"))
        base = (f"Không có '{query}'{where}." if area
                else f"Quanh đây tôi không thấy '{query}' nào.")
        if near:
            base += f" Chỗ gần nhất cách khoảng {near}."
        return base

    if outcome == "NO_RESULTS":
        return f"Tôi không tìm thấy '{query}'{where}."

    # Mọi mã còn lại = HỆ THỐNG hỏng. Không được nói 'không có'.
    if outcome == "SOURCE_UNAVAILABLE":
        return (f"Tôi chưa tra được '{query}' vì trình duyệt chưa sẵn sàng. "
                f"Bạn mở Chrome giúp tôi rồi hỏi lại nhé.")
    if outcome == "BLOCKED":
        return f"Tôi chưa tra được '{query}' vì trang bản đồ đang chặn. Bạn thử lại sau nhé."
    if outcome == "TIMEOUT":
        return f"Tra '{query}' lâu quá nên tôi chưa lấy được kết quả. Bạn thử lại nhé."
    return f"Tôi chưa đọc được kết quả cho '{query}' lúc này."
