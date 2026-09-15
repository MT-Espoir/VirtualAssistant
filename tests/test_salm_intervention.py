import threading
import time
from datetime import datetime, timezone

from features.salm.intervention import (Intervention, InterventionGate,
                                         ProactiveDispatcher)
from features.salm.models import (ActivityKind, ActivitySnapshot, Confidence,
                                  DerivedState, DisplayState, Presence)


def _activity(now, meeting=False, fullscreen=False):
    snapshot = ActivitySnapshot(
        monotonic=now, wall_time=datetime.now(timezone.utc), idle_seconds=0,
        foreground_app="code", foreground_fullscreen=fullscreen,
        display=DisplayState.ON, session_locked=False, meeting_open=meeting)
    state = DerivedState(
        presence=Presence.PRESENT, display=DisplayState.ON,
        activity=ActivityKind.ACTIVE_INTERACTIVE, media="none",
        primary_app="code", confidence=Confidence.HIGH, evidence=(),
        since_monotonic=now, since_wall=snapshot.wall_time,
        meeting_open=meeting)
    return snapshot, state


def test_gate_global_and_break_scopes_are_distinct():
    gate = InterventionGate(salm_enabled=False)
    snapshot, state = _activity(1)
    gate.update_activity(snapshot, state, now=1)
    assert gate.reasons("global", now=1) == ()
    assert "salm_disabled" in gate.reasons("break_care", now=1)

    gate.set_work_mode(True)
    assert "work_mode" in gate.reasons("global", now=1)


def test_meeting_unknown_does_not_release_dnd_and_exit_has_two_graces():
    gate = InterventionGate(meeting_exit_grace=8, post_dnd_grace=30)
    snap, state = _activity(0, meeting=True)
    gate.update_activity(snap, state, now=0)
    assert "meeting_open" in gate.reasons(now=0)

    snap, state = _activity(2, meeting=None)
    gate.update_activity(snap, state, now=2)
    assert "meeting_open" in gate.reasons(now=2)

    snap, state = _activity(10, meeting=False)
    gate.update_activity(snap, state, now=10)
    snap, state = _activity(18, meeting=False)
    gate.update_activity(snap, state, now=18)
    assert "meeting_open" not in gate.reasons(now=18)
    assert "post_dnd_grace" in gate.reasons("break_care", now=18)
    assert "post_dnd_grace" not in gate.reasons("break_care", now=49)


def test_dispatcher_checks_again_after_queueing():
    gate = InterventionGate()
    snap, state = _activity(0)
    gate.update_activity(snap, state, now=0)
    called = threading.Event()
    dropped = threading.Event()
    dispatcher = ProactiveDispatcher(gate)
    assert dispatcher.submit(Intervention("queued", called.set,
                                          on_drop=dropped.set))
    gate.set_work_mode(True)
    dispatcher.start()
    try:
        assert not called.wait(0.15)
        assert dropped.is_set()
    finally:
        dispatcher.stop()


def test_gate_change_cancels_active_intervention_once():
    gate = InterventionGate()
    snap, state = _activity(0)
    gate.update_activity(snap, state, now=0)
    started = threading.Event()
    cancelled = threading.Event()
    calls = []
    dispatcher = ProactiveDispatcher(gate, poll_seconds=0.01)
    dispatcher.start()
    try:
        item = Intervention(
            "care", started.set,
            cancel=lambda: (calls.append("cancel"), cancelled.set()),
            active_seconds=2)
        assert dispatcher.submit(item)
        assert started.wait(1)
        gate.set_work_mode(True)
        assert cancelled.wait(1)
        time.sleep(0.05)
        assert calls == ["cancel"]
    finally:
        dispatcher.stop()


def test_fullscreen_blocks_break_care_but_not_unrelated_global_scope():
    gate = InterventionGate()
    snap, state = _activity(0, fullscreen=True)
    gate.update_activity(snap, state, now=0)
    assert gate.reasons("global", now=0) == ()
    assert "foreground_fullscreen" in gate.reasons("break_care", now=0)


def test_stopping_dispatcher_drops_queued_item():
    gate = InterventionGate()
    dropped = threading.Event()
    dispatcher = ProactiveDispatcher(gate)
    assert dispatcher.submit(Intervention("queued", lambda: None,
                                          on_drop=dropped.set))
    dispatcher.stop()
    assert dropped.is_set()


def test_submit_after_dispatcher_stopped_is_rejected_and_dropped():
    gate = InterventionGate()
    dropped = threading.Event()
    dispatcher = ProactiveDispatcher(gate)
    dispatcher.stop()
    assert not dispatcher.submit(Intervention(
        "late", lambda: None, on_drop=dropped.set))
    assert dropped.is_set()
