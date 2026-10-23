"""Opt-in, local OpenTelemetry measurements; never export conversation payloads.

Durations use perf_counter_ns. W3C propagation uses the official SDK propagator.
No SDK import or background worker until ALICE_TELEMETRY_DIR is set or Session
is constructed by the baseline runner. Business outcomes are never inferred
from a span finishing successfully.
"""

import atexit
import contextvars
import functools
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
import hashlib
import importlib.metadata
import platform
import subprocess
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)
_UNSET = object()
_session = contextvars.ContextVar("alice_measurement_session", default=_UNSET)
_active = contextvars.ContextVar("alice_measurement", default=None)
_turn = contextvars.ContextVar("alice_measurement_turn", default=None)
_runtime = None
_runtime_attempted = False
_lock = threading.Lock()
CHANNELS = {"turn", "fast_local", "browser_media", "iot", "llm", "voice", "agent", "tool", "unknown"}
OUTCOMES = {"returned", "failed", "dispatched", "unknown", "verified", "refused", "awaiting_confirmation", "no_input", "fallback"}
MODES = {"runtime", "offline", "live_readonly", "calibration"}
PHASES = {"turn", "response_ready", "fast_handler", "tool_call", "agent_run", "llm_call", "browser_roundtrip", "iot_roundtrip", "iot_server", "capture", "stt", "tts_complete", "voice_recovery", "matcher", "noop", "postcondition", "tts_synthesis", "voice_bootstrap", "iot_ack"}
SCENARIOS = {"interactive", "local_volume_parser", "browser_pause_parser", "iot_timer_parser", "noisy_recovery_rules", "extension_disconnected", "gateway_token_missing", "gateway_status_readonly", "local_llm_readonly", "llm_readonly", "instrumentation_overhead", "smoke", "test", "runtime_volume", "runtime_browser", "voice_replay", "voice_acoustic", "iot_off_once", "voice_fixture"}
_SAFE_TOKEN = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


def environment_metadata():
    """Reproducible code identity and non-personal machine/runtime dimensions."""
    root = Path(__file__).resolve().parents[2]
    files = ["src/utils/telemetry.py", "src/evals/latency.py", "packaging/measure_baseline.py",
             "src/app.py", "src/agent/agent.py", "src/agent/tools.py", "src/llm/client.py", "src/llm/gemini.py",
             "src/services/browser_bridge.py", "src/features/iot/client.py", "src/features/iot/gateway.py",
             "src/features/system/fast.py", "src/features/browser/fast.py", "src/features/iot/fast.py",
             "src/voice/recorder.py", "src/voice/recovery.py", "src/voice/speech_recognizer.py", "src/voice/speech_synthesizer.py",
             "src/voice/vieneu_voice.py", "chrome_extension/background.js", "packaging/measure_runtime_baseline.py"]
    versions = {}
    for package in ("opentelemetry-sdk", "requests", "websockets", "SpeechRecognition", "numpy", "vieneu", "onnxruntime", "torch", "soundfile", "scipy"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not_installed"
    result = {"python": platform.python_version(), "os": platform.system(), "os_release": platform.release(),
              "machine_architecture": platform.machine(), "logical_cpu_count": os.cpu_count(), "packages": versions,
              "monotonic_clock_resolution_s": time.get_clock_info("perf_counter").resolution,
              "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files if (root / name).is_file()}}
    try:
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5)
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root, capture_output=True, text=True, timeout=5)
        result.update(git_revision=revision.stdout.strip() if revision.returncode == 0 else "unknown",
                      working_tree_dirty=bool(dirty.stdout.strip()))
    except (OSError, subprocess.TimeoutExpired):
        result["git_revision"] = "unknown"
    return result


def safe_attributes(values):
    """Closed dimensions; reject text, URLs, tool arguments and exception messages."""
    result = {}
    enums = {"channel": CHANNELS, "phase": PHASES, "outcome": OUTCOMES, "mode": MODES,
             "cache": {"cold", "warm", "unknown"}, "dependency": {"available", "unavailable", "unknown"},
             "backend": {"vieneu", "gtts", "pyttsx3", "piper", "unknown"}}
    for key, value in values.items():
        if key in enums and isinstance(value, str) and value in enums[key]:
            result["alice." + key] = value
        elif key == "scenario" and isinstance(value, str) and value in SCENARIOS:
            result["alice." + key] = value
        elif key == "error_type" and isinstance(value, str) and _SAFE_TOKEN.fullmatch(value):
            result["alice." + key] = value
    return result


class Measurement:
    def __init__(self, span=None, attributes=None):
        self.span = span
        self.attributes = dict(attributes or {})
        self.started = time.perf_counter_ns()
        self.landmarks = set()

    def set(self, **values):
        attrs = safe_attributes(values)
        self.attributes.update(attrs)
        if self.span:
            self.span.set_attributes(attrs)

    def mark(self, name, seconds_ago=0.0):
        # Landmarks are code-defined names, never content. These are software
        # observations, not proof that a human heard sound or saw a screen.
        if self.span and name not in self.landmarks and name in {"input_ready", "response_ready", "playback_requested", "tts_driver_started", "packet_sent", "vad_end_proxy", "effect_verified", "node_result_observed"}:
            offset = (time.perf_counter_ns() - self.started) / 1e9 - seconds_ago
            if offset >= 0:
                self.landmarks.add(name)
                self.span.add_event(name, {"alice.offset.s": offset})


class Session:
    def __init__(self, directory, *, mode="runtime", metadata=None):
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader
        from opentelemetry.sdk.metrics.view import View, ExplicitBucketHistogramAggregation

        if mode not in MODES:
            raise ValueError("Unsupported measurement mode")
        self.run_id = uuid.uuid4().hex
        self.directory = Path(directory) / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.mode = mode
        self.closed = False
        self.submitted = self.written = self.dropped = 0
        self.started_spans = self.ended_spans = 0
        self._queue = queue.Queue(maxsize=4096)
        self._writer = threading.Thread(target=self._write_loop, daemon=True, name="alice-telemetry")
        self._writer.start()
        owner = self

        class LocalExporter(SpanExporter):
            def export(self, spans):
                for span in spans:
                    parent = span.parent
                    attributes = safe_attributes({key.removeprefix("alice."): value for key, value in span.attributes.items()})
                    attributes["alice.duration.s"] = span.attributes["alice.duration.s"]
                    row = {"schema": 1, "trace_id": format(span.context.trace_id, "032x"),
                           "span_id": format(span.context.span_id, "016x"),
                           "parent_span_id": format(parent.span_id, "016x") if parent else None,
                           "name": "alice." + attributes.get("alice.phase", "unknown"), "start_time_unix_ns": span.start_time,
                           "span_kind": span.kind.name, "status": span.status.status_code.name,
                           "duration_s": span.attributes["alice.duration.s"],
                           "attributes": attributes,
                           "events": [{"name": e.name, "attributes": {"alice.offset.s": e.attributes["alice.offset.s"]}} for e in span.events
                                      if e.name in {"input_ready", "response_ready", "playback_requested", "tts_driver_started", "packet_sent", "vad_end_proxy", "effect_verified", "node_result_observed"}
                                      and isinstance(e.attributes.get("alice.offset.s"), (int, float))]}
                    owner.submitted += 1
                    try:
                        owner._queue.put_nowait(row)
                    except queue.Full:
                        owner.dropped += 1
                return SpanExportResult.SUCCESS

            def shutdown(self):
                pass

        resource = Resource({"service.name": "alice", "alice.run_id": self.run_id})
        self.provider = TracerProvider(resource=resource, sampler=ALWAYS_ON)
        self.provider.add_span_processor(SimpleSpanProcessor(LocalExporter()))
        self.tracer = self.provider.get_tracer("alice.baseline", "1.0")
        self.reader = InMemoryMetricReader()
        self.meter_provider = MeterProvider(resource=resource, metric_readers=[self.reader], views=[
            View(instrument_name="alice.operation.duration", aggregation=ExplicitBucketHistogramAggregation(
                boundaries=(.005, .010, .050, .100, .300, .500, 1., 1.5, 3., 5., 10., 30., 90.)))])
        self.histogram = self.meter_provider.get_meter("alice.baseline", "1.0").create_histogram(
            "alice.operation.duration", unit="s", description="Monotonic duration of an Alice processing stage")
        # metadata is supplied by the runner, never env dumps or machine hostname.
        self.manifest = {"schema": 1, "run_id": self.run_id, "mode": mode,
                         "clock": "time.perf_counter_ns", "sampling": "all",
                         "metadata": environment_metadata() if metadata is None else metadata}

    def _write_loop(self):
        try:
            with (self.directory / "spans.jsonl").open("w", encoding="utf-8") as stream:
                while True:
                    batch = [self._queue.get()]
                    for _ in range(127):
                        try:
                            batch.append(self._queue.get_nowait())
                        except queue.Empty:
                            break
                    stopping = None in batch
                    records = [row for row in batch if row is not None]
                    try:
                        stream.write("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in records))
                        stream.flush()
                        self.written += len(records)
                    except (OSError, ValueError):
                        self.dropped += len(records)
                    finally:
                        for _ in batch:
                            self._queue.task_done()
                    if stopping:
                        return
        except OSError:
            # Drain until shutdown so measurement failures do not stall Alice.
            while True:
                row = self._queue.get()
                self._queue.task_done()
                if row is None:
                    return
                self.dropped += 1

    @contextmanager
    def measure(self, channel, phase, **values):
        if self.closed:
            yield Measurement()
            return
        from opentelemetry.trace import Status, StatusCode, SpanKind
        kind = values.pop("_span_kind", None) or (SpanKind.CLIENT if phase in {"browser_roundtrip", "iot_roundtrip", "llm_call"} else SpanKind.INTERNAL)
        inherited = dict(_active.get().attributes) if _active.get() else {}
        inherited.update(safe_attributes(dict(values, channel=channel, phase=phase, mode=self.mode, outcome="returned")))
        with self.tracer.start_as_current_span("alice." + phase, attributes=inherited,
                                               kind=kind,
                                               record_exception=False, set_status_on_exception=False) as span:
            measurement = Measurement(span, inherited)
            self.started_spans += 1
            token = _active.set(measurement)
            turn_token = _turn.set(measurement) if phase == "turn" else None
            try:
                yield measurement
            except BaseException as exc:
                state = {"NeedsConfirmation": "awaiting_confirmation", "ActionRefused": "refused"}.get(type(exc).__name__, "failed")
                measurement.set(outcome=state, error_type=type(exc).__name__)
                if state == "failed":
                    span.set_status(Status(StatusCode.ERROR))
                raise
            finally:
                seconds = (time.perf_counter_ns() - measurement.started) / 1e9
                span.set_attribute("alice.duration.s", seconds)
                self.histogram.record(seconds, measurement.attributes)
                self.ended_spans += 1
                _active.reset(token)
                if turn_token is not None:
                    _turn.reset(turn_token)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.provider.force_flush()
        self.provider.shutdown()
        try:
            self._queue.put(None, timeout=5)
        except queue.Full:
            # A stalled writer must make the run invalid, not hold up shutdown
            # indefinitely. The daemon exits with the process.
            self.dropped += 1
        self._writer.join(timeout=10)
        data = self.reader.get_metrics_data()
        if data:
            (self.directory / "metrics.json").write_text(data.to_json(), encoding="utf-8")
        self.meter_provider.shutdown()
        self.manifest.update(submitted=self.submitted, written=self.written, dropped=self.dropped,
                             started_spans=self.started_spans, ended_spans=self.ended_spans,
                             complete=not self._writer.is_alive() and self.submitted == self.written and self.dropped == 0 and self.started_spans == self.ended_spans)
        (self.directory / "manifest.json").write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")


def get_session():
    global _runtime, _runtime_attempted
    chosen = _session.get()
    if chosen is not _UNSET:
        return chosen
    if not _runtime_attempted:
        with _lock:
            if not _runtime_attempted:
                _runtime_attempted = True
                directory = os.getenv("ALICE_TELEMETRY_DIR", "").strip()
                if directory:
                    try:
                        _runtime = Session(directory)
                        atexit.register(_runtime.close)
                    except Exception as exc:
                        log.warning("Telemetry disabled: %s", type(exc).__name__)
    return _runtime


@contextmanager
def use_session(session):
    token = _session.set(session)
    try:
        yield session
    finally:
        _session.reset(token)


@contextmanager
def measure(channel, phase, **values):
    session = get_session()
    if session is None:
        yield Measurement()
    else:
        with session.measure(channel, phase, **values) as value:
            yield value


def measured(channel, phase):
    def decorate(function):
        @functools.wraps(function)
        def run(*args, **kwargs):
            if get_session() is None:
                return function(*args, **kwargs)
            with measure(channel, phase):
                return function(*args, **kwargs)
        return run
    return decorate


def annotate(**values):
    active = _active.get()
    if active:
        active.set(**values)
    turn = _turn.get()
    if turn and turn is not active and "channel" in values:
        turn.set(channel=values["channel"])
    if turn and turn is not active and "outcome" in values and active.attributes.get("alice.phase") in {"response_ready", "fast_handler"}:
        turn.set(outcome=values["outcome"])


def mark(name, seconds_ago=0.0):
    active = _active.get()
    if active:
        active.mark(name, seconds_ago)
    turn = _turn.get()
    if turn and turn is not active:
        turn.mark(name, seconds_ago)


def trace_headers():
    if get_session() is None:
        return {}
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    carrier = {}
    TraceContextTextMapPropagator().inject(carrier)
    return carrier


def traced_llm(client):
    """Preserve the provider interface; record calls without prompts/responses."""
    class TracedClient:
        def __getattr__(self, name):
            return getattr(client, name)

        @measured("llm", "llm_call")
        def generate(self, **kwargs):
            return client.generate(**kwargs)
    return TracedClient()


def received_trace(channel, phase):
    """Authenticated loopback HTTP handlers keep the caller trace ID.

    Only W3C traceparent is extracted. No baggage, token, path or body enters
    telemetry. Invalid/oversized headers start a fresh local trace.
    """
    def decorate(function):
        @functools.wraps(function)
        def run(handler, *args, **kwargs):
            session = get_session()
            if session is None:
                return function(handler, *args, **kwargs)
            from opentelemetry import context
            from opentelemetry.trace import SpanKind
            from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
            value = handler.headers.get("traceparent", "")
            carrier = {"traceparent": value} if isinstance(value, str) and len(value) <= 256 else {}
            token = context.attach(TraceContextTextMapPropagator().extract(carrier))
            try:
                with session.measure(channel, phase, _span_kind=SpanKind.SERVER):
                    return function(handler, *args, **kwargs)
            finally:
                context.detach(token)
        return run
    return decorate
