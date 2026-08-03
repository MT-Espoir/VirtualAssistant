"""Test phần LOGIC của cầu nối MCP (không cần server thật): heuristic destructive, trích
kết quả, và đăng ký MCP tool vào registry — dùng MCPClient GIẢ."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.mcp_bridge import is_destructive_tool, _extract_text
from agent.tools import build_default_registry


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
    reg = build_default_registry(MagicMock(), mcp=FakeMCP([
        _tool("gcal_list_events"), _tool("gmail_send")]))
    assert reg.has("gcal_list_events") and reg.has("gmail_send")
    assert reg.get("gcal_list_events").destructive is False
    assert reg.get("gmail_send").destructive is True        # 'send' -> hỏi xác nhận
    assert "gmail_send" in reg.get("gmail_send").confirm_message()


def test_mcp_handler_calls_through():
    mcp = FakeMCP([_tool("gcal_list_events")], results={"gcal_list_events": "Có 3 sự kiện."})
    reg = build_default_registry(MagicMock(), mcp=mcp)
    out = reg.run("gcal_list_events", {"date": "today"})
    assert out == "Có 3 sự kiện." and mcp.calls == [("gcal_list_events", {"date": "today"})]


def test_mcp_duplicate_name_skipped_not_crash():
    # MCP server phơi tool trùng tên tool sẵn có -> bỏ qua, giữ tool gốc, không lỗi
    reg = build_default_registry(MagicMock(), mcp=FakeMCP([_tool("open_app")]))
    assert reg.has("open_app")


def test_mcp_absent_without_client():
    assert not build_default_registry(MagicMock()).has("gcal_list_events")
