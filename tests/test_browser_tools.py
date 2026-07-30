"""Test tool điều khiển Chrome đăng ký trong registry (dùng browser giả)."""

try:
    import pytest
except ImportError:
    pytest = None

from agent.tools import build_default_registry


class _FakeActions:
    """Facade tối thiểu — build_default_registry cần một actions, nhưng test này
    chỉ quan tâm tool browser nên các method khác không bị gọi."""
    def __getattr__(self, name):
        return lambda *a, **k: "noop"


class _FakeBrowser:
    """Ghi lại lệnh gửi + trả phản hồi định trước để kiểm tra tool."""
    def __init__(self, response):
        self.response = response
        self.sent = None

    def send_command(self, **kwargs):
        self.sent = kwargs
        return self.response


class _ScriptBrowser:
    """Trả phản hồi khác nhau theo 'action' của lệnh (mô phỏng nhiều bước)."""
    def __init__(self, by_action):
        self.by_action = by_action
        self.sent = []

    def send_command(self, **kwargs):
        self.sent.append(kwargs)
        return self.by_action.get(kwargs.get("action"), {})


def _registry(browser):
    return build_default_registry(_FakeActions(), scheduler=None, browser=browser)


def test_browser_tool_registered_only_with_browser():
    assert "browser_media_control" not in [s["name"] for s in _registry(None).specs()]
    br = _FakeBrowser({"success": True})
    assert "browser_media_control" in [s["name"] for s in _registry(br).specs()]


def test_media_control_sends_correct_command():
    br = _FakeBrowser({"success": True})
    reg = _registry(br)
    out = reg.run("browser_media_control", {"action": "toggle"})
    assert br.sent == {"action": "CONTROL_MEDIA", "mediaAction": "TOGGLE"}
    assert "chrome" in out.lower()


def test_media_control_set_volume_passes_value():
    br = _FakeBrowser({"success": True})
    reg = _registry(br)
    out = reg.run("browser_media_control", {"action": "set_volume", "value": 80})
    assert br.sent["mediaAction"] == "SET_VOLUME" and br.sent["value"] == 80.0
    assert "80%" in out


def test_media_control_invalid_action_no_send():
    br = _FakeBrowser({"success": True})
    reg = _registry(br)
    out = reg.run("browser_media_control", {"action": "explode"})
    assert br.sent is None                      # không gửi lệnh sai xuống Chrome
    assert "không hợp lệ" in out.lower()


def test_media_control_reports_error_response():
    br = _FakeBrowser({"type": "ERROR", "message": "No active YouTube tab found."})
    reg = _registry(br)
    out = reg.run("browser_media_control", {"action": "pause"})
    assert "không tìm thấy" in out.lower()


# --------------------------- Feature 1: tab tools --------------------------- #

def test_tab_tools_registered_with_browser():
    names = [s["name"] for s in _registry(_FakeBrowser({})).specs()]
    assert "browser_list_tabs" in names and "browser_close_tab" in names


def test_list_tabs_sends_get_tabs():
    br = _FakeBrowser({"type": "TAB_LIST", "tabs": []})
    reg = _registry(br)
    reg.run("browser_list_tabs", {})
    assert br.sent == {"action": "GET_TABS"}


def test_close_tab_default_is_dry_run_preview():
    # confirm không truyền -> dryRun=True (chỉ xem trước, không đóng)
    matched = [{"id": 1, "title": "Facebook", "url": "https://facebook.com"}]
    br = _FakeBrowser({"type": "STATUS", "matched": matched, "dryRun": True})
    reg = _registry(br)
    out = reg.run("browser_close_tab", {"keyword": "facebook"})
    assert br.sent["action"] == "CLOSE_TAB_BY_KEYWORD"
    assert br.sent["dryRun"] is True             # mặc định KHÔNG đóng thật
    assert "chắc" in out.lower()


def test_close_tab_confirm_true_actually_closes():
    matched = [{"id": 1, "title": "Facebook", "url": "https://facebook.com"}]
    br = _FakeBrowser({"type": "STATUS", "matched": matched, "dryRun": False, "closedCount": 1})
    reg = _registry(br)
    out = reg.run("browser_close_tab", {"keyword": "facebook", "confirm": True})
    assert br.sent["dryRun"] is False
    assert "đã đóng" in out.lower()


def test_close_tab_empty_keyword_no_send():
    br = _FakeBrowser({})
    reg = _registry(br)
    out = reg.run("browser_close_tab", {"keyword": "   "})
    assert br.sent is None and "từ khoá" in out.lower()


# --------------------------- Feature 2: open-or-reuse tool --------------------------- #

def test_open_reuse_registered():
    assert "browser_open_or_reuse" in [s["name"] for s in _registry(_FakeBrowser({})).specs()]


def test_open_reuse_sends_derived_domain():
    br = _FakeBrowser({"reused": True, "url": "https://www.youtube.com/watch?v=x"})
    reg = _registry(br)
    out = reg.run("browser_open_or_reuse", {"url": "https://www.youtube.com/watch?v=x"})
    assert br.sent == {"action": "OPEN_OR_REUSE_URL", "targetDomain": "youtube.com",
                       "newUrl": "https://www.youtube.com/watch?v=x"}
    assert "dùng lại" in out.lower()


def test_open_reuse_new_tab_summary():
    br = _FakeBrowser({"reused": False, "url": "https://example.org"})
    reg = _registry(br)
    out = reg.run("browser_open_or_reuse", {"url": "example.org"})
    assert br.sent["newUrl"] == "https://example.org"
    assert "tab mới" in out.lower()


def test_open_reuse_empty_url_no_send():
    br = _FakeBrowser({})
    reg = _registry(br)
    out = reg.run("browser_open_or_reuse", {"url": "  "})
    assert br.sent is None and "url" in out.lower()


# --------------------------- Feature 3: tìm + đọc + chọn kết quả --------------------------- #

_SEARCH_RESP = {"type": "STATUS", "results": [
    {"title": "TOEIC Speaking A", "url": "https://a.com/1"},
    {"title": "TOEIC Speaking B", "url": "https://b.com/2"},
]}


def test_web_search_tools_registered_with_browser():
    names = [s["name"] for s in _registry(_FakeBrowser(_SEARCH_RESP)).specs()]
    assert "web_search_list" in names and "open_search_result" in names
    assert "web_search_list" not in [s["name"] for s in _registry(None).specs()]


def test_search_list_sends_command_and_reads_titles():
    br = _FakeBrowser(_SEARCH_RESP)
    reg = _registry(br)
    out = reg.run("web_search_list", {"query": "toeic speaking"})
    assert br.sent["action"] == "SEARCH_READ" and br.sent["query"] == "toeic speaking"
    assert "1. TOEIC Speaking A" in out and "2. TOEIC Speaking B" in out


def test_open_result_uses_stored_state_across_calls():
    # web_search_list lưu state -> open_search_result mở đúng URL theo SỐ (không cần URL)
    br = _ScriptBrowser({"SEARCH_READ": _SEARCH_RESP,
                         "OPEN_OR_REUSE_URL": {"reused": False, "url": "https://b.com/2"}})
    reg = _registry(br)
    reg.run("web_search_list", {"query": "toeic"})
    out = reg.run("open_search_result", {"index": 2})
    opened = [c for c in br.sent if c["action"] == "OPEN_OR_REUSE_URL"]
    assert opened and opened[-1]["newUrl"] == "https://b.com/2"
    assert "số 2" in out and "TOEIC Speaking B" in out


def test_open_result_without_prior_search():
    br = _FakeBrowser(_SEARCH_RESP)
    reg = _registry(br)
    out = reg.run("open_search_result", {"index": 1})
    assert "chưa có kết quả" in out.lower()


def test_open_result_index_out_of_range():
    br = _ScriptBrowser({"SEARCH_READ": _SEARCH_RESP})
    reg = _registry(br)
    reg.run("web_search_list", {"query": "toeic"})
    out = reg.run("open_search_result", {"index": 9})
    assert "chỉ có 2 kết quả" in out.lower()


def test_search_list_reports_connection_error():
    br = _FakeBrowser({"type": "ERROR", "message": "Chrome chưa kết nối"})
    reg = _registry(br)
    out = reg.run("web_search_list", {"query": "x"})
    assert "chưa kết nối" in out.lower()


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
