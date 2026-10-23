"""Read-only/offline baseline runner. No desktop, Chrome or IoT actuators."""

import argparse
import json
import socket
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evals.latency import write_report
from utils.telemetry import Session, measure, use_session, environment_metadata


def metadata():
    facts = environment_metadata()
    facts.update(load="serial_single_client", unmeasured=["live_desktop_actuator", "live_chrome_media_postcondition", "physical_iot_state", "live_microphone_acoustic_response"])
    return facts


def offline(directory, samples, warmup):
    from features.system.fast import match_volume
    from features.browser.fast import match_media
    from features.iot.fast import match_ac_off_timer
    from services.browser_bridge import BrowserBridge
    from features.iot.client import IoTClient
    from voice.recovery import VoiceUtterance, assess_voice_utterance
    facts = metadata()
    facts.update(samples_per_case=samples, warmup_excluded=warmup,
                 conditions="Actual parser/recovery and real unavailable-dependency branches; no stub actuator success")
    session = Session(directory, mode="offline", metadata=facts)
    with tempfile.TemporaryDirectory(prefix="alice-baseline-", dir=session.directory) as temporary:
        bridge = BrowserBridge()
        client = IoTClient(SimpleNamespace(api_port=18787, token_path=Path(temporary) / "absent-token"))
        # Inputs are fixed artificial examples; never collect user speech for this run.
        noisy = VoiceUtterance("bật nhắc khuya lúc 23:30", confidence=.1,
                               alternatives=("bật nhắc khuya lúc 23:30", "tắt nhắc khuya lúc 23:30"), engine="fixture")
        if (match_volume("tăng âm lượng lên 35%") is None or match_media("tạm dừng video") is None
                or match_ac_off_timer("tắt máy lạnh sau 15 phút") is None or not assess_voice_utterance(noisy).retry):
            session.close()
            raise RuntimeError("Baseline fixture no longer exercises the intended code path")
        cases = [("fast_local", "matcher", "local_volume_parser", lambda: match_volume("tăng âm lượng lên 35%")),
                 ("browser_media", "matcher", "browser_pause_parser", lambda: match_media("tạm dừng video")),
                 ("iot", "matcher", "iot_timer_parser", lambda: match_ac_off_timer("tắt máy lạnh sau 15 phút")),
                 ("voice", "voice_recovery", "noisy_recovery_rules", lambda: assess_voice_utterance(noisy)),
                 ("browser_media", "browser_roundtrip", "extension_disconnected", lambda: bridge.send_command("GET_TABS")),
                 ("iot", "iot_roundtrip", "gateway_token_missing", client.status)]
        # Real negative branches produce warnings; suppress console volume only.
        import logging
        logging.getLogger("services.browser_bridge").setLevel(logging.ERROR)
        for channel, phase, scenario, operation in cases:
            for _ in range(warmup):
                try:
                    operation()
                except RuntimeError:
                    pass
            with use_session(session):
                for _ in range(samples):
                    # Adapter methods already own their span; parent is only a
                    # scenario carrier. Filter stage names when interpreting.
                    with measure(channel, "turn", scenario=scenario, cache="warm") as span:
                        if scenario in {"extension_disconnected", "gateway_token_missing"}:
                            span.set(dependency="unavailable")
                        try:
                            if phase.endswith("roundtrip"):
                                result = operation()
                                if isinstance(result, dict) and result.get("type") == "ERROR":
                                    span.set(outcome="failed")
                            else:
                                with measure(channel, phase):
                                    operation()
                        except RuntimeError:
                            span.set(outcome="failed")
    session.close()
    write_report(session.directory)
    return session.directory


def probe(directory, samples):
    from utils.config import config
    from features.iot.client import IoTClient
    from llm.client import build_default_llm_client, Message
    facts = metadata()
    facts.update(samples_per_case=samples, warmup_excluded=0, unavailable=[])
    session = Session(directory, mode="live_readonly", metadata=facts)
    with use_session(session):
        client = IoTClient()
        # GET /status never toggles relays, changes automation or emits IR.
        try:
            client.status()
        except RuntimeError:
            facts["unavailable"].append("iot_gateway_status")
        else:
            for index in range(samples):
                with measure("iot", "turn", scenario="gateway_status_readonly", cache="warm"):
                    try:
                        client.status()
                    except RuntimeError:
                        facts["unavailable"].append("iot_gateway_became_unavailable")
                        break
        # Baseline auto-probe is local only, never spends remote API credits.
        if config.LLM_PROVIDER != "ollama":
            facts["unavailable"].append("llm_probe_local_only")
        else:
            from urllib.parse import urlparse
            endpoint = urlparse(config.OLLAMA_URL)
            if endpoint.hostname not in {"127.0.0.1", "localhost", "::1"}:
                facts["unavailable"].append("ollama_endpoint_not_loopback")
            else:
                try:
                    with socket.create_connection((endpoint.hostname, endpoint.port or 11434), timeout=1):
                        pass
                except OSError:
                    facts["unavailable"].append("ollama_not_listening")
                else:
                    model = build_default_llm_client()
                    facts["llm_provider"] = "ollama"
                    facts["llm_model"] = config.OLLAMA_MODEL
                    for index in range(samples):
                        with measure("llm", "turn", scenario="local_llm_readonly", cache="unknown"):
                            try:
                                model.generate(system="Return only OK.", messages=[Message(role="user", text="Hello.")], tools=[])
                            except Exception as exc:
                                facts["unavailable"].append("llm_call_failed_" + type(exc).__name__)
                                break
    session.close()
    write_report(session.directory)
    return session.directory


def calibration(directory, samples):
    facts = metadata()
    facts.update(samples_per_case=samples, conditions="Alternating no-op off/on, exporter flush excluded")
    timings = {"disabled": [], "enabled": []}
    session = Session(directory, mode="calibration", metadata=facts)
    for _ in range(samples):
        with use_session(None):
            before = time.perf_counter_ns()
            with measure("fast_local", "noop"):
                pass
            timings["disabled"].append((time.perf_counter_ns() - before) / 1e9)
        with use_session(session):
            before = time.perf_counter_ns()
            with measure("fast_local", "noop", scenario="instrumentation_overhead", cache="warm"):
                pass
            timings["enabled"].append((time.perf_counter_ns() - before) / 1e9)
    from evals.latency import percentile
    facts["observer_total_call_s"] = {k: {"n": len(v), "p50": percentile(v,.5), "p95": percentile(v,.95), "p99": percentile(v,.99)} for k,v in timings.items()}
    (session.directory / "observer_samples.json").write_text(json.dumps(timings), encoding="utf-8")
    session.close()
    write_report(session.directory)
    return session.directory


def readonly(directory, samples, warmup, kind):
    from features.iot.client import IoTClient
    from utils.config import config
    from llm.client import Message, build_default_llm_client
    import logging
    facts = metadata()
    facts.update(samples_requested=samples, warmup_excluded=warmup, unavailable=[], conditions="Read-only isolated call; not full assistant turn")
    session = Session(directory, mode="live_readonly", metadata=facts)
    if kind == "iot":
        operation = IoTClient().status
        scenario = "gateway_status_readonly"
    else:
        # Production factory and limits, static artificial input, no tool schema.
        # Suppress provider error strings: existing errors can contain request URLs.
        logging.getLogger("llm.gemini").setLevel(logging.CRITICAL)
        scenario = "llm_readonly"
        facts.update(llm_provider=config.LLM_PROVIDER, llm_timeout_s=config.LLM_TIMEOUT,
                     llm_max_tokens=config.LLM_MAX_TOKENS,
                     llm_model_configuration=(config.GEMINI_MODELS if config.LLM_PROVIDER == "gemini" else config.OLLAMA_MODEL if config.LLM_PROVIDER == "ollama" else config.LLM_MODEL),
                     probe_prompt="fixed_short_no_tools", gap_s=10)
        with use_session(session):
            try:
                model = build_default_llm_client()
            except Exception as exc:
                facts["unavailable"].append("llm_setup_" + type(exc).__name__)
                session.close()
                write_report(session.directory)
                return session.directory
        operation = lambda: model.generate(system="Return only OK.", messages=[Message(role="user", text="Hello.")], tools=[])
    facts["warmup_completed"] = 0
    with use_session(None):
        for _ in range(warmup):
            try:
                operation()
            except Exception as exc:
                facts["unavailable"].append("warmup_" + type(exc).__name__)
                break
            facts["warmup_completed"] += 1
            if kind == "llm":
                time.sleep(10)
    with use_session(session):
        for index in range(samples):
            with measure("iot" if kind == "iot" else "llm", "turn", scenario=scenario, cache="unknown") as span:
                try:
                    operation()
                except Exception as exc:
                    facts["unavailable"].append("call_" + type(exc).__name__)
                    span.set(outcome="failed", error_type=type(exc).__name__)
                    break
            if kind == "llm" and index + 1 < samples:
                time.sleep(10)
    session.close()
    write_report(session.directory)
    return session.directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["offline", "probe", "calibration", "iot-readonly", "llm-readonly", "report"])
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "latency")
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    if args.samples < 1 or args.samples > 100000 or args.warmup < 0:
        parser.error("samples must be 1..100000; warmup must be non-negative")
    if args.mode == "report":
        if args.run is None:
            parser.error("report requires --run")
        write_report(args.run)
        print(args.run / "report.md")
        return
    if args.mode in {"probe", "llm-readonly"} and args.samples + (args.warmup if args.mode == "llm-readonly" else 0) > 20:
        parser.error("read-only probe is capped at 20 calls per dependency; use runtime traces for full baseline")
    path = (readonly(args.output, args.samples, args.warmup, "iot" if args.mode == "iot-readonly" else "llm") if args.mode.endswith("readonly") else
            offline(args.output, args.samples, args.warmup) if args.mode == "offline" else
            calibration(args.output, args.samples) if args.mode == "calibration" else probe(args.output, args.samples))
    print(path / "report.md")


if __name__ == "__main__":
    main()
