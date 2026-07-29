"""Test giao thức lệnh Chrome (services.browser_protocol) — thuần, không mạng."""

try:
    import pytest
except ImportError:
    pytest = None

from services.browser_protocol import (
    build_media_command, normalize_media_action, summarize_media_response,
    summarize_tab_list, summarize_close,
    build_open_or_reuse, summarize_open_or_reuse, host_of, normalize_url,
    build_search_read, parse_search_results, summarize_search_results)


# --------------------------- build_media_command --------------------------- #

def test_build_simple_action():
    assert build_media_command("pause") == {"action": "CONTROL_MEDIA", "mediaAction": "PAUSE"}


def test_build_is_case_insensitive():
    assert build_media_command(" Toggle ")["mediaAction"] == "TOGGLE"


def test_build_set_volume_clamps():
    assert build_media_command("set_volume", 150)["value"] == 100.0
    assert build_media_command("set_volume", -5)["value"] == 0.0


def test_build_seek_keeps_negative():
    assert build_media_command("seek", -10)["value"] == -10.0


def test_build_invalid_action_raises():
    try:
        build_media_command("explode")
    except ValueError as e:
        assert "không hợp lệ" in str(e)
    else:
        raise AssertionError("phải ném ValueError")


def test_build_missing_value_raises():
    for act in ("set_volume", "seek"):
        try:
            build_media_command(act)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{act} thiếu value phải ném ValueError")


def test_build_non_numeric_value_raises():
    try:
        build_media_command("set_volume", "to")
    except ValueError:
        pass
    else:
        raise AssertionError("value phi số phải ném ValueError")


def test_normalize_unknown_returns_none():
    assert normalize_media_action("xyz") is None


# --------------------------- summarize_media_response --------------------------- #

def test_summary_success_pause():
    r = summarize_media_response({"success": True}, "pause")
    assert "tạm dừng" in r.lower() and "chrome" in r.lower()


def test_summary_success_set_volume_includes_value():
    r = summarize_media_response({"success": True}, "set_volume", 80)
    assert "80%" in r


def test_summary_error_no_media():
    r = summarize_media_response({"type": "ERROR", "message": "No active YouTube tab found."},
                                 "toggle")
    assert "không tìm thấy" in r.lower()


def test_summary_error_not_connected():
    r = summarize_media_response({"type": "ERROR", "message": "Chrome chưa kết nối"}, "play")
    assert "extension" in r.lower()


def test_summary_non_dict():
    assert "không nhận được" in summarize_media_response(None, "play").lower()


# --------------------------- Feature 1: tab list --------------------------- #

def test_tab_list_formats():
    resp = {"type": "TAB_LIST", "tabs": [
        {"id": 1, "title": "Facebook", "url": "https://www.facebook.com/x"},
        {"id": 2, "title": "YouTube", "url": "https://youtube.com/watch"}]}
    out = summarize_tab_list(resp)
    assert "2 tab" in out and "Facebook" in out and "www.facebook.com" in out


def test_tab_list_empty():
    assert "không có tab" in summarize_tab_list({"type": "TAB_LIST", "tabs": []}).lower()


def test_tab_list_error_not_connected():
    out = summarize_tab_list({"type": "ERROR", "message": "Chrome chưa kết nối"})
    assert "chưa kết nối" in out.lower()


# --------------------------- Feature 1: close (preview vs commit) --------------------------- #

def _close_resp(matched, dry, closed=None):
    r = {"type": "STATUS", "action": "CLOSE_TAB_BY_KEYWORD", "matched": matched, "dryRun": dry}
    if closed is not None:
        r["closedCount"] = closed
    return r


def test_close_preview_asks_confirmation_and_does_not_close():
    matched = [{"id": 1, "title": "Facebook", "url": "https://facebook.com"}]
    out = summarize_close(_close_resp(matched, dry=True), "facebook", confirm=False)
    assert "chắc" in out.lower() and "facebook" in out.lower()
    assert "đã đóng" not in out.lower()          # xem trước KHÔNG được nói đã đóng


def test_close_no_match():
    out = summarize_close(_close_resp([], dry=True), "abcxyz", confirm=False)
    assert "không tìm thấy" in out.lower()


def test_close_commit_reports_closed_count():
    matched = [{"id": 1, "title": "FB", "url": "x"}, {"id": 2, "title": "FB2", "url": "y"}]
    out = summarize_close(_close_resp(matched, dry=False, closed=2), "fb", confirm=True)
    assert "đã đóng 2 tab" in out.lower()


def test_close_error():
    out = summarize_close({"type": "ERROR", "message": "boom"}, "x", confirm=True)
    assert "lỗi" in out.lower()


# --------------------------- Feature 2: open-or-reuse --------------------------- #

def test_normalize_and_host():
    assert normalize_url("youtube.com") == "https://youtube.com"
    assert normalize_url("https//x.com") == "https://x.com"
    assert host_of("https://www.youtube.com/watch?v=x") == "youtube.com"
    assert host_of("music.youtube.com/x") == "music.youtube.com"


def test_build_open_derives_domain():
    cmd = build_open_or_reuse("https://www.youtube.com/watch?v=abc")
    assert cmd == {"action": "OPEN_OR_REUSE_URL",
                   "targetDomain": "youtube.com",
                   "newUrl": "https://www.youtube.com/watch?v=abc"}


def test_build_open_adds_scheme():
    assert build_open_or_reuse("example.org/x")["newUrl"] == "https://example.org/x"


def test_build_open_explicit_domain():
    cmd = build_open_or_reuse("https://youtube.com/watch?v=x", match_domain="youtube.com")
    assert cmd["targetDomain"] == "youtube.com"


def test_build_open_empty_raises():
    for bad in ("", "   ", None):
        try:
            build_open_or_reuse(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("URL rỗng phải ném ValueError")


def test_summary_open_reused():
    out = summarize_open_or_reuse(
        {"reused": True, "url": "https://youtube.com/watch?v=x"}, "youtube.com/watch?v=x")
    assert "dùng lại" in out.lower() and "youtube.com" in out


def test_summary_open_new():
    out = summarize_open_or_reuse({"reused": False, "url": "https://x.com"}, "x.com")
    assert "tab mới" in out.lower()


def test_summary_open_error():
    out = summarize_open_or_reuse({"type": "ERROR", "message": "Chrome chưa kết nối"}, "x.com")
    assert "chưa kết nối" in out.lower()


# --------------------------- Feature 3: tìm + đọc kết quả --------------------------- #

def test_build_search_read_defaults_google():
    cmd = build_search_read("toeic speaking")
    assert cmd == {"action": "SEARCH_READ", "query": "toeic speaking",
                   "engine": "google", "limit": 5}


def test_build_search_read_engine_and_limit():
    cmd = build_search_read("x", engine="duckduckgo", limit=3)
    assert cmd["engine"] == "duckduckgo" and cmd["limit"] == 3


def test_build_search_read_unknown_engine_falls_back():
    assert build_search_read("x", engine="yahoo")["engine"] == "google"


def test_build_search_read_limit_clamped():
    assert build_search_read("x", limit=99)["limit"] == 10
    assert build_search_read("x", limit=0)["limit"] == 1


def test_build_search_read_empty_query_raises():
    import pytest as _pt
    with _pt.raises(ValueError):
        build_search_read("   ")


def test_parse_search_results_filters_and_defaults_title():
    resp = {"type": "STATUS", "results": [
        {"title": "A", "url": "https://a.com"},
        {"title": "", "url": "https://b.com/x"},     # thiếu title -> lấy tên miền
        {"title": "no url", "url": ""},               # thiếu url -> loại
    ]}
    results, err = parse_search_results(resp)
    assert err is None
    assert results == [{"title": "A", "url": "https://a.com"},
                       {"title": "b.com", "url": "https://b.com/x"}]


def test_parse_search_results_error_response():
    results, err = parse_search_results({"type": "ERROR", "message": "Chrome chưa kết nối"})
    assert results == [] and "chưa kết nối" in err.lower()


def test_summarize_search_results_numbered_and_asks():
    out = summarize_search_results(
        [{"title": "Kết quả A", "url": "https://a"},
         {"title": "Kết quả B", "url": "https://b"}], "toeic")
    assert "1. Kết quả A" in out and "2. Kết quả B" in out
    assert "số mấy" in out.lower()


def test_summarize_search_results_empty():
    assert "không đọc được" in summarize_search_results([], "abc").lower()


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
