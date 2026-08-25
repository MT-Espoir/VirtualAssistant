"""Test đọc/điều khiển màn hình: phần THUẦN (search_text/summarize) + đăng ký tool."""

try:
    import pytest
except ImportError:
    pytest = None

from actions.screen_control import search_text, summarize_find
from agent.tools import build_default_registry
from conftest import registry_with


# --------------------------- search_text (thuần) --------------------------- #

OCR = "Tong quan du an\nBao cao doanh thu Quy 4\nLỢI NHUẬN: 1.2 tỷ\nGhi chú cuối trang"


def test_search_finds_line_case_insensitive():
    assert search_text(OCR, "doanh thu") == ["Bao cao doanh thu Quy 4"]


def test_search_ignores_accents():
    # 'loi nhuan' (không dấu) khớp 'LỢI NHUẬN' (có dấu, hoa)
    assert search_text(OCR, "loi nhuan") == ["LỢI NHUẬN: 1.2 tỷ"]


def test_search_multiple_matches():
    assert len(search_text("abc x\nx def\nno match\nx", "x")) == 3


def test_search_empty_query_or_text():
    assert search_text(OCR, "") == []
    assert search_text("", "x") == []
    assert search_text(OCR, "khongcotutnay") == []


def test_summarize_found_and_not_found():
    assert "Không thấy" in summarize_find([], "abc")
    s = summarize_find(["dòng 1", "dòng 2"], "abc")
    assert "Tìm thấy 'abc'" in s and "2 dòng" in s


def test_summarize_truncates_long_list():
    s = summarize_find([f"d{i}" for i in range(10)], "x", limit=3)
    assert "và 7 dòng nữa" in s


# --------------------------- đăng ký tool (browser giả) --------------------------- #

class _FakeActions:
    def __getattr__(self, name):
        return lambda *a, **k: "noop"


class _FakeScreen:
    def __init__(self):
        self.calls = []
    def capture(self):
        self.calls.append(("capture",)); return "Đã chụp màn hình 1920x1080, lưu tại: x.png"
    def find(self, query):
        self.calls.append(("find", query)); return f"Tìm thấy '{query}'..."
    def scroll(self, direction, amount=3):
        self.calls.append(("scroll", direction, amount)); return f"Đã cuộn {direction} {amount} nấc."


def _registry(screen):
    return registry_with(actions=_FakeActions(), screen=screen)


def test_screen_tools_registered_only_with_screen():
    assert "take_screenshot" not in [s["name"] for s in _registry(None).specs()]
    names = [s["name"] for s in _registry(_FakeScreen()).specs()]
    assert {"take_screenshot", "find_on_screen", "scroll_screen"} <= set(names)


def test_screenshot_tool_calls_capture():
    sc = _FakeScreen()
    out = _registry(sc).run("take_screenshot", {})
    assert sc.calls == [("capture",)] and "chụp màn hình" in out.lower()


def test_find_tool_passes_query():
    sc = _FakeScreen()
    _registry(sc).run("find_on_screen", {"query": "doanh thu"})
    assert sc.calls == [("find", "doanh thu")]


def test_scroll_tool_default_amount():
    sc = _FakeScreen()
    _registry(sc).run("scroll_screen", {"direction": "down"})
    assert sc.calls == [("scroll", "down", 3)]


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
