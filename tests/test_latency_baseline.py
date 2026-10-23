"""Measurement invariants: privacy, clocks, correlation, no false SLO passes."""

import contextvars
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("opentelemetry.sdk")
from evals.latency import percentile, summarize, write_report
from utils.telemetry import Session, measure, use_session, trace_headers, received_trace, safe_attributes, mark


def rows(session):
    return [json.loads(x) for x in (session.directory / "spans.jsonl").read_text(encoding="utf-8").splitlines()]


def test_units_exact_quantiles_and_invalid_samples():
    assert percentile(list(range(1,101)), .95) == 95
    assert percentile([.001], .99) == .001
    assert percentile([], .5) is None
    for invalid in ([float("nan")], [float("inf")], [-1.]):
        with pytest.raises(ValueError):
            percentile(invalid, .95)


def test_span_parent_ids_cross_thread_and_no_payload(tmp_path):
    session = Session(tmp_path, mode="offline")
    with use_session(session):
        with measure("fast_local", "turn", scenario="test", transcript="secret", url="https://secret"):
            from utils.telemetry import _active
            _active.get().span.set_attribute("unsafe_third_party", "secret")
            _active.get().span.add_event("unsafe_event", {"body": "secret"})
            context = contextvars.copy_context()
            def child():
                with measure("tool", "tool_call"):
                    assert trace_headers()["traceparent"].startswith("00-")
            worker = threading.Thread(target=lambda: context.run(child))
            worker.start()
            worker.join()
    session.close()
    data = rows(session)
    parent = next(r for r in data if r["name"] == "alice.turn")
    child = next(r for r in data if r["name"] == "alice.tool_call")
    assert child["parent_span_id"] == parent["span_id"]
    assert child["trace_id"] == parent["trace_id"]
    assert "secret" not in (session.directory / "spans.jsonl").read_text()
    assert session.manifest["complete"]


def test_w3c_receiver_valid_invalid_headers_and_auth_unchanged(tmp_path):
    session = Session(tmp_path, mode="live_readonly")
    class Handler:
        @received_trace("iot", "iot_server")
        def call(self):
            return "business_result"
    with use_session(session):
        with measure("iot", "iot_roundtrip"):
            headers = trace_headers()
            assert HandlerWithHeaders(Handler, headers).call() == "business_result"
        with measure("iot", "iot_roundtrip"):
            HandlerWithHeaders(Handler, {"traceparent": "00-" + "0"*32 + "-" + "0"*16 + "-01"}).call()
    session.close()
    data = rows(session)
    clients = [r for r in data if r["name"] == "alice.iot_roundtrip"]
    servers = [r for r in data if r["name"] == "alice.iot_server"]
    assert servers[0]["trace_id"] == clients[0]["trace_id"]
    assert servers[0]["parent_span_id"] == clients[0]["span_id"]
    assert servers[0]["span_kind"] == "SERVER"
    assert servers[1]["trace_id"] != clients[1]["trace_id"]


def HandlerWithHeaders(cls, headers):
    obj = cls()
    obj.headers = headers
    return obj


def test_errors_not_verified_and_exception_text_never_saved(tmp_path):
    session = Session(tmp_path)
    with use_session(session):
        with pytest.raises(RuntimeError):
            with measure("iot", "iot_roundtrip"):
                raise RuntimeError("private password or user content")
    session.close()
    data = rows(session)[0]
    assert data["attributes"]["alice.outcome"] == "failed"
    assert data["status"] == "ERROR"
    assert "password" not in json.dumps(data)
    assert safe_attributes({"channel": [], "scenario": "password", "arguments": {"token": "secret"}}) == {}


def test_gate_needs_real_boundary_and_complete_samples(tmp_path):
    session = Session(tmp_path, mode="runtime")
    with use_session(session):
        with measure("fast_local", "turn", scenario="test", cache="warm") as turn:
            turn.set(outcome="fallback")
            mark("input_ready")
            mark("response_ready")
        with measure("fast_local", "matcher", scenario="test", cache="warm"):
            pass
    session.close()
    report = write_report(session.directory)
    boundary = next(g for g in report["groups"] if g["phase"] == "input_to_response")
    stage = next(g for g in report["groups"] if g["phase"] == "matcher")
    assert boundary["gate"] == "insufficient_samples"
    assert boundary["outcomes"] == {"fallback": 1}
    assert stage["gate"] == "not_applicable_stage_or_offline"
    (session.directory / "observer_samples.json").write_text(json.dumps({"enabled": [.001,.002], "disabled": [.0001,.0002]}))
    recalculated = summarize(session.directory)
    assert recalculated["metadata"]["observer_total_call_s"]["enabled"]["p99"] == .002
    manifest = session.manifest.copy()
    manifest["complete"] = False
    (session.directory / "manifest.json").write_text(json.dumps(manifest))
    assert next(g for g in summarize(session.directory)["groups"] if g["phase"] == "input_to_response")["gate"] == "invalid_incomplete_export"


def test_disabled_session_does_not_create_files_or_change_result(tmp_path):
    from utils.telemetry import measured
    @measured("tool", "tool_call")
    def operation(value):
        return value
    with use_session(None):
        assert operation("same") == "same"
        assert trace_headers() == {}
    assert list(tmp_path.iterdir()) == []


def test_llm_factory_preserves_interface_with_telemetry(tmp_path, monkeypatch):
    from llm import client as module
    class Client:
        model = "fixture"
        def generate(self, **kwargs):
            return "same_result"
    inner = Client()
    monkeypatch.setattr(module, "_build_default_llm_client", lambda: inner)
    with use_session(None):
        assert module.build_default_llm_client() is inner
    session = Session(tmp_path, mode="offline")
    with use_session(session):
        wrapped = module.build_default_llm_client()
        assert wrapped.model == "fixture"
        assert wrapped.generate(system="private_prompt", messages=[], tools=[]) == "same_result"
    session.close()
    assert rows(session)[0]["name"] == "alice.llm_call"
    assert "private_prompt" not in json.dumps(rows(session))


def test_tts_fallback_backend_distributions_are_separate(tmp_path):
    session = Session(tmp_path, mode="runtime")
    with use_session(session):
        with measure("voice", "tts_complete", backend="vieneu"):
            pass
        with measure("voice", "tts_complete", backend="gtts") as span:
            span.set(outcome="fallback")
    session.close()
    groups = summarize(session.directory)["groups"]
    assert {g["backend"] for g in groups} == {"vieneu", "gtts"}
    assert all(g["n"] == 1 for g in groups)


def test_assistant_loop_records_paired_boundary_without_waiting_for_user(tmp_path, monkeypatch):
    import app
    from unittest.mock import MagicMock
    from utils.events import AssistantBus
    inputs = iter(["fixture text", None])
    monkeypatch.setattr(app, "_next_input", lambda *args: next(inputs))
    agent = MagicMock()
    agent.pending = None
    agent.persona = None
    agent.run.return_value = SimpleNamespace(text="fixture reply", emotion="neutral")
    session = Session(tmp_path, mode="runtime")
    with use_session(session):
        app._assistant_loop(agent, AssistantBus(), None, None)
    session.close()
    report = summarize(session.directory)
    boundary = [g for g in report["groups"] if g["phase"] == "input_to_response"]
    assert len(boundary) == 1
    assert boundary[0]["n"] == 1
    assert boundary[0]["channel"] == "agent"
    assert "fixture text" not in json.dumps(rows(session))


def test_tts_queue_text_keeps_identity_and_context(tmp_path):
    from voice.speech_synthesizer import _TracedText
    from utils.telemetry import get_session
    session = Session(tmp_path)
    with use_session(session):
        text = _TracedText("private TTS text")
    assert isinstance(text, str) and text == "private TTS text"
    assert text.context.run(get_session) is session
    session.close()
    assert "private TTS text" not in json.dumps(rows(session))


def test_iot_client_propagates_header_but_not_token_to_telemetry(tmp_path, monkeypatch):
    from features.iot import client as module
    from features.iot.client import IoTClient
    token = tmp_path / "token"
    token.write_text("private_token")
    captured = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"status":"ok"}'
    def open_request(request, timeout):
        captured.append(request)
        return Response()
    monkeypatch.setattr(module, "urlopen", open_request)
    session = Session(tmp_path / "traces")
    with use_session(session):
        assert IoTClient(SimpleNamespace(api_port=18787, token_path=token)).status() == {"status":"ok"}
    session.close()
    assert captured[0].get_header("Traceparent").startswith("00-")
    assert captured[0].get_header("X-alice-iot-token") == "private_token"
    assert "private_token" not in json.dumps(rows(session))


def test_monotonic_duration_independent_from_wall_clock_and_histogram(tmp_path, monkeypatch):
    from utils import telemetry
    session = Session(tmp_path)
    ticks = iter([1000000000, 1250000000])
    monkeypatch.setattr(telemetry.time, "perf_counter_ns", lambda: next(ticks))
    with use_session(session):
        with measure("fast_local", "noop"):
            pass
    session.close()
    assert rows(session)[0]["duration_s"] == .25
    metrics = json.loads((session.directory / "metrics.json").read_text())
    data = metrics["resource_metrics"][0]["scope_metrics"][0]["metrics"][0]
    assert data["unit"] == "s"
    assert data["data"]["data_points"][0]["count"] == 1
    assert data["data"]["data_points"][0]["sum"] == .25
