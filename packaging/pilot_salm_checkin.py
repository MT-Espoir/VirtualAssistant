"""Pilot cô lập SALM-1 qua policy -> dispatcher -> VieNeu TTS.

Chạy từ gốc repo:
    python packaging/pilot_salm_checkin.py
    python packaging/pilot_salm_checkin.py --dry-run

Mặc định script đọc một gentle check-in và câu xác nhận snooze bằng đúng TTS đang cấu
hình. Nếu giọng chính chưa sẵn sàng/nạp lỗi, pilot dừng và tuyệt đối không dùng fallback.
Opportunity và thời gian +10 phút đều là clock giả trong bộ nhớ; không ghi log SALM thật.
"""

import argparse
import os
import sys
import time
from datetime import datetime


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import app  # noqa: E402
from features.salm.checkin import SNOOZE_REPLY_TEXT  # noqa: E402
from features.salm.intervention import (InterventionGate,
                                         ProactiveDispatcher)  # noqa: E402
from features.salm.models import (ActivityKind, ActivitySnapshot,  # noqa: E402
                                  BreakOpportunity, Confidence,
                                  DerivedState, DisplayState,
                                  MediaKind, Presence)
from features.salm.policy import BreakPolicy  # noqa: E402
from features.salm.runtime import SalmRuntime  # noqa: E402
from utils.events import AssistantBus  # noqa: E402


class _MemoryStorage:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(dict(record))


def _activity(now, idle=8.0):
    wall = datetime.now().astimezone()
    snapshot = ActivitySnapshot(
        monotonic=now, wall_time=wall, idle_seconds=idle,
        foreground_app="pilot", foreground_fullscreen=False,
        display=DisplayState.ON, session_locked=False, meeting_open=False)
    state = DerivedState(
        presence=Presence.PRESENT, display=DisplayState.ON,
        activity=ActivityKind.ACTIVE_INTERACTIVE, media=MediaKind.NONE,
        primary_app="pilot", confidence=Confidence.HIGH,
        evidence=("pilot_fixture",), since_monotonic=now,
        since_wall=wall, meeting_open=False)
    return snapshot, state


def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    return None


def run(dry_run=False):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    synth = None
    bus = AssistantBus()
    if not dry_run:
        print("[1/4] Đang chờ VieNeu sẵn sàng...", flush=True)
        synth = app._make_speaker()
        waiter = getattr(synth, "wait_until_voice_ready", None) if synth else None
        if waiter is None or not waiter(app.STARTUP_GREETING_VOICE_TIMEOUT_S):
            print("FAIL: giọng custom không sẵn sàng; không phát bằng fallback.", flush=True)
            return 2
        print("      VieNeu đã sẵn sàng.", flush=True)
    else:
        print("[1/4] Dry-run: bỏ qua TTS.", flush=True)

    gate = InterventionGate()
    dispatcher = ProactiveDispatcher(gate, poll_seconds=0.01)
    policy = BreakPolicy()
    storage = _MemoryStorage()
    spoken = []

    def on_checkin(action, decision, text):
        if action == "cancel":
            if synth is not None:
                synth.stop()
            return True
        spoken.append(text)
        print(f"[2/4] L2 được phép phát: {decision.candidate_id}", flush=True)
        if synth is not None:
            app._say(synth, bus, text, "happy", proactive=True)
        return True

    runtime = SalmRuntime(
        "unused", storage=storage, gate=gate, dispatcher=dispatcher,
        policy=policy, policy_shadow=True, silent_care=True,
        gentle_checkin=True, on_checkin=on_checkin)
    dispatcher.start()
    base = time.monotonic()
    cycles = {"work_engagement": 0, "screen_exposure": 0}
    clocks = {"work_engagement": 3000.0, "screen_exposure": 0.0}
    snapshot, state = _activity(base)
    gate.update_activity(snapshot, state, now=base)
    opportunity = BreakOpportunity(
        clock="work_engagement", level="soft", at=snapshot.wall_time,
        value_seconds=3000.0, threshold_seconds=3000.0,
        reason_codes=("pilot_work_soft_threshold",), cycle_id=0)

    try:
        decision = policy.evaluate(
            (opportunity,), state, snapshot, gate, clocks, cycles, now=base)
        if decision is None or decision.action != "dispatch":
            print(f"FAIL: policy không dispatch ({decision}).", flush=True)
            return 3
        runtime._handle_policy_decision(decision, now=base, cycles=cycles)
        session = _wait_until(lambda: runtime.checkins.active(time.monotonic()), timeout=90)
        if session is None or len(spoken) != 1:
            print("FAIL: check-in không mở được cửa sổ phản hồi.", flush=True)
            return 4

        snooze_now = time.monotonic()
        reply = runtime.try_snooze("hoãn", now=snooze_now,
                                    at=datetime.now().astimezone())
        if reply != SNOOZE_REPLY_TEXT:
            print("FAIL: fast command snooze không được nhận.", flush=True)
            return 5
        print("[3/4] Nhận 'hoãn' không qua LLM; snooze = 10 phút.", flush=True)
        if synth is not None:
            app._say(synth, bus, reply, "happy", proactive=True)

        # Nhảy clock giả tới đúng hạn. DND phải biến lần re-evaluate duy nhất thành DROP;
        # khi mở DND sau đó policy không được phát bù.
        due = snooze_now + 600.0
        gate.set_work_mode(True)
        due_snapshot, due_state = _activity(due)
        gate.update_activity(due_snapshot, due_state, now=due)
        blocked = policy.evaluate(
            (), due_state, due_snapshot, gate, clocks, cycles, now=due)
        gate.set_work_mode(False)
        later_snapshot, later_state = _activity(due + 1.0)
        gate.update_activity(later_snapshot, later_state, now=due + 1.0)
        replay = policy.evaluate(
            (), later_state, later_snapshot, gate, clocks, cycles, now=due + 1.0)
        if (blocked is None or blocked.action != "drop"
                or "snooze_recheck_blocked" not in blocked.reason_codes
                or replay is not None):
            print(f"FAIL: DND/replay sai: blocked={blocked}, replay={replay}", flush=True)
            return 6
        print("[4/4] DND chặn đúng hạn; mở lại không phát backlog.", flush=True)

        outcomes = [r.get("outcome") for r in storage.records if "outcome" in r]
        if outcomes != ["snoozed"]:
            print(f"FAIL: outcome không đúng: {outcomes}", flush=True)
            return 7
        print("PASS: SALM-1 pilot hoàn tất; không ghi dữ liệu SALM thật.", flush=True)
        return 0
    finally:
        dispatcher.stop()
        if synth is not None:
            synth.stop()


def main():
    parser = argparse.ArgumentParser(description="Pilot SALM-1 gentle check-in")
    parser.add_argument("--dry-run", action="store_true",
                        help="chạy policy/dispatcher/snooze/DND nhưng không khởi tạo TTS")
    args = parser.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
