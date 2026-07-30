"""Test phần logic thuần của window_control (khớp/lọc tên cửa sổ).

Không gọi win32 thật (test env có thể không có pywin32) — chỉ kiểm `_match_window`
với dữ liệu (hwnd, title) giả, và hành vi suy biến khi thiếu pywin32.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from actions.system import window_control as wc


WINDOWS = [
    (11, "Claude"),
    (22, "Google Chrome - YouTube"),
    (33, "Tài liệu - Word"),
    (44, "chrome extensions"),
]


def test_match_exact_wins_over_contains():
    # 'chrome' xuất hiện trong nhiều tiêu đề; khớp CHÍNH XÁC (không có) -> lấy 'bắt đầu bằng'
    hwnd, title = wc._match_window(WINDOWS, "chrome")
    assert (hwnd, title) == (44, "chrome extensions")  # bắt đầu bằng 'chrome'


def test_match_accent_insensitive():
    hwnd, title = wc._match_window(WINDOWS, "tai lieu")
    assert hwnd == 33


def test_match_case_insensitive_contains():
    hwnd, title = wc._match_window(WINDOWS, "youtube")
    assert hwnd == 22


def test_match_exact_full_title():
    hwnd, title = wc._match_window(WINDOWS, "claude")
    assert hwnd == 11


def test_match_none_when_no_hit():
    assert wc._match_window(WINDOWS, "firefox") is None


def test_match_empty_name():
    assert wc._match_window(WINDOWS, "   ") is None


def test_degrades_without_win32(monkeypatch):
    monkeypatch.setattr(wc, "win32gui", None)
    assert "Windows" in wc.list_windows()
    assert "Windows" in wc.switch_to_window("chrome")


def test_switch_requires_name(monkeypatch):
    # Có win32gui (giả) nhưng tên rỗng -> báo cần tên, không enum
    monkeypatch.setattr(wc, "win32gui", object())
    assert "Cần cho biết tên" in wc.switch_to_window("")
