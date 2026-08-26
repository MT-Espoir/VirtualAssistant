"""Test bộ khung eval (evals.harness) — LLM giả, không cần model thật/mạng."""

from conftest import registry_with

from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

from llm.client import AssistantTurn, ToolCall

from evals.harness import (
    RecordingRegistry, RecordingRouter, score_case, run_case, summarize, CountingLLM)


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
    return registry_with(actions=MagicMock())


# --------------------------- RecordingRegistry --------------------------- #

def test_recording_registry_records_without_executing():
    actions = MagicMock()
    rec = RecordingRegistry(registry_with(actions=actions))
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
    r = run_case(llm, registry_with(actions=actions), router=None,
                 case={"id": "x", "text": "mở chrome", "expect": ["open_app"]})
    assert r["tool_ok"] is True and r["called"] == ["open_app"]
    actions.open_application.assert_not_called()       # tool KHÔNG chạy thật


def test_run_case_counts_deferred_destructive_as_selected():
    # Tool khó hoàn tác (close_app) bị agent hoãn để hỏi xác nhận -> eval vẫn tính là
    # model đã chọn đúng tool (đo chọn tool, không đo thực thi).
    actions = MagicMock()
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "close_app", {"app_name": "chrome"})]),
    ])
    r = run_case(llm, registry_with(actions=actions), router=None,
                 case={"id": "c", "text": "đóng chrome", "expect": ["close_app"]})
    assert r["tool_ok"] is True and r["called"] == ["close_app"]
    actions.close_application.assert_not_called()          # KHÔNG chạy (hoãn + không side effect)


def test_run_case_records_router_case():
    llm = _FakeLLM([AssistantTurn(text="Xin chào!")])   # general, không gọi tool

    class _FakeRouter:
        def classify(self, text):
            return "general"
        def select_for_case(self, case, registry):
            return "sys", registry.specs()

    r = run_case(llm, registry_with(actions=MagicMock()), router=_FakeRouter(),
                 case={"id": "g", "text": "chào", "expect": [], "case": "general"})
    assert r["got_case"] == "general" and r["case_ok"] is True and r["tool_ok"] is True


# --------------------------- CountingLLM (đo chi phí) --------------------------- #

def test_counting_llm_counts_and_passes_through():
    inner = _FakeLLM([AssistantTurn(text="a"), AssistantTurn(text="b")])
    c = CountingLLM(inner)
    assert c.generate(system="s", messages=[], tools=[]).text == "a"
    assert c.generate(system="s", messages=[], tools=[]).text == "b"
    assert c.calls == 2 and c.seconds >= 0.0


def test_counting_llm_reset():
    c = CountingLLM(_FakeLLM([AssistantTurn(text="a")]))
    c.generate(system="s", messages=[], tools=[])
    c.reset()
    assert c.calls == 0 and c.seconds == 0.0


def test_counting_llm_counts_even_on_error():
    class _Boom:
        def generate(self, **kw):
            raise RuntimeError("hỏng")

    c = CountingLLM(_Boom())
    try:
        c.generate(system="s", messages=[], tools=[])
    except RuntimeError:
        pass
    assert c.calls == 1          # lượt lỗi vẫn tốn quota -> phải đếm


def test_run_case_reports_llm_calls():
    # 1 tool -> agent gọi LLM 2 lần (decide + respond); không router.
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "chrome"})]),
        AssistantTurn(text="Đã mở."),
    ])
    r = run_case(llm, registry_with(actions=MagicMock()), router=None,
                 case={"id": "x", "text": "mở chrome", "expect": ["open_app"]})
    assert r["calls"] == 2 and r["seconds"] is not None


def test_run_case_shared_counter_includes_router_classify():
    # Counter dùng CHUNG cho router + agent -> đếm đủ 3 lượt (classify + decide + respond).
    shared = CountingLLM(_FakeLLM([
        AssistantTurn(text="system"),                                    # classify
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "chrome"})]),
        AssistantTurn(text="Đã mở."),
    ]))

    class _RouterUsingSharedLLM:
        def classify(self, text):
            shared.generate(system="r", messages=[], tools=[])
            return "system"
        def select_for_case(self, case, registry):
            return "sys", registry.specs()

    r = run_case(shared, registry_with(actions=MagicMock()),
                 router=_RouterUsingSharedLLM(),
                 case={"id": "x", "text": "mở chrome", "expect": ["open_app"],
                       "case": "system"})
    assert r["calls"] == 3       # đây là con số Phase 1 nhắm giảm còn 2


# --------------------------- tham số dòng lệnh của run_eval --------------------------- #

def _parse_args():
    """Import lười: run_eval kéo theo config/actions — thiếu deps thì bỏ qua test."""
    try:
        from evals.run_eval import _parse_args as fn
    except Exception:                       # noqa: BLE001
        if pytest is not None:
            pytest.skip("Thiếu phụ thuộc để import run_eval")
        return None
    return fn


def test_parse_args_splits_gap_and_prefixes():
    fn = _parse_args()
    assert fn(["--gap=9", "web", "sys"]) == (9.0, ["web", "sys"])


def test_parse_args_defaults_to_no_gap():
    fn = _parse_args()
    assert fn([]) == (0.0, [])
    assert fn(["web"]) == (0.0, ["web"])


def test_parse_args_ignores_bad_gap():
    """--gap hỏng KHÔNG được nuốt mất tiền tố id ca (dễ chạy nhầm toàn bộ)."""
    fn = _parse_args()
    assert fn(["--gap=abc", "web"]) == (0.0, ["web"])


def test_parse_args_gap_never_negative():
    fn = _parse_args()
    assert fn(["--gap=-5"]) == (0.0, [])


# --------------------------- summarize --------------------------- #

def test_summarize_cost_metrics():
    results = [
        {"tool_ok": True, "case_ok": None, "calls": 3, "seconds": 3.0},
        {"tool_ok": True, "case_ok": None, "calls": 1, "seconds": 1.0},
    ]
    s = summarize(results)
    assert s["total_calls"] == 4 and s["avg_calls"] == 2.0 and s["avg_seconds"] == 2.0


def test_summarize_without_cost_metrics_stays_none():
    # Tương thích ngược: kết quả cũ không có 'calls' -> không vỡ, trả None.
    s = summarize([{"tool_ok": True, "case_ok": None}])
    assert s["avg_calls"] is None and s["avg_seconds"] is None


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


# --------------------------- đo kích thước đầu vào --------------------------- #

def test_counting_llm_cong_don_ky_tu_dau_vao():
    """`prompt_eval` chiếm ~83% chi phí một lượt, nên số call thôi chưa đủ để so A/B."""
    from evals.harness import CountingLLM
    from llm.client import AssistantTurn, Message

    class _LLM:
        def generate(self, **k):
            return AssistantTurn(text="ok")

    llm = CountingLLM(_LLM())
    llm.generate(system="abcde", messages=[Message(role="user", text="xy")], tools=[])
    assert llm.input_chars == 5 + 2 + len("[]")

    llm.generate(system="", messages=[], tools=[{"name": "t"}])
    assert llm.input_chars > 9, "lượt thứ hai phải CỘNG DỒN, không ghi đè"


def test_reset_xoa_luon_so_do_dau_vao():
    from evals.harness import CountingLLM

    llm = CountingLLM(object())
    llm.input_chars = 999
    llm.reset()
    assert llm.input_chars == 0


def test_summarize_bao_cao_dau_vao_trung_binh():
    from evals.harness import summarize

    s = summarize([{"tool_ok": True, "case_ok": None, "input_chars": 100},
                   {"tool_ok": True, "case_ok": None, "input_chars": 300}])
    assert s["avg_input_chars"] == 200
