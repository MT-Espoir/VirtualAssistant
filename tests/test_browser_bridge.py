"""Test guardrail Origin của cầu nối WebSocket: chỉ nhận extension, chặn website độc."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.browser_bridge import is_origin_allowed


def test_allows_chrome_extension_origin():
    assert is_origin_allowed("chrome-extension://abcdefghijklmnop")


def test_allows_no_origin_client():
    # Client không phải trình duyệt (test/native tin cậy) không gửi Origin
    assert is_origin_allowed(None)
    assert is_origin_allowed("")


def test_blocks_website_origins():
    for bad in ("https://evil.com", "http://localhost:3000",
                "https://accounts.google.com", "http://127.0.0.1:8765"):
        assert not is_origin_allowed(bad), bad
