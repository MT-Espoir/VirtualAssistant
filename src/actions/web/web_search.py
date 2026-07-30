"""Mở web / tìm kiếm — dữ liệu trang lấy từ websites.json qua DataLoader."""

import re
import urllib.parse
import webbrowser

from utils.data_loader import DataLoader
from utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_url(raw):
    """Chuẩn hoá một chuỗi thành URL hợp lệ.

    - Sửa scheme thiếu dấu ':' (vd 'https//x' -> 'https://x').
    - Giữ nguyên nếu ĐÃ có scheme (tránh ghép 'https://' hai lần).
    - Thêm 'https://' nếu chưa có scheme.
    """
    u = (raw or "").strip()
    u = re.sub(r"^(https?)//", r"\1://", u, flags=re.IGNORECASE)   # 'https//x' -> 'https://x'
    if re.match(r"^https?://", u, flags=re.IGNORECASE):
        return u
    return "https://" + u.lstrip("/")

data_loader = DataLoader(language="vi")

_SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
}


def search_web(query, engine="google"):
    """Tìm kiếm web với công cụ chỉ định (google/bing/youtube)."""
    if not query:
        return "Chưa có nội dung tìm kiếm."
    encoded = urllib.parse.quote(query)
    template = _SEARCH_ENGINES.get(engine.lower(), _SEARCH_ENGINES["google"])
    webbrowser.open(template.format(q=encoded))
    return f"Đang tìm '{query}' trên {engine}."


def search_on_specific_site(query, site):
    """Tìm kiếm một truy vấn trên trang cụ thể (facebook, youtube, github...)."""
    site = site.lower()
    encoded = urllib.parse.quote(query)
    url_template = data_loader.get_search_url(site)

    if url_template:
        search_url = url_template.replace("{query}", encoded)
        search_url = search_url.replace("{query_no_spaces}", encoded.replace(' ', ''))
        webbrowser.open(search_url)
        return f"Đang tìm '{query}' trên {site.title()}."

    generic_url = f"https://www.{site}.com/search?q={encoded}"
    try:
        webbrowser.open(generic_url)
        return f"Đang thử tìm '{query}' trên {site.title()}."
    except webbrowser.Error:
        return f"Không tìm được trên {site}."


def resolve_website_url(name):
    """Tên/alias trang -> URL trang chủ (dựa websites.json), fallback đoán tên miền."""
    key = (name or "").strip().lower()
    homepages = data_loader.get_website_homepages()   # canonical -> url
    aliases = data_loader.get_website_keywords()        # canonical -> [aliases]

    if key in homepages:
        return homepages[key]
    for cano, alias_list in aliases.items():
        if key == cano or key in [a.lower() for a in alias_list]:
            if cano in homepages:
                return homepages[cano]
    if not key:
        return "https://www.google.com"
    # Không khớp danh bạ: coi 'key' như địa chỉ và chuẩn hoá (xử lý cả trường hợp
    # đã có sẵn scheme, tránh sinh URL kiểu 'https://https//www.youtube.com').
    if "." in key or "//" in key:
        return _normalize_url(key)
    return f"https://www.{key}.com"


def open_website(site_name):
    """Mở trực tiếp một trang web theo tên."""
    url = resolve_website_url(site_name)
    webbrowser.open(url)
    # UX: KHÔNG đọc/hiển thị full URL trong câu trả lời (dài, khó nghe khi TTS đọc);
    # URL thật vẫn ghi log để debug.
    logger.info("Mở website %s -> %s", site_name, url)
    return f"Đang mở {site_name}."


def search_and_play_youtube(query):
    """Mở TRANG KẾT QUẢ YouTube cho từ khóa (không mở thẳng video)."""
    if not query:
        return "Chưa có từ khóa tìm kiếm."
    encoded = urllib.parse.quote(query)
    webbrowser.open(f"https://www.youtube.com/results?search_query={encoded}")
    return f"Đã mở trang kết quả YouTube cho '{query}' (chưa phát video cụ thể)."


# ID video YouTube: đúng 11 ký tự [A-Za-z0-9_-]. Hai mẫu để tăng độ bền:
_VIDEO_ID_RE = re.compile(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"')
_WATCH_ID_RE = re.compile(r'/watch\?v=([A-Za-z0-9_-]{11})')

# Header giống trình duyệt thật + cookie bỏ qua trang consent EU của YouTube — nếu
# không, YouTube hay trả trang xin đồng ý cookie (KHÔNG chứa videoId) -> trích trượt.
_YT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    "Cookie": "CONSENT=YES+1",
}


def first_youtube_video_id(query, http_get=None, timeout=15):
    """Lấy videoId của kết quả ĐẦU TIÊN bằng cách đọc HTML trang kết quả.

    Thay cho pytube (hay vỡ khi YouTube đổi giao diện): trang kết quả nhúng sẵn
    ytInitialData chứa các "videoId":"...". Trả về id đầu tiên, hoặc None nếu
    không tải/không trích được. `http_get` cho phép tiêm hàm GET giả khi test.
    """
    encoded = urllib.parse.quote(query)
    url = f"https://www.youtube.com/results?search_query={encoded}"
    try:
        if http_get is not None:
            resp = http_get(url)
        else:
            import requests
            resp = requests.get(url, timeout=timeout, headers=_YT_HEADERS)
        text = resp.text
        for pattern in (_VIDEO_ID_RE, _WATCH_ID_RE):     # thử JSON trước, rồi link /watch
            match = pattern.search(text)
            if match:
                return match.group(1)
        logger.warning("Không thấy videoId trong trang kết quả cho '%s' "
                       "(YouTube có thể trả trang consent).", query)
        return None
    except Exception as e:
        logger.warning("Không trích được videoId cho '%s': %s", query, e)
        return None


def search_and_play_youtube_direct(query, http_get=None):
    """Mở THẲNG video đầu tiên khớp từ khóa; không được thì lùi về trang kết quả."""
    if not query:
        return "Chưa có từ khóa tìm kiếm."
    video_id = first_youtube_video_id(query, http_get=http_get)
    if video_id:
        webbrowser.open(f"https://www.youtube.com/watch?v={video_id}")
        return f"Đang phát video đầu tiên cho '{query}' trên YouTube."
    # Không trích được video: nói THẬT là chỉ mở trang kết quả (tránh AI báo nhầm đã phát).
    return search_and_play_youtube(query)
