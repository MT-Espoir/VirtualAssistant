"""
Giao thức lệnh điều khiển Chrome — logic THUẦN (không mạng/websocket), để test được.

Chuyển "hành động media" cấp tool (play/pause/...) sang payload JSON gửi cho
extension, và tóm tắt phản hồi của extension thành câu tiếng Việt cho agent đọc lại.
Phần vận chuyển (WebSocket) nằm ở services/browser_bridge.py.
"""

import re

# Tên hành động cấp tool (LLM dùng) -> mã gửi cho extension (background.js).
MEDIA_ACTIONS = {
    "play": "PLAY",
    "pause": "PAUSE",
    "toggle": "TOGGLE",
    "next": "NEXT",
    "prev": "PREV",
    "set_volume": "SET_VOLUME",
    "seek": "SEEK",
}

# Các hành động cần tham số 'value'.
_NEEDS_VALUE = {"set_volume", "seek"}


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
