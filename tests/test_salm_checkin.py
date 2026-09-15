import threading
import time
from datetime import datetime, timezone

import app
from features.salm.checkin import (CheckInResponseWindow,
                                    SCREEN_HARD_CHECKIN_TEXT,
                                    SCREEN_SOFT_CHECKIN_TEXT,
                                    SNOOZE_REPLY_TEXT, WORK_CHECKIN_TEXT,
                                    checkin_text, match_snooze)
from features.salm.intervention import InterventionGate
from features.salm.models import (ActivityKind, ActivitySnapshot,
                                  BreakOpportunity, Confidence, DerivedState,
                                  DisplayState, MediaKind, Presence)
from features.salm.policy import BreakOutcomeTracker, BreakPolicy, PolicyDecision
from features.salm.runtime import SalmRuntime


WALL = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _sample(now, idle=0, fullscreen=False):
    snapshot = ActivitySnapshot(
        monotonic=now, wall_time=WALL, idle_seconds=idle,
        foreground_app="code", foreground_fullscreen=fullscreen,
        display=DisplayState.ON, session_locked=False, meeting_open=False)
    state = DerivedState(
        presence=Presence.PRESENT, display=DisplayState.ON,
        activity=ActivityKind.ACTIVE_INTERACTIVE, media=MediaKind.NONE,
        primary_app="code", confidence=Confidence.HIGH, evidence=(),
        since_monotonic=now, since_wall=WALL, meeting_open=False)
    return snapshot, state


def _opp(cycle=0):
    return BreakOpportunity(
        "work_engagement", "soft", WALL, 3000, 3000,
        ("work_engagement_soft_threshold",), cycle)


def _evaluate(policy, gate, now, opportunities=(), idle=0, fullscreen=False,
              cycles=None):
    snapshot, state = _sample(now, idle, fullscreen)
    gate.update_activity(snapshot, state, now=now)
    return policy.evaluate(
        opportunities, state, snapshot, gate,
        {"work_engagement": 3000, "screen_exposure": 0},
        cycles or {"work_engagement": 0, "screen_exposure": 0})


def test_checkin_templates_are_deterministic_and_contain_no_private_context():
    assert checkin_text("work_engagement", "soft") == WORK_CHECKIN_TEXT
    assert checkin_text("screen_exposure", "soft") == SCREEN_SOFT_CHECKIN_TEXT
    assert checkin_text("screen_exposure", "hard") == SCREEN_HARD_CHECKIN_TEXT
    joined = " ".join((WORK_CHECKIN_TEXT, SCREEN_SOFT_CHECKIN_TEXT,
                       SCREEN_HARD_CHECKIN_TEXT)).lower()
    for forbidden in ("chrome", "vlc", "phút", "giờ", "bệnh", "chẩn đoán"):
        assert forbidden not in joined


def test_snooze_matcher_is_narrow_and_accent_insensitive():
    for text in ("Hoãn", "10 phút nữa", "để anh chốt nốt", "lát nữa nhé"):
        assert match_snooze(text)
    for text in ("mở Chrome", "tôi nghỉ rồi", "hoàn thành rồi", "không", ""):
        assert not match_snooze(text)


def test_response_window_consumes_one_snooze_and_expires():
    decision = PolicyDecision(
        "dispatch", "work_engagement:soft:0", "work_engagement", "soft",
        WALL, ("natural_pause",))
    window = CheckInResponseWindow(window_seconds=10)
    window.arm(decision, cycle_id=0, now=100)
    assert window.take_snooze("mở Chrome", 101) is None
    assert window.take_snooze("hoãn", 105).candidate_id == decision.candidate_id
    assert window.take_snooze("hoãn", 106) is None

    window.arm(decision, cycle_id=0, now=200)
    assert window.take_snooze("hoãn", 211) is None


def test_snooze_rechecks_once_at_deadline_and_still_needs_transition():
    policy, gate = BreakPolicy(), InterventionGate()
    first = _evaluate(policy, gate, 0, (_opp(),), idle=8)
    assert first.action == "dispatch"
    assert policy.snooze(first.candidate_id, now=10, seconds=600)

    assert _evaluate(policy, gate, 609, idle=8).reason_codes == ("snoozed",)
    recheck = _evaluate(policy, gate, 610, idle=8)
    assert recheck.action == "dispatch"
    assert recheck.candidate_id.endswith(":snooze:1")
    assert recheck.reason_codes == ("snooze_recheck", "natural_pause")
    assert _evaluate(policy, gate, 611, idle=8) is None


def test_snooze_recheck_drops_when_dnd_active_and_never_replays_late():
    policy, gate = BreakPolicy(), InterventionGate()
    first = _evaluate(policy, gate, 0, (_opp(),), idle=8)
    assert policy.snooze(first.candidate_id, now=10, seconds=600)
    gate.set_work_mode(True)
    blocked = _evaluate(policy, gate, 610, idle=8)
    assert blocked.action == "drop"
    assert blocked.reason_codes == ("snooze_recheck_blocked", "work_mode")
    gate.set_work_mode(False)
    assert _evaluate(policy, gate, 700, idle=8) is None


def test_restored_timed_dnd_rechecks_armed_candidate_only_once():
    policy, gate = BreakPolicy(), InterventionGate()
    gate.set_user_care_dnd(True)
    deferred = _evaluate(policy, gate, 0, (_opp(),), idle=8)
    assert deferred.action == "defer"
    assert "user_care_dnd" in deferred.reason_codes

    gate.set_user_care_dnd(False)
    policy.expire_user_dnd()
    recheck = _evaluate(policy, gate, 10, idle=8)
    assert recheck.action == "dispatch"
    assert recheck.reason_codes == ("dnd_recheck", "natural_pause")
    assert _evaluate(policy, gate, 20, idle=8) is None


def test_restored_timed_dnd_drops_once_if_another_gate_is_active():
    policy, gate = BreakPolicy(), InterventionGate()
    gate.set_user_care_dnd(True)
    _evaluate(policy, gate, 0, (_opp(),), idle=8)
    gate.set_user_care_dnd(False)
    gate.set_work_mode(True)
    policy.expire_user_dnd()
    dropped = _evaluate(policy, gate, 10, idle=8)
    assert dropped.action == "drop"
    assert dropped.reason_codes == ("dnd_recheck_blocked", "work_mode")
    gate.set_work_mode(False)
    assert _evaluate(policy, gate, 20, idle=8) is None


def test_break_during_snooze_discards_old_checkin():
    policy, gate = BreakPolicy(), InterventionGate()
    first = _evaluate(policy, gate, 0, (_opp(),), idle=8)
    assert policy.snooze(first.candidate_id, now=10, seconds=600)
    changed = {"work_engagement": 1, "screen_exposure": 0}
    assert _evaluate(policy, gate, 300, idle=8, cycles=changed) is None
    assert _evaluate(policy, gate, 610, idle=8, cycles=changed) is None


def test_checkin_outcomes_use_explicit_but_non_psychological_labels():
    decision = PolicyDecision(
        "dispatch", "work_engagement:soft:0", "work_engagement", "soft",
        WALL, ("natural_pause",))
    tracker = BreakOutcomeTracker(window_seconds=10)
    tracker.watch(decision, cycle_id=0, now=0, checkin=True)
    assert tracker.observe({"work_engagement": 1}, 1, WALL)[0].outcome == "accepted"
    tracker.watch(decision, cycle_id=1, now=20, checkin=True)
    assert tracker.observe({"work_engagement": 1}, 30, WALL)[0].outcome == "ignored"
    tracker.watch(decision, cycle_id=1, now=40, checkin=True)
    assert tracker.snooze(decision.candidate_id, WALL).outcome == "snoozed"


class _Storage:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)


class _Dispatcher:
    def __init__(self):
        self.items = []

    def submit(self, item):
        self.items.append(item)
        return True


class _PolicyAcceptsSnooze:
    def __init__(self):
        self.calls = []

    def snooze(self, candidate_id, now, seconds=600):
        self.calls.append((candidate_id, now, seconds))
        return True

    def discard_pending(self):
        return ()


def test_runtime_presents_l2_and_snooze_bypasses_llm():
    storage = _Storage()
    dispatcher = _Dispatcher()
    policy = _PolicyAcceptsSnooze()
    presented = []
    runtime = SalmRuntime(
        "unused", storage=storage, dispatcher=dispatcher, policy=policy,
        gentle_checkin=True,
        on_checkin=lambda action, decision, text: presented.append(
            (action, decision.candidate_id, text)))
    decision = PolicyDecision(
        "dispatch", "work_engagement:soft:3", "work_engagement", "soft",
        WALL, ("natural_pause",))
    runtime._handle_policy_decision(
        decision, now=10, cycles={"work_engagement": 3})

    dispatcher.items[0].present()
    now = time.monotonic()
    assert presented == [("present", decision.candidate_id, WORK_CHECKIN_TEXT)]
    assert runtime.try_snooze("để anh chốt nốt", now=now, at=WALL) == SNOOZE_REPLY_TEXT
    assert policy.calls == [(decision.candidate_id, now, 600.0)]
    assert storage.records[-1]["outcome"] == "snoozed"


def test_voice_turn_waits_for_listener_and_skips_if_user_just_spoke():
    coordinator = app._VoiceTurnCoordinator()
    listening = threading.Event()
    release = threading.Event()

    def listen():
        listening.set()
        release.wait(1)
        return b"user speech"

    heard = []
    listener = threading.Thread(target=lambda: coordinator.next_input(listen))
    listener.start()
    assert listening.wait(1)
    presenter = threading.Thread(
        target=lambda: heard.append(coordinator.present("cue", lambda: None)))
    presenter.start()
    release.set()
    listener.join(1)
    presenter.join(1)
    assert heard == [False]


def test_voice_turn_speaks_after_an_empty_listen_cycle():
    coordinator = app._VoiceTurnCoordinator()
    assert coordinator.next_input(lambda: None) is None
    spoken = []
    assert coordinator.present("cue", lambda: spoken.append(True)) is True
    assert spoken == [True]
