"""Mở web / tìm kiếm — dữ liệu trang lấy từ websites.json qua DataLoader."""

import urllib.parse
import webbrowser

from utils.data_loader import DataLoader
from utils.logger import get_logger

logger = get_logger(__name__)

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
    return f"https://www.{key}.com" if "." not in key else f"https://{key}"


def open_website(site_name):
    """Mở trực tiếp một trang web theo tên."""
    url = resolve_website_url(site_name)
    webbrowser.open(url)
    return f"Đang mở {site_name} ({url})."


def search_and_play_youtube(query):
    """Mở trang kết quả YouTube cho từ khóa (không phụ thuộc pytube)."""
    if not query:
        return "Chưa có từ khóa tìm kiếm."
    encoded = urllib.parse.quote(query)
    webbrowser.open(f"https://www.youtube.com/results?search_query={encoded}")
    return f"Đang tìm '{query}' trên YouTube."


def search_and_play_youtube_direct(query):
    """Tìm và mở video đầu tiên qua pytube; nếu không được thì mở trang kết quả."""
    if not query:
        return "Chưa có từ khóa tìm kiếm."
    try:
        from pytube import Search
        results = Search(query).results
        if results:
            video = results[0]
            webbrowser.open(f"https://www.youtube.com/watch?v={video.video_id}")
            return f"Đang phát video '{video.title}'."
        return f"Không tìm thấy video cho '{query}'."
    except Exception as e:  # pytube hay hỏng khi YouTube đổi giao diện
        logger.warning("pytube lỗi (%s), mở trang kết quả thay thế.", e)
        return search_and_play_youtube(query)
