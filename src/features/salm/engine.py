"""Bộ máy session/metrics thuần của SALM.

Không thread, không Windows API và không I/O. Mọi test có thể replay snapshot với
fake monotonic clock; wall clock chỉ dùng để chia bucket ngày và ghi log.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from features.salm.models import (
    ActivityInterval,
    ActivityKind,
    ActivitySnapshot,
    BreakOpportunity,
    DailyMetrics,
    DerivedState,
    DisplayState,
    MediaKind,
    Presence,
)
from features.salm.reducer import derive_state


WORK_SOFT_SECONDS = 50 * 60.0
WORK_HARD_SECONDS = 90 * 60.0
SCREEN_SOFT_SECONDS = 45 * 60.0
SCREEN_HARD_SECONDS = 120 * 60.0
WORK_RESET_SECONDS = 10 * 60.0
SCREEN_RESET_SECONDS = 5 * 60.0


@dataclass(frozen=True)
class EngineUpdate:
    state: DerivedState
    closed_intervals: Tuple[ActivityInterval, ...] = ()
    opportunities: Tuple[BreakOpportunity, ...] = ()


class SalmEngine:
    """Tích lũy hai clock độc lập và phát opportunity shadow đúng một lần/cycle."""

    def __init__(self, max_sample_gap=30.0):
        self.max_sample_gap = max(1.0, float(max_sample_gap))
        self.state: Optional[DerivedState] = None
        self._snapshot: Optional[ActivitySnapshot] = None
        self.work_clock = 0.0
        self.screen_clock = 0.0
        self.work_break = 0.0
        self.screen_break = 0.0
        self._fired = {
            "work_engagement": set(),
            "screen_exposure": set(),
        }
        self.cycle_ids = {"work_engagement": 0, "screen_exposure": 0}
        self.daily: Dict[str, DailyMetrics] = {}
        self._interval_duration = 0.0

    def update(self, snapshot: ActivitySnapshot) -> EngineUpdate:
        new_state = derive_state(snapshot, self.state)
        closed: List[ActivityInterval] = []
        opportunities: List[BreakOpportunity] = []

        if snapshot.no_screen_break_seconds > 0:
            self._credit_no_screen_break(snapshot.no_screen_break_seconds,
                                         snapshot.wall_time)

        if self._snapshot is not None and self.state is not None:
            raw_dt = snapshot.monotonic - self._snapshot.monotonic
            # Tick lùi hoặc thread bị treo lâu đều không được biến thành duration giả.
            dt = raw_dt if 0.0 <= raw_dt <= self.max_sample_gap else 0.0
            if dt:
                self._accumulate(self._snapshot, self.state, dt)
                opportunities.extend(self._update_clocks(self.state, dt, snapshot.wall_time))
                self._interval_duration += dt

            if new_state.signature() != self.state.signature():
                closed.append(self._close_interval(snapshot))
                self._interval_duration = 0.0

        self._snapshot = snapshot
        self.state = new_state
        return EngineUpdate(new_state, tuple(closed), tuple(opportunities))

    def _credit_no_screen_break(self, seconds, at):
        seconds = max(0.0, float(seconds))
        if not seconds:
            return
        self._day(at).confirmed_break += seconds
        self.work_break += seconds
        self.screen_break += seconds
        if self.work_break >= WORK_RESET_SECONDS:
            if self.work_clock > 0 or self._fired["work_engagement"]:
                self.cycle_ids["work_engagement"] += 1
            self.work_clock = 0.0
            self.work_break = 0.0
            self._fired["work_engagement"].clear()
        if self.screen_break >= SCREEN_RESET_SECONDS:
            if self.screen_clock > 0 or self._fired["screen_exposure"]:
                self.cycle_ids["screen_exposure"] += 1
            self.screen_clock = 0.0
            self.screen_break = 0.0
            self._fired["screen_exposure"].clear()

    def finish(self, at_monotonic=None, at_wall=None) -> Tuple[ActivityInterval, ...]:
        """Đóng interval đang mở lúc shutdown mà không tự cộng một khoảng chưa đo."""
        if self._snapshot is None or self.state is None:
            return ()
        mono = self._snapshot.monotonic if at_monotonic is None else float(at_monotonic)
        wall = self._snapshot.wall_time if at_wall is None else at_wall
        tail = mono - self._snapshot.monotonic
        tail = tail if 0.0 <= tail <= self.max_sample_gap else 0.0
        duration = self._interval_duration + tail
        return (ActivityInterval(
            start=wall - timedelta(seconds=duration),
            end=wall,
            duration_seconds=duration,
            presence=self.state.presence,
            display=self.state.display,
            activity=self.state.activity,
            media=self.state.media,
            primary_app=self.state.primary_app,
            confidence=self.state.confidence,
            evidence=self.state.evidence,
            meeting_open=self.state.meeting_open,
        ),)

    def _day(self, when: datetime) -> DailyMetrics:
        key = when.astimezone().date().isoformat() if when.tzinfo else when.date().isoformat()
        if key not in self.daily:
            self.daily[key] = DailyMetrics()
        return self.daily[key]

    def _accumulate(self, snapshot, state, dt):
        day = self._day(snapshot.wall_time)
        media_apps = set(snapshot.gsmtc_apps) | set(snapshot.audible_apps)
        day.add_circadian(
            snapshot.wall_time, dt,
            interactive=state.activity == ActivityKind.ACTIVE_INTERACTIVE)

        for app_id in snapshot.running_apps:
            day.app(app_id).add("running", dt)
        if state.primary_app:
            app = day.app(state.primary_app)
            app.add("foreground", dt)
            if state.activity == ActivityKind.ACTIVE_INTERACTIVE:
                app.add("interactive", dt)
            elif state.activity == ActivityKind.PASSIVE_VIEWING:
                app.add("passive_viewing", dt)
        for app_id in media_apps:
            if app_id != state.primary_app:
                day.app(app_id).add("background_audio", dt)

        if state.activity == ActivityKind.ACTIVE_INTERACTIVE:
            day.work_engagement += dt
        if (state.display in (DisplayState.ON, DisplayState.DIM)
                and state.activity in (ActivityKind.ACTIVE_INTERACTIVE,
                                       ActivityKind.PASSIVE_VIEWING)):
            day.screen_exposure += dt
        if state.activity == ActivityKind.AMBIGUOUS_IDLE or state.presence == Presence.UNKNOWN:
            day.unknown_duration += dt
        if (state.activity == ActivityKind.AMBIGUOUS_IDLE
                and state.presence in (Presence.IDLE_CANDIDATE, Presence.AWAY)):
            day.idle_gap += dt
        if self._is_work_break(state):
            day.confirmed_break += dt

    @staticmethod
    def _is_work_break(state):
        return (state.presence in (Presence.IDLE_CANDIDATE, Presence.AWAY,
                                   Presence.SUSPENDED)
                or state.display == DisplayState.OFF)

    @staticmethod
    def _is_screen_break(state):
        # Idle-only AWAY có confidence medium và vẫn có thể là đọc trang tĩnh; không
        # dùng nó để reset screen clock. OFF/lock/suspend mới là bằng chứng no-screen.
        return (state.display == DisplayState.OFF
                or state.presence == Presence.SUSPENDED
                or "session_locked" in state.evidence)

    def _update_clocks(self, state, dt, at):
        out = []
        if state.activity == ActivityKind.ACTIVE_INTERACTIVE:
            self.work_clock += dt
            self.work_break = 0.0
        elif self._is_work_break(state):
            self.work_break += dt

        if (state.display in (DisplayState.ON, DisplayState.DIM)
                and state.activity in (ActivityKind.ACTIVE_INTERACTIVE,
                                       ActivityKind.PASSIVE_VIEWING)):
            self.screen_clock += dt
            self.screen_break = 0.0
        elif self._is_screen_break(state):
            self.screen_break += dt

        if self.work_break >= WORK_RESET_SECONDS:
            self.work_clock = 0.0
            self.work_break = 0.0
            self._fired["work_engagement"].clear()
        if self.screen_break >= SCREEN_RESET_SECONDS:
            self.screen_clock = 0.0
            self.screen_break = 0.0
            self._fired["screen_exposure"].clear()

        out.extend(self._opportunities("work_engagement", self.work_clock,
                                      WORK_SOFT_SECONDS, WORK_HARD_SECONDS, at))
        out.extend(self._opportunities("screen_exposure", self.screen_clock,
                                      SCREEN_SOFT_SECONDS, SCREEN_HARD_SECONDS, at))
        return out

    def _opportunities(self, clock, value, soft, hard, at):
        out = []
        for level, threshold in (("soft", soft), ("hard", hard)):
            if value >= threshold and level not in self._fired[clock]:
                self._fired[clock].add(level)
                out.append(BreakOpportunity(
                    clock=clock,
                    level=level,
                    at=at,
                    value_seconds=value,
                    threshold_seconds=threshold,
                    reason_codes=(f"{clock}_{level}_threshold",),
                    cycle_id=self.cycle_ids[clock],
                ))
        return out

    def _close_interval(self, snapshot):
        start = snapshot.wall_time - timedelta(seconds=self._interval_duration)
        return ActivityInterval(
            start=start,
            end=snapshot.wall_time,
            duration_seconds=self._interval_duration,
            presence=self.state.presence,
            display=self.state.display,
            activity=self.state.activity,
            media=self.state.media,
            primary_app=self.state.primary_app,
            confidence=self.state.confidence,
            evidence=self.state.evidence,
            meeting_open=self.state.meeting_open,
        )

    def diagnostic(self):
        state = self.state
        return {
            "state": None if state is None else {
                "presence": state.presence.value,
                "display": state.display.value,
                "activity": state.activity.value,
                "media": state.media.value,
                "primary_app": state.primary_app,
                "confidence": state.confidence.value,
                "evidence": list(state.evidence),
                "meeting_open": state.meeting_open,
            },
            "clocks": {
                "work_engagement": round(self.work_clock, 3),
                "screen_exposure": round(self.screen_clock, 3),
                "work_break": round(self.work_break, 3),
                "screen_break": round(self.screen_break, 3),
            },
            "cycle_ids": dict(self.cycle_ids),
        }
