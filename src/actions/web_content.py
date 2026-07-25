"""
Đọc & tra cứu nội dung web cho agent (để LLM tóm tắt/ trả lời).

- fetch_url_text(url): tải một trang, trích văn bản đọc được (dùng html.parser
  stdlib — không cần bs4), cắt bớt để vừa ngữ cảnh LLM.
- wikipedia_summary(topic): tra cứu nhanh trên Wikipedia qua REST API (trả JSON
  có sẵn đoạn tóm tắt, không scraping).

`http_get` cho phép tiêm hàm GET giả khi test (không cần requests/mạng).
"""

from html.parser import HTMLParser
from urllib.parse import quote

from utils.logger import get_logger

logger = get_logger(__name__)

_UA = "Mozilla/5.0 (VirtualAssistant)"


class _TextExtractor(HTMLParser):
    """Gom text hiển thị, bỏ qua script/style/head."""
    _SKIP = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            t = data.strip()
            if t:
                self.parts.append(t)

    def text(self):
        return " ".join(self.parts)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception as e:  # HTML hỏng không được làm vỡ
        logger.debug("Lỗi phân tích HTML: %s", e)
    return parser.text()


def _get(url, http_get=None, timeout=15):
    if http_get is not None:
        return http_get(url)
    import requests
    return requests.get(url, timeout=timeout, headers={"User-Agent": _UA})


def fetch_url_text(url: str, max_chars: int = 3000, http_get=None) -> str:
    """Tải một URL và trả về văn bản đọc được (đã cắt bớt)."""
    if not url or not str(url).startswith(("http://", "https://")):
        return "URL không hợp lệ (cần bắt đầu bằng http:// hoặc https://)."
    try:
        resp = _get(url, http_get)
        html = resp.text
    except Exception as e:
        logger.error("web_fetch lỗi khi tải %s: %s", url, e)
        return f"Không tải được trang: {e}"

    text = html_to_text(html)
    if len(text) > max_chars:
        text = text[:max_chars] + "…"
    return text or "Trang không có nội dung văn bản đọc được."


def wikipedia_summary(topic: str, lang: str = "vi", http_get=None) -> str:
    """Trả về đoạn tóm tắt Wikipedia cho chủ đề (REST API, không scraping)."""
    if not topic:
        return "Cần cho biết chủ đề cần tra cứu."
    url = (f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
           f"{quote(topic.strip().replace(' ', '_'))}")
    try:
        resp = _get(url, http_get)
        data = resp.json()
    except Exception as e:
        logger.error("wikipedia lỗi: %s", e)
        return f"Không tra cứu được: {e}"

    if data.get("extract"):
        return data["extract"]
    return f"Không tìm thấy '{topic}' trên Wikipedia."
