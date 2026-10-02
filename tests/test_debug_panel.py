"""Phần thuần của pipeline debug; không dựng Tkinter và không cần màn hình."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from agent.tools import Tool, ToolRegistry
from agent.agent import Agent
from llm.client import AssistantTurn
from features.salm.models import (ActivityKind, ActivitySnapshot, Confidence,
                                  DerivedState, DisplayState, MediaKind, Presence)
from features.salm.runtime import SalmRuntime
from ui.debug_panel import event_tabs, format_event
from utils.events import AssistantBus


def test_debug_event_che_secret_va_giu_thu_tu():
    bus = AssistantBus()
    bus.emit_debug("tool", "gọi API", {
        "api_key": "khong-duoc-hien",
        "nested": {"access_token": "cung-khong", "ok": 7},
    })
    event = bus.drain_debug()[0]
    assert bus.drain() == []       # debug không làm nhiễu queue chức năng của avatar
    assert event["category"] == "tool"
    assert event["data"]["api_key"] == "<đã che>"
    assert event["data"]["nested"] == {"access_token": "<đã che>", "ok": 7}


def test_phan_loai_tab_va_format_event():
    assert event_tabs("tool") == ("all", "tools")
    assert event_tabs("activity") == ("all", "activity")
    assert event_tabs("la") == ("all", "system")
    shown = format_event({
        "time": "2026-09-18T20:10:11.123+07:00",
        "category": "assistant", "level": "INFO",
        "message": "Trợ lý: xong", "data": {"emotion": "happy"},
    })
    assert "20:10:11.123" in shown
    assert "Trợ lý: xong" in shown
    assert '"emotion": "happy"' in shown


def test_llm_raw_response_shows_blank_lines_as_literal_escape_before_cleanup():
    class _LLM:
        def generate(self, **_kwargs):
            return AssistantTurn(text="Câu một.\n\nCâu hai.\n#emotion: happy")

    seen = []
    registry = ToolRegistry()
    registry.set_debug_sink(
        lambda category, message, data, level="INFO":
        seen.append({"category": category, "message": message,
                     "data": data, "level": level}))

    reply = Agent(_LLM(), registry).run("trả lời thử")

    event = next(item for item in seen if item["category"] == "llm")
    assert "\\n\\n" in event["message"]
    assert "Câu một.\n\nCâu hai." not in event["message"]
    assert event["data"]["line_breaks"] == 3
    assert event["data"]["blank_line_boundaries"] == 1
    assert event["data"]["duration_ms"] >= 0
    assert reply.text == "Câu một.\nCâu hai."


def test_llm_category_is_routed_to_main_conversation_tab():
    assert event_tabs("llm") == ("all", "conversation")


def test_say_logs_exact_tts_text_and_total_duration():
    import app

    class _Synth:
        def __init__(self):
            self.spoken = []

        def speak_sync(self, text):
            self.spoken.append(text)

    bus, synth = AssistantBus(), _Synth()
    app._say(synth, bus, "Câu một.\nCâu hai.", "happy")
    events = bus.drain_debug()

    assert synth.spoken == ["Câu một.\nCâu hai."]
    assert "Câu một.\\nCâu hai." in events[0]["message"]
    assert events[0]["data"]["line_breaks"] == 1
    assert events[0]["data"]["blank_line_boundaries"] == 0
    assert events[-1]["message"] == "TTS hoàn tất"
    assert events[-1]["data"]["duration_ms"] >= 0


def test_registry_phat_tool_start_va_result():
    seen = []
    registry = ToolRegistry()
    registry.register(Tool("cong", "", {"type": "object"},
                           lambda a=0, b=0: a + b))
    registry.set_debug_sink(
        lambda category, message, data, level="INFO":
        seen.append((category, message, data, level)))

    assert registry.run("cong", {"a": 2, "b": 3}) == 5
    assert [item[1] for item in seen] == ["Bắt đầu cong", "Hoàn tất cong"]
    assert seen[-1][2]["result"] == "5"
    assert seen[-1][3] == "SUCCESS"


def test_registry_phat_tool_error_roi_nem_lai():
    seen = []
    registry = ToolRegistry()

    def fail():
        raise ValueError("hỏng")

    registry.register(Tool("fail", "", {"type": "object"}, fail))
    registry.set_debug_sink(
        lambda category, message, data, level="INFO":
        seen.append((message, data, level)))
    with pytest.raises(ValueError, match="hỏng"):
        registry.run("fail", {})
    assert seen[-1][0] == "Tool lỗi: fail"
    assert seen[-1][2] == "ERROR"
    assert "ValueError" in seen[-1][1]["error"]


def test_salm_chi_phat_khi_trang_thai_nhan_dien_thay_doi():
    seen = []
    runtime = SalmRuntime.__new__(SalmRuntime)
    runtime.on_debug = lambda category, message, data, level="INFO": seen.append(data)
    runtime._last_debug_signature = None
    runtime.gate = SimpleNamespace(reasons=lambda _scope: ())
    now = datetime.now().astimezone()
    snapshot = ActivitySnapshot(
        monotonic=1.0, wall_time=now, idle_seconds=2.0,
        foreground_app="code", display=DisplayState.ON)
    state = DerivedState(
        presence=Presence.PRESENT, display=DisplayState.ON,
        activity=ActivityKind.ACTIVE_INTERACTIVE, media=MediaKind.NONE,
        primary_app="code", confidence=Confidence.HIGH,
        evidence=("recent_input",), since_monotonic=1.0, since_wall=now)

    runtime._emit_activity_change(snapshot, state, {"work_engagement": 12.0})
    runtime._emit_activity_change(snapshot, state, {"work_engagement": 13.0})
    assert len(seen) == 1
    assert seen[0]["foreground_app"] == "code"
    assert seen[0]["activity"] == "active_interactive"
