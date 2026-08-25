"""Test phần LOGIC của cầu nối MCP (không cần server thật): heuristic destructive, trích
kết quả, và đăng ký MCP tool vào registry — dùng MCPClient GIẢ."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.mcp_bridge import is_destructive_tool, _extract_text
from agent.tools import build_default_registry
from conftest import registry_with


class FakeMCP:
    """MCPClient giả: list_tools/call_tool trả dữ liệu định sẵn (không kết nối thật)."""
    def __init__(self, tools, results=None):
        self._tools = tools
        self.results = results or {}
        self.calls = []

    def list_tools(self):
        return list(self._tools)

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.results.get(name, f"ran {name}")


def _tool(name, desc="mô tả"):
    return {"name": name, "description": desc, "input_schema": {"type": "object", "properties": {}}}


# --------------------------- heuristic destructive --------------------------- #

def test_is_destructive_by_name():
    for w in ("gmail_send_email", "gcal_create_event", "gcal_delete_event", "gmail_trash"):
        assert is_destructive_tool(w), w
    for r in ("gcal_list_events", "gmail_read_message", "gcal_get_event"):
        assert not is_destructive_tool(r), r


# --------------------------- trích kết quả --------------------------- #

def test_extract_text_joins():
    r = SimpleNamespace(content=[SimpleNamespace(text="dòng 1"), SimpleNamespace(text="dòng 2")],
                        isError=False)
    assert _extract_text(r) == "dòng 1\ndòng 2"


def test_extract_text_error_flag():
    r = SimpleNamespace(content=[SimpleNamespace(text="hết quyền")], isError=True)
    assert "lỗi" in _extract_text(r).lower() and "hết quyền" in _extract_text(r)


def test_extract_text_empty():
    assert "không có nội dung" in _extract_text(SimpleNamespace(content=[], isError=False))


# --------------------------- đăng ký MCP tool --------------------------- #

def test_register_bridges_tools_and_marks_destructive():
    reg = registry_with(mcp=FakeMCP([
        _tool("gcal_list_events"), _tool("gmail_send")]))
    assert reg.has("gcal_list_events") and reg.has("gmail_send")
    assert reg.get("gcal_list_events").destructive is False
    assert reg.get("gmail_send").destructive is True        # 'send' -> hỏi xác nhận
    assert "gmail_send" in reg.get("gmail_send").confirm_message()


def test_mcp_handler_calls_through():
    mcp = FakeMCP([_tool("gcal_list_events")], results={"gcal_list_events": "Có 3 sự kiện."})
    reg = registry_with(mcp=mcp)
    out = reg.run("gcal_list_events", {"date": "today"})
    assert out == "Có 3 sự kiện." and mcp.calls == [("gcal_list_events", {"date": "today"})]


def test_mcp_duplicate_name_skipped_not_crash():
    # MCP server phơi tool trùng tên tool sẵn có -> bỏ qua, giữ tool gốc, không lỗi
    reg = registry_with(mcp=FakeMCP([_tool("open_app")]))
    assert reg.has("open_app")


def test_mcp_absent_without_client():
    assert not build_default_registry(MagicMock()).has("gcal_list_events")


# --------------------------- nháp email -> panel xem trước --------------------------- #

_MAIL = {"to": "sep@x.com", "subject": "Xin nghỉ phép", "body": "Kính gửi anh..."}


def test_email_send_tool_gets_a_preview():
    # Dò theo HÌNH DẠNG THAM SỐ, không theo tên tool -> server MCP nào cũng nhận đúng.
    reg = registry_with(mcp=FakeMCP([_tool("gws_gmail_send")]))
    assert reg.get("gws_gmail_send").preview(**_MAIL) == _MAIL


def test_email_confirm_phrase_is_human_not_tool_name():
    reg = registry_with(mcp=FakeMCP([_tool("gws_gmail_send")]))
    phrase = reg.get("gws_gmail_send").confirm_message(**_MAIL)
    assert "gửi email" in phrase and "sep@x.com" in phrase
    assert "gws_gmail_send" not in phrase          # không đọc tên tool máy móc cho người nghe


def test_non_email_destructive_tool_has_no_preview_payload():
    reg = registry_with(mcp=FakeMCP([_tool("gcal_create_event")]))
    tool = reg.get("gcal_create_event")
    assert tool.preview(summary="Họp", start="2026-08-25T09:00") is None
    assert "gcal_create_event" in tool.confirm_message(summary="Họp")


def test_read_only_tool_yields_no_preview_payload():
    reg = registry_with(mcp=FakeMCP([_tool("gcal_list_events")]))
    assert reg.get("gcal_list_events").preview(date="today") is None


# HỒI QUY: người dùng nói "viết mail xin hướng dẫn đồ án" -> chỉ ĐỌC, không
# hiện panel. Nguyên nhân: 'gws_gmail_draft' không chứa từ khoá GHI nào ('send/create/
# delete'...) nên bị xếp là chỉ-đọc -> không cổng duyệt -> không panel. Mà LƯU NHÁP chính
# là lúc cần nhìn bản nháp nhất.
def test_draft_tool_is_not_flagged_destructive_by_name():
    assert not is_destructive_tool("gws_gmail_draft")     # đúng như heuristic tên vốn thế


def test_draft_tool_still_gets_a_preview():
    reg = registry_with(mcp=FakeMCP([_tool("gws_gmail_draft")]))
    assert reg.get("gws_gmail_draft").preview(**_MAIL) == _MAIL


def test_draft_tool_confirm_phrase_says_save_not_send():
    # Đồng ý "lưu nháp" mà hệ thống gửi thật là kiểu phản bội tin cậy tệ nhất.
    reg = registry_with(mcp=FakeMCP([
        _tool("gws_gmail_draft"), _tool("gws_gmail_send")]))
    assert "lưu nháp" in reg.get("gws_gmail_draft").confirm_message(**_MAIL)
    assert "gửi email" in reg.get("gws_gmail_send").confirm_message(**_MAIL)


def test_draft_without_recipient_still_previews():
    # Ca thật của người dùng: "viết mail xin hướng dẫn đồ án" — chưa nói gửi cho ai.
    reg = registry_with(mcp=FakeMCP([_tool("gws_gmail_draft")]))
    payload = reg.get("gws_gmail_draft").preview(
        to="", subject="Xin hướng dẫn đồ án tốt nghiệp", body="Kính gửi thầy...")
    assert payload is not None and payload["to"] == ""
