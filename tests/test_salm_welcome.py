from datetime import datetime, timezone
import threading

import app
from features.salm.models import (ActivityKind, Confidence, DerivedState,
                                  DisplayState, MediaKind, Presence)
from features.salm.welcome import (STARTUP_GREETING_TEXT,
                                   ReturnWelcomeTracker)
from utils.events import AssistantBus


WALL = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _state(presence, since):
    return DerivedState(
        presence=presence, display=DisplayState.ON,
        activity=(ActivityKind.ACTIVE_INTERACTIVE
                  if presence == Presence.PRESENT else ActivityKind.NONE),
        media=MediaKind.NONE, primary_app="code", confidence=Confidence.HIGH,
        evidence=(), since_monotonic=since, since_wall=WALL)


def test_idle_candidate_does_not_create_a_false_welcome():
    tracker = ReturnWelcomeTracker(min_absence=120)
    assert tracker.observe(_state(Presence.IDLE_CANDIDATE, 0), 90, WALL) is None
    assert tracker.observe(_state(Presence.PRESENT, 91), 91, WALL) is None


def test_confirmed_away_uses_original_idle_start_and_emits_once_on_return():
    tracker = ReturnWelcomeTracker(min_absence=120)
    assert tracker.observe(_state(Presence.AWAY, 0), 600, WALL) is None
    event = tracker.observe(_state(Presence.PRESENT, 601), 601, WALL)
    assert event.absence_seconds == 601
    assert event.origin == "away"
    assert tracker.observe(_state(Presence.PRESENT, 602), 602, WALL) is None


def test_short_absence_is_ignored_and_unknown_after_resume_keeps_session_open():
    tracker = ReturnWelcomeTracker(min_absence=120)
    tracker.observe(_state(Presence.AWAY, 100), 100, WALL)
    assert tracker.observe(_state(Presence.PRESENT, 150), 150, WALL) is None

    tracker.observe(_state(Presence.SUSPENDED, 200), 200, WALL)
    assert tracker.observe(_state(Presence.UNKNOWN, 260), 260, WALL) is None
    event = tracker.observe(_state(Presence.PRESENT, 330), 330, WALL)
    assert event.absence_seconds == 130
    assert event.origin == "suspended"


def test_welcome_cooldown_only_suppresses_nearby_transition_noise():
    tracker = ReturnWelcomeTracker(min_absence=120, cooldown=300)
    tracker.observe(_state(Presence.AWAY, 0), 0, WALL)
    assert tracker.observe(_state(Presence.PRESENT, 200), 200, WALL) is not None
    tracker.observe(_state(Presence.AWAY, 250), 250, WALL)
    assert tracker.observe(_state(Presence.PRESENT, 400), 400, WALL) is None
    tracker.observe(_state(Presence.AWAY, 501), 501, WALL)
    assert tracker.observe(_state(Presence.PRESENT, 701), 701, WALL) is not None


class _Dispatcher:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.item = None

    def submit(self, item):
        self.item = item
        return self.accepted


class _Synth:
    def __init__(self):
        self.spoken = []

    def speak_sync(self, text):
        self.spoken.append(text)

    def stop(self):
        pass


def test_startup_greeting_finishes_before_input_starts():
    dispatcher, synth, bus = _Dispatcher(), _Synth(), AssistantBus()
    completed = []
    assert app._start_with_greeting(
        dispatcher, synth, bus, lambda: completed.append(True))
    assert completed == []
    dispatcher.item.present()
    assert synth.spoken == [STARTUP_GREETING_TEXT]
    assert completed == [True]
    assert [event.state for event in bus.drain()] == ["speaking", "idle"]


def test_blocked_or_dropped_startup_greeting_never_blocks_input():
    completed = []
    blocked = _Dispatcher(accepted=False)
    assert not app._start_with_greeting(
        blocked, None, AssistantBus(), lambda: completed.append("blocked"))
    assert completed == ["blocked"]

    completed.clear()
    queued = _Dispatcher()
    app._start_with_greeting(
        queued, None, AssistantBus(), lambda: completed.append("dropped"))
    queued.item.on_drop()
    queued.item.on_drop()
    assert completed == ["dropped"]


def test_startup_greeting_waits_for_custom_voice_before_speaking():
    class _LoadingSynth(_Synth):
        def __init__(self):
            super().__init__()
            self.wait_entered = threading.Event()
            self.ready = threading.Event()

        def wait_until_voice_ready(self, timeout=None):
            self.wait_entered.set()
            return self.ready.wait(timeout)

    dispatcher, synth, bus = _Dispatcher(), _LoadingSynth(), AssistantBus()
    completed = []
    app._start_with_greeting(dispatcher, synth, bus, lambda: completed.append(True))

    presenter = threading.Thread(target=dispatcher.item.present)
    presenter.start()
    assert synth.wait_entered.wait(1)
    assert synth.spoken == []
    assert completed == []

    synth.ready.set()
    presenter.join(1)
    assert not presenter.is_alive()
    assert synth.spoken == [STARTUP_GREETING_TEXT]
    assert completed == [True]


def test_failed_custom_voice_skips_greeting_but_releases_input():
    class _FailedSynth(_Synth):
        def wait_until_voice_ready(self, timeout=None):
            return False

    dispatcher, synth, bus = _Dispatcher(), _FailedSynth(), AssistantBus()
    completed = []
    app._start_with_greeting(dispatcher, synth, bus, lambda: completed.append(True))
    dispatcher.item.present()

    assert synth.spoken == []
    assert completed == [True]
    assert bus.drain() == []
