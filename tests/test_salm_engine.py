from datetime import datetime, timedelta, timezone

from features.salm.engine import (SCREEN_RESET_SECONDS, SCREEN_SOFT_SECONDS,
                                  WORK_RESET_SECONDS, WORK_SOFT_SECONDS, SalmEngine)
from features.salm.models import ActivitySnapshot, DisplayState


BASE = datetime(2030, 1, 1, tzinfo=timezone.utc)


def snap(t, **kwargs):
    values = dict(monotonic=float(t), wall_time=BASE + timedelta(seconds=t),
                  idle_seconds=0, foreground_app="code", display=DisplayState.ON,
                  running_apps=frozenset(("code",)))
    values.update(kwargs)
    return ActivitySnapshot(**values)


def test_interactive_time_goes_to_work_screen_and_foreground_app():
    engine = SalmEngine(max_sample_gap=10000)
    engine.update(snap(0))
    result = engine.update(snap(60))
    day = engine.daily["2030-01-01"]
    assert day.work_engagement == 60
    assert day.screen_exposure == 60
    assert day.apps["code"].interactive == 60
    assert not result.opportunities


def test_spotify_is_background_overlay_only():
    engine = SalmEngine(max_sample_gap=10000)
    audio = frozenset(("spotify",))
    engine.update(snap(0, audible_apps=audio,
                       running_apps=frozenset(("code", "spotify"))))
    engine.update(snap(10, audible_apps=audio,
                       running_apps=frozenset(("code", "spotify"))))
    day = engine.daily["2030-01-01"]
    assert day.apps["code"].interactive == 10
    assert day.apps["spotify"].background_audio == 10
    assert day.apps["spotify"].interactive == 0


def test_passive_video_counts_screen_not_work():
    engine = SalmEngine(max_sample_gap=10000)
    video = dict(idle_seconds=60, foreground_app="chrome",
                 gsmtc_apps=frozenset(("chrome",)))
    engine.update(snap(0, **video))
    engine.update(snap(120, **video))
    day = engine.daily["2030-01-01"]
    assert day.screen_exposure == 120
    assert day.work_engagement == 0
    assert day.apps["chrome"].passive_viewing == 120


def test_soft_opportunities_are_deduplicated():
    engine = SalmEngine(max_sample_gap=10000)
    engine.update(snap(0))
    first = engine.update(snap(WORK_SOFT_SECONDS))
    clocks = {(item.clock, item.level) for item in first.opportunities}
    assert ("work_engagement", "soft") in clocks
    assert ("screen_exposure", "soft") in clocks
    again = engine.update(snap(WORK_SOFT_SECONDS + 1))
    assert not again.opportunities


def test_work_reset_does_not_reset_screen_clock():
    engine = SalmEngine(max_sample_gap=10000)
    engine.update(snap(0))
    engine.update(snap(WORK_SOFT_SECONDS))
    engine.update(snap(WORK_SOFT_SECONDS + 1, idle_seconds=31))
    engine.update(snap(WORK_SOFT_SECONDS + 1 + WORK_RESET_SECONDS, idle_seconds=631))
    assert engine.work_clock == 0
    assert engine.screen_clock == WORK_SOFT_SECONDS + 1


def test_display_off_resets_screen_after_five_minutes():
    engine = SalmEngine(max_sample_gap=10000)
    engine.update(snap(0))
    engine.update(snap(SCREEN_SOFT_SECONDS))
    engine.update(snap(SCREEN_SOFT_SECONDS + 1, display=DisplayState.OFF))
    engine.update(snap(SCREEN_SOFT_SECONDS + 1 + SCREEN_RESET_SECONDS,
                       display=DisplayState.OFF))
    assert engine.screen_clock == 0


def test_idle_with_display_on_never_resets_screen():
    engine = SalmEngine(max_sample_gap=10000)
    engine.update(snap(0))
    engine.update(snap(60))
    engine.update(snap(61, idle_seconds=31))
    engine.update(snap(2000, idle_seconds=1970))
    assert engine.screen_clock == 61
    assert engine.screen_break == 0
    assert engine.daily["2030-01-01"].idle_gap > 0


def test_monotonic_jump_is_not_counted():
    engine = SalmEngine(max_sample_gap=30)
    engine.update(snap(100))
    engine.update(snap(90))
    engine.update(snap(1000))
    assert engine.work_clock == 0
    assert engine.screen_clock == 0


def test_sleep_credit_resets_clocks_without_counting_gap_as_usage():
    engine = SalmEngine(max_sample_gap=30)
    engine.update(snap(0))
    engine.update(snap(10))
    engine.update(snap(10000, idle_seconds=None, no_screen_break_seconds=700))
    assert engine.work_clock == 0
    assert engine.screen_clock == 0
    assert engine.daily["2030-01-01"].confirmed_break == 700


def test_suspend_closes_active_interval_and_resume_without_input_is_unknown():
    engine = SalmEngine(max_sample_gap=30)
    engine.update(snap(0))
    suspended = engine.update(snap(10, suspended=True))
    assert len(suspended.closed_intervals) == 1
    assert suspended.state.presence.value == "suspended"
    resumed = engine.update(snap(1000, idle_seconds=None,
                                 no_screen_break_seconds=990))
    assert resumed.state.presence.value == "unknown"
    assert engine.work_clock == 0
    assert engine.screen_clock == 0
