"""
Test ánh xạ mở app/web (đọc applications.json / websites.json thật qua DataLoader).

Không cần requests/bs4/pytube (đã bỏ import chết ở web_search); webbrowser được
mock để không thực sự mở trình duyệt.
"""

try:
    import pytest
except ImportError:
    pytest = None

from actions.app_control import resolve_app_command
from actions import web_search


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


# --------------------------- open_website (mock webbrowser) --------------------------- #

def test_open_website_uses_resolved_url():
    opened = {}
    orig = web_search.webbrowser.open
    web_search.webbrowser.open = lambda url: opened.setdefault("url", url)
    try:
        msg = web_search.open_website("yt")
        assert opened["url"] == "https://www.youtube.com"
        assert "youtube.com" in msg
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
