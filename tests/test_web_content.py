"""
Test actions.web.web_content — trích văn bản HTML (html.parser stdlib) và tra cứu.

Dùng http_get giả (trả object có .text / .json()) nên không cần requests/mạng.
"""

try:
    import pytest
except ImportError:
    pytest = None

from actions.web.web_content import html_to_text, fetch_url_text, wikipedia_summary


class FakeResp:
    def __init__(self, text="", data=None):
        self.text = text
        self._data = data

    def json(self):
        return self._data


# --------------------------- html_to_text --------------------------- #

def test_html_to_text_strips_tags_and_scripts():
    html = "<html><head><title>t</title></head><body>" \
           "<script>var x=1;</script><h1>Tiêu đề</h1><p>Nội dung chính.</p></body></html>"
    text = html_to_text(html)
    assert "Tiêu đề" in text and "Nội dung chính." in text
    assert "var x" not in text and "<" not in text


# --------------------------- fetch_url_text --------------------------- #

def test_fetch_invalid_url():
    assert "không hợp lệ" in fetch_url_text("chrome://x")


def test_fetch_returns_text():
    resp = FakeResp(text="<p>Xin chào thế giới</p>")
    out = fetch_url_text("https://vd.com", http_get=lambda u: resp)
    assert out == "Xin chào thế giới"


def test_fetch_truncates():
    resp = FakeResp(text="<p>" + "a" * 5000 + "</p>")
    out = fetch_url_text("https://vd.com", max_chars=100, http_get=lambda u: resp)
    assert len(out) <= 101 + 1 and out.endswith("…")


def test_fetch_handles_error():
    def boom(u):
        raise RuntimeError("timeout")
    out = fetch_url_text("https://vd.com", http_get=boom)
    assert "Không tải được" in out and "timeout" in out


# --------------------------- wikipedia_summary --------------------------- #

def test_wikipedia_returns_extract():
    resp = FakeResp(data={"extract": "Python là một ngôn ngữ lập trình."})
    out = wikipedia_summary("Python", http_get=lambda u: resp)
    assert out == "Python là một ngôn ngữ lập trình."


def test_wikipedia_not_found():
    resp = FakeResp(data={"type": "https://mediawiki.org/wiki/HyperSwitch/errors/not_found"})
    out = wikipedia_summary("khong_ton_tai_xyz", http_get=lambda u: resp)
    assert "Không tìm thấy" in out


def test_wikipedia_empty_topic():
    assert "Cần cho biết" in wikipedia_summary("")


def test_wikipedia_error():
    def boom(u):
        raise RuntimeError("mạng lỗi")
    out = wikipedia_summary("Python", http_get=boom)
    assert "Không tra cứu được" in out


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
