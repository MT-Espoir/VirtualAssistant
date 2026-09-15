from datetime import datetime, timedelta, timezone

from features.salm.models import (ActivityKind, ActivitySnapshot, Confidence,
                                  DisplayState, MediaKind, Presence)
from features.salm.reducer import derive_state


BASE = datetime(2030, 1, 1, tzinfo=timezone.utc)


def snap(t=0, **kwargs):
    values = dict(monotonic=float(t), wall_time=BASE + timedelta(seconds=t),
                  idle_seconds=0, foreground_app="code", display=DisplayState.ON,
                  running_apps=frozenset(("code",)))
    values.update(kwargs)
    return ActivitySnapshot(**values)


def test_idle_10_minutes_is_away_since_last_input():
    state = derive_state(snap(700, idle_seconds=600))
    assert state.presence == Presence.AWAY
    assert state.activity == ActivityKind.AMBIGUOUS_IDLE
    assert state.since_monotonic == 100
    assert state.since_wall == BASE + timedelta(seconds=100)


def test_idle_transition_keeps_original_idle_start():
    candidate = derive_state(snap(40, idle_seconds=40))
    away = derive_state(snap(600, idle_seconds=600), candidate)
    assert away.presence == Presence.AWAY
    assert away.since_monotonic == candidate.since_monotonic == 0


def test_background_audio_does_not_steal_foreground_activity():
    state = derive_state(snap(audible_apps=frozenset(("spotify",))))
    assert state.activity == ActivityKind.ACTIVE_INTERACTIVE
    assert state.media == MediaKind.BACKGROUND_AUDIO
    assert state.primary_app == "code"


def test_foreground_playback_with_low_input_is_passive_viewing():
    state = derive_state(snap(idle_seconds=90, foreground_app="chrome",
                              foreground_fullscreen=True,
                              gsmtc_apps=frozenset(("chrome",))))
    assert state.presence == Presence.PRESENT
    assert state.activity == ActivityKind.PASSIVE_VIEWING
    assert state.media == MediaKind.FOREGROUND_MEDIA
    assert state.confidence == Confidence.HIGH


def test_wasapi_foreground_playback_has_medium_confidence():
    state = derive_state(snap(idle_seconds=90, foreground_app="vlc",
                              audible_apps=frozenset(("vlc",))))
    assert state.activity == ActivityKind.PASSIVE_VIEWING
    assert state.confidence == Confidence.MEDIUM


def test_display_off_wins_over_media():
    state = derive_state(snap(idle_seconds=90, foreground_app="chrome",
                              display=DisplayState.OFF,
                              gsmtc_apps=frozenset(("chrome",))))
    assert state.presence == Presence.AWAY
    assert state.activity == ActivityKind.NONE
    assert state.media == MediaKind.BACKGROUND_AUDIO


def test_suspend_wins_everything():
    state = derive_state(snap(suspended=True, gsmtc_apps=frozenset(("chrome",))))
    assert state.presence == Presence.SUSPENDED
    assert state.activity == ActivityKind.NONE
