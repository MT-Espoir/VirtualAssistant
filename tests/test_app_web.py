"""
Test ánh xạ mở app/web (đọc applications.json / websites.json thật qua DataLoader).

Không cần requests/bs4/pytube (đã bỏ import chết ở web_search); webbrowser được
mock để không thực sự mở trình duyệt.
"""

try:
    import pytest
except ImportError:
    pytest = None

from actions.system.app_control import resolve_app_command
from actions.web import web_search


# --------------------------- resolve_app_command --------------------------- #

def test_app_alias_to_executable():
    assert resolve_app_command("google chrome") == "chrome"
    assert resolve_app_command("trình duyệt google") == "chrome"


def test_app_vietnamese_name():
    assert resolve_app_command("văn bản") == "winword"   # word -> winword
    assert resolve_app_command("máy tính") == "calc"      # calculator -> calc


def test_app_canonical_name():
    assert resolve_app_command("excel") == "excel"
    assert resolve_app_command("edge") == "msedge"


def test_app_unknown_returns_raw():
    assert resolve_app_command("phần mềm lạ xyz") == "phần mềm lạ xyz"


# --------------------------- resolve_website_url --------------------------- #

def test_web_canonical():
    assert web_search.resolve_website_url("youtube") == "https://www.youtube.com"


def test_web_alias():
    assert web_search.resolve_website_url("yt") == "https://www.youtube.com"
    assert web_search.resolve_website_url("fb") == "https://www.facebook.com"


def test_web_unknown_guesses_domain():
    assert web_search.resolve_website_url("trangla") == "https://www.trangla.com"


def test_web_domain_passthrough():
    assert web_search.resolve_website_url("example.com") == "https://example.com"


# --------------------------- resolve_website_url: chuẩn hoá scheme --------------------------- #

def test_web_fixes_missing_colon_scheme():
    # 'https//...' (thiếu dấu ':') -> sửa, KHÔNG ghép 'https://' hai lần
    assert web_search.resolve_website_url("https//www.youtube.com") == "https://www.youtube.com"


def test_web_keeps_existing_scheme():
    assert web_search.resolve_website_url("https://www.youtube.com") == "https://www.youtube.com"


# --------------------------- open_website (mock webbrowser) --------------------------- #

def test_open_website_uses_resolved_url():
    opened = {}
    orig = web_search.webbrowser.open
    web_search.webbrowser.open = lambda url: opened.setdefault("url", url)
    try:
        msg = web_search.open_website("yt")
        assert opened["url"] == "https://www.youtube.com"   # vẫn mở đúng URL
        # UX: câu trả lời KHÔNG chứa full URL (dài, khó nghe khi TTS đọc), chỉ tên trang.
        assert "http" not in msg and "yt" in msg
    finally:
        web_search.webbrowser.open = orig


# --------------------------- YouTube: trích videoId (thay pytube) --------------------------- #

class _FakeResp:
    def __init__(self, text):
        self.text = text


def test_first_video_id_extracts_first_match():
    html = 'junk "videoId":"abcABC123_-" more "videoId":"zzzzzzzzzzz" end'
    got = web_search.first_youtube_video_id("bài hát", http_get=lambda url: _FakeResp(html))
    assert got == "abcABC123_-"


def test_first_video_id_none_when_absent():
    got = web_search.first_youtube_video_id("x", http_get=lambda url: _FakeResp("không có gì"))
    assert got is None


def test_first_video_id_fallback_watch_link():
    # Không có "videoId":"..." nhưng có link /watch?v= -> vẫn trích được (regex dự phòng)
    html = 'no json here but <a href="/watch?v=abcABC123_-">clip</a>'
    got = web_search.first_youtube_video_id("x", http_get=lambda url: _FakeResp(html))
    assert got == "abcABC123_-"


def test_first_video_id_none_on_network_error():
    def boom(url):
        raise OSError("mạng lỗi")
    assert web_search.first_youtube_video_id("x", http_get=boom) is None


def test_play_direct_opens_watch_url_when_found():
    opened = {}
    orig = web_search.webbrowser.open
    web_search.webbrowser.open = lambda url: opened.setdefault("url", url)
    try:
        html = '"videoId":"abcABC123_-"'
        msg = web_search.search_and_play_youtube_direct(
            "lấp lánh", http_get=lambda url: _FakeResp(html))
        assert opened["url"] == "https://www.youtube.com/watch?v=abcABC123_-"
        assert "Đang phát" in msg
    finally:
        web_search.webbrowser.open = orig


def test_play_direct_falls_back_to_results_when_not_found():
    opened = {}
    orig = web_search.webbrowser.open
    web_search.webbrowser.open = lambda url: opened.setdefault("url", url)
    try:
        msg = web_search.search_and_play_youtube_direct(
            "abc", http_get=lambda url: _FakeResp("trống"))
        assert "results?search_query=" in opened["url"]
        assert "chưa phát" in msg      # thông điệp trung thực, không báo đã phát
    finally:
        web_search.webbrowser.open = orig


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print("PASS", _name)
            except Exception as _e:  # noqa: BLE001
                failures += 1
                print("FAIL", _name, "->", repr(_e))
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    raise SystemExit(1 if failures else 0)
