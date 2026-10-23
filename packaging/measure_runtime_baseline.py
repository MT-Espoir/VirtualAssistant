"""Controlled real Alice pipelines. Actuation is bounded and recorded explicitly.

Use Alice's existing Python environment for VieNeu/Windows dependencies. Synthetic
speech is temporary; microphone recordings are never written to disk.
"""

import argparse
import contextlib
import hashlib
import io
import json
import logging
import math
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from utils.telemetry import Session, measure, mark, annotate, use_session, environment_metadata
from evals.latency import write_report


class QuietBus:
    """Real pipeline event sink, without retaining UI text or debug payloads."""
    def __init__(self, postcondition=None): self.postcondition = postcondition
    def emit(self, **kwargs):
        # _say marks response_ready before this event. The additional probe
        # therefore does not inflate the measured production response boundary.
        if kwargs.get("state") == "speaking" and self.postcondition:
            self.postcondition()
    def emit_debug(self, *args, **kwargs): pass
    def emit_ui(self, **kwargs): pass
    def emit_control(self, *args, **kwargs): pass
    def current_ui_target(self): return "avatar"


class BoundedAgent:
    def __init__(self, registry):
        self.registry = registry
        self.pending = self.persona = None

    def run(self, text):
        # Unexpected transcription must not reach unrestricted tools or LLM.
        raise RuntimeError("Baseline input did not take the selected fast path")


class PacedPCM:
    """Stream clocked like PCM input, rather than a zero-time recorder mock."""
    def __init__(self, rate):
        self.rate = rate
        self.data = b""
        self.position = 0
        self.deadline = None

    def install(self, data):
        self.data, self.position, self.deadline = data, 0, None

    def read(self, frames, **kwargs):
        if self.deadline is None:
            self.deadline = time.perf_counter()
        self.deadline += frames / self.rate
        time.sleep(max(0, self.deadline - time.perf_counter()))
        count = frames * 2
        chunk = self.data[self.position:self.position + count]
        self.position += count
        return chunk + bytes(count - len(chunk))

    def get_read_available(self): return 0
    def stop_stream(self): pass
    def close(self): pass


class ReplayAudio:
    def __init__(self, rate): self.stream = PacedPCM(rate)
    def open(self, **kwargs): return self.stream
    def terminate(self): pass


def volume_registry(facts):
    from pycaw.pycaw import AudioUtilities
    from actions.system.system_control import control_volume
    from agent.tools import Tool, ToolRegistry
    endpoint = AudioUtilities.GetSpeakers().EndpointVolume
    original = float(endpoint.GetMasterVolumeLevelScalar())
    base = max(1, min(98, round(original * 100)))
    allowed = {base, base + 1}
    registry = ToolRegistry()
    facts.update(verified_effects=0, unexpected_actions_blocked=0)
    pending = [None]

    def handler(level=None, change=None):
        if change is not None or level not in allowed:
            facts["unexpected_actions_blocked"] += 1
            raise ValueError("Only the two bounded test volume levels are allowed")
        result = control_volume(level=level)
        pending[0] = level
        return result

    def verify():
        level = pending[0]
        if level is None: return
        with measure("fast_local", "postcondition") as span:
            observed = AudioUtilities.GetSpeakers().EndpointVolume.GetMasterVolumeLevelScalar()
            if abs(observed - level / 100) > .005:
                span.set(outcome="failed")
                raise RuntimeError("Volume read-after-write mismatch")
            span.set(outcome="verified")
            facts["verified_effects"] += 1
            mark("effect_verified")
            pending[0] = None

    def restore():
        endpoint.SetMasterVolumeLevelScalar(original, None)
        if abs(endpoint.GetMasterVolumeLevelScalar() - original) > .0001:
            raise RuntimeError("Original output volume was not restored")
    registry.register(Tool("set_volume", "Bounded real volume measurement", {}, handler))
    return registry, base, restore, verify


def runtime_local(session, samples, warmup):
    import app
    from features.system.fast import match_volume
    facts = session.manifest["metadata"]
    registry, base, restore, verify = volume_registry(facts)
    agent, bus = BoundedAgent(registry), QuietBus(verify)
    try:
        with use_session(None), contextlib.redirect_stdout(io.StringIO()):
            for i in range(warmup):
                response, emotion = app._dispatch(agent, f"đặt âm lượng {base + i % 2}%", bus, match_volume)
                app._say(None, bus, response, emotion)
        facts["verified_effects"] = 0
        inputs = iter(f"đặt âm lượng {base + i % 2}%" for i in range(samples))
        # Actual assistant loop, with bounded artificial text instead of stdin.
        with use_session(session), contextlib.redirect_stdout(io.StringIO()):
            app._assistant_loop(agent, bus, None, None, fast_match=match_volume,
                                input_reader=lambda *_: next(inputs, None))
    finally:
        restore()
        facts["volume_restored"] = True
    facts.update(input_source="artificial_text", tts_included=False,
                 conditions="Actual assistant loop, matcher, registry and Windows volume; two alternating levels; no GUI consumer")


def connect_bridge():
    from services.browser_bridge import BrowserBridge
    from utils.config import config
    import socket
    with socket.socket() as check:
        if check.connect_ex((config.BROWSER_BRIDGE_HOST, config.BROWSER_BRIDGE_PORT)) == 0:
            raise RuntimeError("Bridge port already owned; do not replace a running Alice")
    bridge = BrowserBridge(config.BROWSER_BRIDGE_HOST, config.BROWSER_BRIDGE_PORT,
                           config.BROWSER_BRIDGE_TOKEN)
    bridge.start()
    until = time.monotonic() + 30
    while not bridge.connected and time.monotonic() < until:
        time.sleep(.1)
    if not bridge.connected:
        bridge.stop()
        raise RuntimeError("Extension did not connect within 30 seconds")
    return bridge


def browser(session, samples, warmup, url):
    import app
    from urllib.parse import urlparse
    from agent.tools import ToolRegistry
    from features.browser.tools import _register_browser_tools
    from features.browser.fast import match_media
    facts = session.manifest["metadata"]
    bridge = connect_bridge()
    tab_id = None
    try:
        # Require a dedicated newly-created tab so cleanup cannot close user data.
        existing = bridge.send_command("GET_TABS").get("tabs", [])
        if any(urlparse(t.get("url", "")).hostname in {"youtube.com", "www.youtube.com", "music.youtube.com"} for t in existing):
            raise RuntimeError("Existing YouTube tab detected; choose an isolated test profile")
        created = bridge.send_command("OPEN_OR_REUSE_URL", newUrl=url, targetDomain="youtube.com")
        if created.get("reused") or not isinstance(created.get("tabId"), int):
            raise RuntimeError("Did not obtain a new dedicated YouTube test tab")
        tab_id = created["tabId"]
        initial = {}
        until = time.monotonic() + 40
        while time.monotonic() < until:
            initial = bridge.send_command("GET_MEDIA_STATE", tabId=tab_id)
            if initial.get("found"):
                break
            if initial.get("type") == "ERROR" and initial.get("message") == "Unknown action":
                raise RuntimeError("Loaded extension does not implement read-after-write probe")
            time.sleep(.5)
        if not initial.get("found"):
            raise RuntimeError("YouTube player did not become available")
        bridge.send_command("CONTROL_MEDIA", tabId=tab_id, mediaAction="SET_VOLUME", value=0)
        # Player DOM can precede usable media by seconds. Setup waits separately;
        # do not misclassify navigation/buffering as a warmed control command.
        bridge.send_command("CONTROL_MEDIA", tabId=tab_id, mediaAction="PLAY")
        ready_until = time.monotonic() + 30
        while not bridge.send_command("GET_MEDIA_STATE", tabId=tab_id).get("isPlaying"):
            if time.monotonic() >= ready_until:
                raise RuntimeError("Dedicated video never reached playing state during setup")
            time.sleep(.25)

        class TargetedBridge:
            def send_command(self, **payload):
                if payload.get("action") == "CONTROL_MEDIA":
                    payload["tabId"] = tab_id
                return bridge.send_command(**payload)

        registry = ToolRegistry()
        _register_browser_tools(registry, TargetedBridge())
        original_handler = registry.get("browser_media_control").handler
        facts.update(verified_effects=0, postcondition_failures=0,
                     conditions="Actual extension/YouTube tab; alternating play/pause; muted dedicated tab; state polled after command")

        pending = [None]
        def handler(action, value=None):
            response = original_handler(action, value)
            pending[0] = action
            return response

        def verify():
            action = pending[0]
            if action is None: return
            with measure("browser_media", "postcondition") as span:
                end = time.monotonic() + 1.5
                while True:
                    state = bridge.send_command("GET_MEDIA_STATE", tabId=tab_id)
                    valid = state.get("found") and (state.get("paused") is True if action == "pause" else state.get("isPlaying") is True)
                    if valid:
                        span.set(outcome="verified")
                        facts["verified_effects"] += 1
                        mark("effect_verified")
                        pending[0] = None
                        return
                    if time.monotonic() >= end:
                        span.set(outcome="unknown")
                        facts["postcondition_failures"] += 1
                        raise RuntimeError("Media postcondition not observed before deadline")
                    time.sleep(.02)

        registry.get("browser_media_control").handler = handler
        agent, bus = BoundedAgent(registry), QuietBus(verify)
        # Use controlled explicit root scenarios, with actual dispatch/registry.
        for i in range(warmup + samples):
            action = "tạm dừng video" if i % 2 == 0 else "phát tiếp video"
            selected = session if i >= warmup else None
            with use_session(selected), contextlib.redirect_stdout(io.StringIO()):
                with measure("browser_media", "turn", scenario="runtime_browser", cache="unknown"):
                    mark("input_ready")
                    response, emotion = app._dispatch(agent, action, bus, match_media)
                    app._say(None, bus, response, emotion)
            if facts["postcondition_failures"]:
                break
            if i == warmup - 1:
                facts["verified_effects"] = 0
            time.sleep(.03)
    finally:
        if tab_id is not None:
            connection = bridge.connection_id
            preview = bridge.send_command("CLOSE_TAB_BY_KEYWORD", keyword=url, dryRun=True,
                                          expected_connection=connection)
            if connection and preview.get("tabIds") == [tab_id] and preview.get("previewToken"):
                closed = bridge.send_command("CLOSE_TAB_BY_KEYWORD", keyword=url, dryRun=False,
                                             tabIds=[tab_id], previewToken=preview["previewToken"],
                                             expected_connection=connection)
                facts["test_tab_closed"] = (closed.get("outcome") == "verified"
                                            and closed.get("readBack") is True
                                            and closed.get("closedIds") == [tab_id])
            else:
                facts["test_tab_closed"] = False
        bridge.stop()


def iot_off(session):
    from features.iot.client import IoTClient
    from agent.tools import ToolRegistry
    from features.iot.tools import register
    client = IoTClient()
    registry = ToolRegistry()
    register(registry, SimpleNamespace(iot=client))
    facts = session.manifest["metadata"]
    status = client.status()
    rooms = sorted({d["room_id"] for d in status["devices"] if "climate.power" in d["capabilities"]})
    if len(rooms) != 1:
        raise RuntimeError("Exactly one climate room required for the authorized off test")
    facts.update(commands_attempted=1, auto_power_on=False, physical_state_verified=False,
                 conditions="One explicitly authorized off command; real API/MQTT/node ACK; no physical sensor verification")
    with use_session(session):
        with measure("iot", "turn", scenario="iot_off_once", cache="unknown") as turn:
            mark("input_ready")
            # Run normal IoT tool and its normal polling, without changing gate policy.
            result = json.loads(registry.run("control_room_ac", {"action": "off", "room_id": rooms[0]}))
            mark("response_ready")
            turn.set(outcome="dispatched" if result.get("request_id") else "failed")
            request_id = result.get("request_id")
            facts["tool_result_status"] = result.get("status")
            if request_id:
                with measure("iot", "iot_ack") as ack:
                    end = time.monotonic() + 12
                    while True:
                        latest = client.command_status(request_id)
                        state = latest.get("status")
                        if state in {"ir_sent", "failed", "node_result_ok_uncorrelated", "node_result_failed_uncorrelated", "ack_timeout_unknown"} or time.monotonic() >= end:
                            facts["final_command_status"] = state
                            facts["node_response_correlated"] = state in {"ir_sent", "failed"}
                            if state in {"ir_sent", "failed", "node_result_ok_uncorrelated", "node_result_failed_uncorrelated"}:
                                mark("node_result_observed")
                            ack.set(outcome="dispatched" if state in {"ir_sent", "node_result_ok_uncorrelated"} else "failed" if state in {"failed", "node_result_failed_uncorrelated"} else "unknown")
                            break
                        time.sleep(.1)


def voice(session, samples, acoustic, ready_timeout=300, fixture_volume=None):
    import app
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from utils.config import config
    from voice.config import from_config
    from voice.vieneu_voice import tao
    from voice.speech_synthesizer import SpeechSynthesizer
    from voice.speech_recognizer import SpeechRecognizer
    from voice.recorder import Recorder
    from features.system.fast import match_volume
    cfg, facts = from_config(config), session.manifest["metadata"]
    registry, base, restore, verify = volume_registry(facts)
    agent, bus = BoundedAgent(registry), QuietBus(verify)
    synth = recorder = engine = None
    try:
        with use_session(session):
            with measure("voice", "voice_bootstrap", scenario="voice_fixture") as bootstrap:
                facts["voice_ready_timeout_s"] = ready_timeout
                engine = tao(cfg.noi)
                if engine is None or not engine.doi_san_sang(ready_timeout):
                    bootstrap.set(outcome="failed")
                    if engine and engine._thread:
                        import traceback
                        stack = sys._current_frames().get(engine._thread.ident)
                        facts["bootstrap_wait_stack"] = [{"file":Path(f.filename).name,"function":f.name,"line":f.lineno} for f in traceback.extract_stack(stack)] if stack else []
                    raise RuntimeError("Configured VieNeu engine did not become ready")
                synth = SpeechSynthesizer(engine=cfg.noi.engine, language=cfg.noi.language,
                    speed=cfg.noi.speed, robot=cfg.noi.robot, robot_carrier=cfg.noi.robot_carrier, giong_rieng=engine)
        facts.update(stt_engine=cfg.nghe.engine, tts_engine=cfg.noi.engine,
                     voice_mode=cfg.noi.vieneu_mode, voice_precision=cfg.noi.vieneu_precision,
                     sample_rate=cfg.nghe.sample_rate, chunk=cfg.nghe.chunk_size,
                     silence_duration_s=cfg.nghe.silence_duration,
                     input_source="speaker_to_physical_microphone" if acoustic else "paced_pcm_replay",
                     fixture_output_percent=fixture_volume, raw_microphone_audio_saved=False,
                     corpus=[], synthetic_audio_retained=False, fixture_playback_errors=[])
        with tempfile.TemporaryDirectory(prefix="synthetic-voice-", dir=session.directory) as temp:
            phrase = f"{cfg.wake_words[0] if cfg.wake_words else 'Alice'}, đặt âm lượng {base} phần trăm."
            wav = Path(temp) / "fixture.wav"
            with use_session(session), measure("voice", "tts_synthesis", scenario="voice_fixture") as fixture:
                if not engine.synth_wav(phrase, str(wav)):
                    fixture.set(outcome="failed")
                    raise RuntimeError("Synthetic fixture generation failed")
            data, rate = sf.read(wav, dtype="float32")
            if data.ndim > 1: data = data.mean(axis=1)
            divisor = math.gcd(rate, cfg.nghe.sample_rate)
            data = resample_poly(data, cfg.nghe.sample_rate // divisor, rate // divisor)
            pcm = (np.clip(data, -1, 1) * 32767).astype('<i2').tobytes()
            facts["corpus"].append({"id":"fixed_volume", "sha256_pcm":hashlib.sha256(pcm).hexdigest(), "duration_s":len(pcm)/2/cfg.nghe.sample_rate})
            source = None if acoustic else ReplayAudio(cfg.nghe.sample_rate)
            recorder = Recorder(channels=cfg.nghe.channels, rate=cfg.nghe.sample_rate,
                chunk=cfg.nghe.chunk_size, speech_threshold_ratio=cfg.nghe.speech_threshold_ratio,
                silence_duration=cfg.nghe.silence_duration, max_utterance_s=cfg.nghe.max_utterance_s,
                speech_start_timeout_s=cfg.nghe.speech_start_timeout_s, pre_roll_s=cfg.nghe.pre_roll_s,
                audio_source=source)
            recognizer = SpeechRecognizer(language=cfg.nghe.language, engine=cfg.nghe.engine, sample_rate=cfg.nghe.sample_rate)
            completed = 0
            def read_input(voice_io, bus):
                nonlocal completed
                if completed >= samples: return None
                completed += 1
                if acoustic:
                    import pygame
                    # Fixture playback is separate from the real response TTS.
                    from pycaw.pycaw import AudioUtilities
                    endpoint = AudioUtilities.GetSpeakers().EndpointVolume
                    prior = endpoint.GetMasterVolumeLevelScalar()
                    if fixture_volume is not None:
                        endpoint.SetMasterVolumeLevelScalar(fixture_volume / 100, None)
                    def play_fixture():
                        try:
                            pygame.mixer.music.load(str(wav))
                            pygame.mixer.music.play()
                        except Exception as exc:
                            facts["fixture_playback_errors"].append(type(exc).__name__)
                    playback = threading.Timer(.3, play_fixture)
                    playback.start()
                else:
                    source.stream.install(bytes(int(.25*cfg.nghe.sample_rate)*2) + pcm + bytes(int((cfg.nghe.silence_duration+.5)*cfg.nghe.sample_rate)*2))
                recognizer.last_result = None
                try:
                    result = app._listen_voice(recorder, recognizer, bus)
                finally:
                    if acoustic:
                        playback.join(timeout=2)
                        pygame.mixer.music.stop()
                        pygame.mixer.music.unload()  # Release Windows file lock before temp cleanup.
                        endpoint.SetMasterVolumeLevelScalar(prior, None)
                capture = recorder.last_capture
                facts.setdefault("recognition_observations", []).append({"sample":completed,
                    "recognized":recognizer.last_result is not None,
                    "matches_expected_volume":match_volume(str(result)) == ("set_volume", {"level":base}),
                    "confidence":getattr(recognizer.last_result,"confidence",None),
                    "ended_by_silence":capture.ended_by_silence, "hit_max_utterance":capture.hit_max_utterance,
                    "peak_rms":capture.peak_rms, "onset_threshold":capture.threshold,
                    "wait_s":capture.wait_seconds, "speech_s":capture.speech_seconds})
                print(f"voice sample {completed}/{samples}: recognized={recognizer.last_result is not None}", file=sys.__stdout__, flush=True)
                return result
            with use_session(session), contextlib.redirect_stdout(io.StringIO()):
                app._assistant_loop(agent, bus, synth, (recorder, recognizer), fast_match=match_volume, input_reader=read_input)
            facts["attempted_samples"] = completed
    finally:
        if recorder: recorder.close()
        if synth: synth.stop()
        if engine: engine.dong()
        restore()
        facts["volume_restored"] = True


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["local", "browser", "voice-replay", "voice-acoustic", "iot-off-once"])
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=25)
    parser.add_argument("--voice-ready-timeout", type=float, default=300)
    parser.add_argument("--fixture-output-volume", type=int)
    parser.add_argument("--url", default="https://www.youtube.com/watch?v=aqz-KE-bpKQ")
    parser.add_argument("--output", type=Path, default=ROOT/"artifacts"/"latency")
    args = parser.parse_args()
    if not 1 <= args.samples <= 10000 or args.warmup < 0: parser.error("Invalid sample count")
    if args.mode.startswith("voice") and args.samples > 20: parser.error("Voice pilot capped at 20 remote STT requests")
    if args.fixture_output_volume is not None and (args.mode != "voice-acoustic" or not 1 <= args.fixture_output_volume <= 50):
        parser.error("fixture output volume is only for acoustic mode, in 1..50")
    if args.mode == "browser":
        from urllib.parse import urlparse
        parsed = urlparse(args.url)
        if parsed.scheme != "https" or parsed.hostname not in {"youtube.com", "www.youtube.com", "music.youtube.com"}:
            parser.error("browser baseline requires an HTTPS YouTube test URL")
    logging.getLogger().setLevel(logging.WARNING)
    facts = environment_metadata()
    facts.update(samples_requested=args.samples, warmup_requested=args.warmup,
                 harness=args.mode, serial_single_client=True, failure=None)
    session = Session(args.output, mode="runtime", metadata=facts)
    print("run", session.run_id, "mode", args.mode, flush=True)
    try:
        if args.mode == "local": runtime_local(session, args.samples, args.warmup)
        elif args.mode == "browser": browser(session, args.samples, args.warmup, args.url)
        elif args.mode == "iot-off-once": iot_off(session)
        else: voice(session, args.samples, args.mode == "voice-acoustic", args.voice_ready_timeout, args.fixture_output_volume)
    except Exception as exc:
        facts["failure"] = type(exc).__name__
        print("measurement_failure", type(exc).__name__, str(exc), flush=True)
    finally:
        session.close()
        write_report(session.directory)
        print(session.directory / "report.md", flush=True)
    return 1 if facts["failure"] else 0


if __name__ == "__main__": raise SystemExit(main())
