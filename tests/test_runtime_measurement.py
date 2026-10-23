"""Verify measurement adapters and the response/probe boundary."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np


def harness():
    path = Path(__file__).resolve().parents[1] / "packaging" / "measure_runtime_baseline.py"
    spec = importlib.util.spec_from_file_location("alice_runtime_baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paced_pcm_runs_actual_vad_without_physical_microphone(monkeypatch):
    module = harness()
    ticks = [0.]
    monkeypatch.setattr(module.time, "perf_counter", lambda: ticks[0])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: ticks.__setitem__(0, ticks[0] + seconds))
    from voice.recorder import Recorder
    audio = module.ReplayAudio(16000)
    recorder = Recorder(rate=16000, chunk=160, calibration_duration=.02,
                        silence_duration=.2, speech_start_timeout_s=.5,
                        max_utterance_s=2, audio_source=audio)
    try:
        # Several nonzero chunks then actual silence, not a prepared transcript.
        pcm = np.full(3200, 10000, dtype='<i2').tobytes() + bytes(16000)
        audio.stream.install(pcm)
        capture = recorder.listen_once()
        assert capture and recorder.last_capture.ended_by_silence
        assert not recorder.last_capture.hit_max_utterance
        assert recorder.last_capture.peak_rms >= 10000
        assert ticks[0] >= .2  # PCM reads remain clocked even under fake test time.
    finally:
        recorder.close()


def test_probe_happens_after_response_landmark(monkeypatch):
    import app
    module = harness()
    events = []
    monkeypatch.setattr(app, "mark", lambda name: events.append(name))
    app._say(None, module.QuietBus(lambda: events.append("read_after_write")), "fixture", "neutral")
    assert events == ["response_ready", "read_after_write"]


def test_explicit_input_reader_never_requests_stdin(monkeypatch):
    import app
    module = harness()
    monkeypatch.setattr(app, "_next_input", lambda *_: (_ for _ in ()).throw(AssertionError("stdin called")))
    agent = MagicMock()
    agent.pending = agent.persona = None
    agent.run.return_value = SimpleNamespace(text="fixture response", emotion="neutral")
    inputs = iter(["fixture command", None])
    app._assistant_loop(agent, module.QuietBus(), None, None,
                        input_reader=lambda *_: next(inputs))
    assert agent.run.call_count == 1
