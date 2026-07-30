"""Test bộ khung eval (evals.harness) — LLM giả, không cần model thật/mạng."""

from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

from llm.client import AssistantTurn, ToolCall
from agent.tools import build_default_registry
from evals.harness import (
    RecordingRegistry, RecordingRouter, score_case, run_case, summarize)


class _FakeLLM:
    """Chạy theo kịch bản turn định trước (giống test_agent)."""
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def generate(self, *, system, messages, tools):
        turn = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return turn


def _registry():
    return build_default_registry(MagicMock())


# --------------------------- RecordingRegistry --------------------------- #

def test_recording_registry_records_without_executing():
    actions = MagicMock()
    rec = RecordingRegistry(build_default_registry(actions))
    out = rec.run("open_app", {"app_name": "chrome"})
    assert rec.calls == [("open_app", {"app_name": "chrome"})]
    assert "open_app" in out                           # stub nêu tên tool đã gọi
    actions.open_application.assert_not_called()      # KHÔNG thực thi thật


def test_recording_registry_specs_passthrough():
    inner = _registry()
    rec = RecordingRegistry(inner)
    assert {s["name"] for s in rec.specs()} == {s["name"] for s in inner.specs()}


# --------------------------- score_case --------------------------- #

def test_score_expected_tool_called():
    r = score_case({"id": "x", "text": "t", "expect": ["set_volume"]},
                   called=["set_volume"], got_case=None)
    assert r["tool_ok"] is True


def test_score_expected_tool_missing():
    r = score_case({"id": "x", "text": "t", "expect": ["set_volume"]},
                   called=["open_app"], got_case=None)
    assert r["tool_ok"] is False


def test_score_no_tool_expected_but_called_fails():
    r = score_case({"id": "x", "text": "t", "expect": []},
                   called=["open_app"], got_case=None)
    assert r["tool_ok"] is False


def test_score_no_tool_expected_and_none_called_passes():
    r = score_case({"id": "x", "text": "t", "expect": []}, called=[], got_case=None)
    assert r["tool_ok"] is True


def test_score_multi_needs_all_expected():
    case = {"id": "m", "text": "t", "expect": ["open_app", "set_volume"]}
    assert score_case(case, ["open_app"], None)["tool_ok"] is False
    assert score_case(case, ["open_app", "set_volume"], None)["tool_ok"] is True


def test_score_case_classification():
    case = {"id": "c", "text": "t", "expect": ["get_weather"], "case": "weather"}
    assert score_case(case, ["get_weather"], "weather")["case_ok"] is True
    assert score_case(case, ["get_weather"], "web")["case_ok"] is False


def test_score_error_marks_tool_fail():
    r = score_case({"id": "e", "text": "t", "expect": ["open_app"]},
                   called=["open_app"], got_case=None, error="Boom")
    assert r["tool_ok"] is False and r["error"] == "Boom"


# --------------------------- run_case (agent thật, LLM giả) --------------------------- #

def test_run_case_captures_tool_call_no_side_effect():
    actions = MagicMock()
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "chrome"})]),
        AssistantTurn(text="Đã mở."),
    ])
    r = run_case(llm, build_default_registry(actions), router=None,
                 case={"id": "x", "text": "mở chrome", "expect": ["open_app"]})
    assert r["tool_ok"] is True and r["called"] == ["open_app"]
    actions.open_application.assert_not_called()       # tool KHÔNG chạy thật


def test_run_case_records_router_case():
    llm = _FakeLLM([AssistantTurn(text="Xin chào!")])   # general, không gọi tool

    class _FakeRouter:
        def classify(self, text):
            return "general"
        def select_for_case(self, case, registry):
            return "sys", registry.specs()

    r = run_case(llm, build_default_registry(MagicMock()), router=_FakeRouter(),
                 case={"id": "g", "text": "chào", "expect": [], "case": "general"})
    assert r["got_case"] == "general" and r["case_ok"] is True and r["tool_ok"] is True


# --------------------------- summarize --------------------------- #

def test_summarize_accuracy():
    results = [
        {"tool_ok": True, "case_ok": True},
        {"tool_ok": False, "case_ok": True},
        {"tool_ok": True, "case_ok": None},
    ]
    s = summarize(results)
    assert s["total"] == 3 and s["tool_pass"] == 2
    assert abs(s["tool_acc"] - 2 / 3) < 1e-9
    assert s["case_total"] == 2 and s["case_pass"] == 2 and s["case_acc"] == 1.0


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
