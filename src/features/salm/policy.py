"""Policy thuần SALM-0B: opportunity -> drop/defer/coalesce/dispatch."""

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from features.salm.engine import (SCREEN_HARD_SECONDS, SCREEN_SOFT_SECONDS,
                                  WORK_HARD_SECONDS, WORK_SOFT_SECONDS)
from features.salm.models import BreakOpportunity, MediaKind, Presence

NATURAL_PAUSE_MIN = 8.0
NATURAL_PAUSE_MAX = 90.0
FOREGROUND_STABLE = 3.0
SOFT_WAIT_MAX = 15 * 60.0
HARD_WAIT_MAX = 5 * 60.0
GLOBAL_CUE_COOLDOWN = 20 * 60.0
COURTESY_AFTER_RETURN = 2 * 60.0
SNOOZE_DEFAULT = 10 * 60.0

_THRESHOLDS = {
    ("work_engagement", "soft"): WORK_SOFT_SECONDS,
    ("work_engagement", "hard"): WORK_HARD_SECONDS,
    ("screen_exposure", "soft"): SCREEN_SOFT_SECONDS,
    ("screen_exposure", "hard"): SCREEN_HARD_SECONDS,
}


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    candidate_id: str
    clock: str
    level: str
    at: datetime
    reason_codes: Tuple[str, ...]
    coalesced_ids: Tuple[str, ...] = ()

    def to_record(self, shadow=True):
        return {
            "kind": "policy_decision",
            "at": self.at.isoformat(),
            "candidate_id": self.candidate_id,
            "clock": self.clock,
            "level": self.level,
            "decision": "would_dispatch" if shadow and self.action == "dispatch" else self.action,
            "reason_codes": list(self.reason_codes),
            "coalesced_ids": list(self.coalesced_ids),
        }


@dataclass(frozen=True)
class PolicyOutcome:
    candidate_id: str
    clock: str
    level: str
    at: datetime
    outcome: str

    def to_record(self):
        return {
            "kind": "policy_outcome",
            "at": self.at.isoformat(),
            "candidate_id": self.candidate_id,
            "clock": self.clock,
            "level": self.level,
            "outcome": self.outcome,
        }


@dataclass
class _OutcomeWatch:
    decision: PolicyDecision
    cycle_id: int
    deadline: float
    checkin: bool = False


class BreakOutcomeTracker:
    """Ghi kết quả quan sát trung tính sau cue, không suy diễn ý định người dùng."""

    def __init__(self, window_seconds=5 * 60.0):
        self.window_seconds = max(0.0, float(window_seconds))
        self._watches = {}
        self._lock = threading.Lock()

    def watch(self, decision, cycle_id, now, checkin=False):
        with self._lock:
            self._watches[decision.candidate_id] = _OutcomeWatch(
                decision, int(cycle_id), float(now) + self.window_seconds,
                bool(checkin))

    def discard(self, candidate_id):
        with self._lock:
            self._watches.pop(candidate_id, None)

    def cancel(self, candidate_id, at):
        with self._lock:
            watch = self._watches.pop(candidate_id, None)
        return self._record(watch, at, "cue_cancelled") if watch else None

    def snooze(self, candidate_id, at):
        """Ghi phản hồi tường minh và kết thúc watch cũ trước lượt re-evaluate."""
        with self._lock:
            watch = self._watches.pop(candidate_id, None)
        return self._record(watch, at, "snoozed") if watch else None

    def resolve(self, candidate_id, at, outcome):
        """Kết thúc watch bằng một phản hồi tường minh đã được policy xác thực."""
        if outcome not in ("declined", "care_dnd"):
            raise ValueError("outcome phản hồi SALM không hợp lệ")
        with self._lock:
            watch = self._watches.pop(candidate_id, None)
        return self._record(watch, at, outcome) if watch else None

    def observe(self, cycles, now, at):
        outcomes = []
        with self._lock:
            for candidate_id, watch in tuple(self._watches.items()):
                current_cycle = cycles.get(watch.decision.clock, watch.cycle_id)
                if current_cycle != watch.cycle_id:
                    outcome = ("accepted" if watch.checkin
                               else "qualifying_break_observed")
                elif float(now) >= watch.deadline:
                    outcome = ("ignored" if watch.checkin
                               else "no_qualifying_break_observed")
                else:
                    continue
                self._watches.pop(candidate_id, None)
                outcomes.append(self._record(watch, at, outcome))
        return tuple(outcomes)

    @staticmethod
    def _record(watch, at, outcome):
        return PolicyOutcome(
            candidate_id=watch.decision.candidate_id,
            clock=watch.decision.clock,
            level=watch.decision.level,
            at=at,
            outcome=outcome,
        )


@dataclass
class _Armed:
    opportunity: BreakOpportunity
    armed_at: float

    @property
    def candidate_id(self):
        return (f"{self.opportunity.clock}:{self.opportunity.level}:"
                f"{self.opportunity.cycle_id}")


@dataclass
class _Snoozed:
    armed: _Armed
    due: float
    attempt: int


class BreakPolicy:
    def __init__(self):
        self._armed = {}
        self._delivered = set()
        self._last_cue_at = None
        self._snooze_until = 0.0
        self._courtesy_until = 0.0
        self._previous_state = None
        self._previous_fullscreen = False
        self._last_app = None
        self._app_changed_at = None
        self._recent_dispatch = {}
        self._snoozed = None
        self._snooze_attempts = {}
        self._dnd_recheck = False

    def cue_cooldown_active(self, now):
        """Shared care cooldown queried by other care producers."""
        return (self._last_cue_at is not None
                and float(now) - self._last_cue_at < GLOBAL_CUE_COOLDOWN)

    def register_external_cue(self, now):
        """Let another care signal win this tick without producing two reminders."""
        self._last_cue_at = float(now)

    def snooze(self, candidate_id, now, seconds=SNOOZE_DEFAULT):
        """Hẹn đúng một lần re-evaluate cho check-in vừa được phát."""
        armed = self._recent_dispatch.get(candidate_id)
        if armed is None:
            return False
        base_id = armed.candidate_id
        attempt = self._snooze_attempts.get(base_id, 0) + 1
        self._snooze_attempts[base_id] = attempt
        due = float(now) + max(0.0, float(seconds))
        self._snooze_until = max(self._snooze_until, due)
        self._snoozed = _Snoozed(armed, due, attempt)
        return True

    def discard_pending(self, keep_snoozed=False):
        """Consume cue đã arm để DND/resume không phát bù backlog cũ."""
        ids = tuple(item.candidate_id for item in self._armed.values())
        self._consume(ids)
        if not keep_snoozed:
            self._snoozed = None
            self._snooze_until = 0.0
        return ids

    def expire_user_dnd(self):
        """Yêu cầu đúng một lần xét candidate hiện hành khi timed DND hết hạn.

        Nếu DND được đặt từ check-in trong chính phiên này thì `_snoozed` đã giữ đúng
        candidate gốc; chỉ cần cờ riêng cho timed state được restore sau restart.
        """
        if self._snoozed is None:
            self._dnd_recheck = True

    def evaluate(self, opportunities, state, snapshot, gate, clocks, cycles,
                 now=None):
        now = snapshot.monotonic if now is None else float(now)
        self._sync_cycles(cycles)
        for opportunity in opportunities:
            candidate_id = (f"{opportunity.clock}:{opportunity.level}:"
                            f"{opportunity.cycle_id}")
            if candidate_id in self._delivered:
                continue
            current = self._armed.get(opportunity.clock)
            if current is None or opportunity.level == "hard":
                self._armed[opportunity.clock] = _Armed(opportunity, now)

        transition = self._observe_transition(state, snapshot, now)
        if self._snoozed is not None:
            return self._evaluate_snoozed(
                state, snapshot, gate, cycles, transition, now)
        if not self._armed:
            self._dnd_recheck = False
            return None

        selected = self._select(clocks)
        opportunity = selected.opportunity
        age = max(0.0, now - selected.armed_at)

        if self._dnd_recheck:
            self._dnd_recheck = False
            ids = tuple(item.candidate_id for item in self._armed.values())
            self._consume(ids)
            reasons = gate.reasons("break_care", now=now)
            if reasons:
                return self._decision(
                    "drop", selected, snapshot.wall_time,
                    ("dnd_recheck_blocked",) + tuple(reasons), ids)
            if not transition:
                return self._decision(
                    "drop", selected, snapshot.wall_time,
                    ("dnd_recheck_no_transition",), ids)
            self._last_cue_at = now
            decision = self._decision(
                "dispatch", selected, snapshot.wall_time,
                ("dnd_recheck", transition), ids)
            self._recent_dispatch[decision.candidate_id] = selected
            return decision

        if opportunity.level == "soft" and age > SOFT_WAIT_MAX:
            self._armed.pop(opportunity.clock, None)
            return self._decision("drop", selected, snapshot.wall_time,
                                  ("soft_wait_expired",))

        reasons = gate.reasons("break_care", now=now)
        if reasons:
            return self._decision("defer", selected, snapshot.wall_time, reasons)
        if now < self._snooze_until:
            return self._decision("defer", selected, snapshot.wall_time, ("snoozed",))
        if now < self._courtesy_until:
            return self._decision("defer", selected, snapshot.wall_time,
                                  ("courtesy_after_return",))

        if self._last_cue_at is not None and now - self._last_cue_at < GLOBAL_CUE_COOLDOWN:
            ids = tuple(item.candidate_id for item in self._armed.values())
            self._consume(ids)
            return self._decision("coalesce", selected, snapshot.wall_time,
                                  ("global_cue_cooldown",), ids)

        hard_timeout = opportunity.level == "hard" and age >= HARD_WAIT_MAX
        if not transition and not hard_timeout:
            return self._decision("defer", selected, snapshot.wall_time,
                                  ("waiting_natural_transition",))

        ids = tuple(item.candidate_id for item in self._armed.values())
        self._recent_dispatch[selected.candidate_id] = selected
        self._consume(ids)
        self._last_cue_at = now
        reason = "hard_wait_elapsed" if hard_timeout and not transition else transition
        return self._decision("dispatch", selected, snapshot.wall_time, (reason,), ids)

    def _sync_cycles(self, cycles):
        for clock, armed in tuple(self._armed.items()):
            if cycles.get(clock) != armed.opportunity.cycle_id:
                self._armed.pop(clock, None)
        snoozed = self._snoozed
        if (snoozed is not None
                and cycles.get(snoozed.armed.opportunity.clock)
                != snoozed.armed.opportunity.cycle_id):
            self._snoozed = None
        for candidate_id, armed in tuple(self._recent_dispatch.items()):
            if cycles.get(armed.opportunity.clock) != armed.opportunity.cycle_id:
                self._recent_dispatch.pop(candidate_id, None)

    def _evaluate_snoozed(self, state, snapshot, gate, cycles, transition, now):
        """Đến hạn chỉ quyết định một lần; block/no-transition thì bỏ, không nhắc muộn."""
        snoozed = self._snoozed
        if snoozed is None:
            return None
        armed = snoozed.armed
        opportunity = armed.opportunity
        if cycles.get(opportunity.clock) != opportunity.cycle_id:
            self._snoozed = None
            return None
        candidate_id = f"{armed.candidate_id}:snooze:{snoozed.attempt}"
        if now < snoozed.due:
            return PolicyDecision(
                "defer", candidate_id, opportunity.clock, opportunity.level,
                snapshot.wall_time, ("snoozed",))

        # Consume trước khi quyết định: đây là lần re-evaluate duy nhất của snooze này.
        self._snoozed = None
        self._snooze_until = 0.0
        coalesced = tuple(item.candidate_id for item in self._armed.values())
        self._consume(coalesced)
        reasons = gate.reasons("break_care", now=now)
        if reasons:
            return PolicyDecision(
                "drop", candidate_id, opportunity.clock, opportunity.level,
                snapshot.wall_time, ("snooze_recheck_blocked",) + tuple(reasons),
                coalesced)
        if not transition:
            return PolicyDecision(
                "drop", candidate_id, opportunity.clock, opportunity.level,
                snapshot.wall_time, ("snooze_recheck_no_transition",), coalesced)

        self._last_cue_at = now
        decision = PolicyDecision(
            "dispatch", candidate_id, opportunity.clock, opportunity.level,
            snapshot.wall_time, ("snooze_recheck", transition), coalesced)
        self._recent_dispatch[candidate_id] = armed
        return decision

    def _observe_transition(self, state, snapshot, now):
        transition = None
        previous = self._previous_state
        if (previous is not None
                and previous.presence in (Presence.IDLE_CANDIDATE, Presence.AWAY)
                and state.presence == Presence.PRESENT):
            gap = max(0.0, now - previous.since_monotonic)
            if gap >= 120.0:
                self._courtesy_until = max(self._courtesy_until,
                                           now + COURTESY_AFTER_RETURN)

        idle = snapshot.idle_seconds
        if idle is not None and NATURAL_PAUSE_MIN <= idle <= NATURAL_PAUSE_MAX:
            transition = "natural_pause"
        if (previous is not None and previous.media == MediaKind.FOREGROUND_MEDIA
                and state.media != MediaKind.FOREGROUND_MEDIA):
            transition = "media_stopped"
        if self._previous_fullscreen and not snapshot.foreground_fullscreen:
            transition = "fullscreen_exited"

        app = state.primary_app
        if app != self._last_app:
            self._last_app = app
            self._app_changed_at = now
        elif (self._app_changed_at is not None and app is not None
              and now - self._app_changed_at >= FOREGROUND_STABLE):
            transition = transition or "foreground_stable"
            self._app_changed_at = None

        self._previous_state = state
        self._previous_fullscreen = bool(snapshot.foreground_fullscreen)
        return transition

    def _select(self, clocks):
        def rank(item):
            opportunity = item.opportunity
            threshold = _THRESHOLDS[(opportunity.clock, opportunity.level)]
            return (1 if opportunity.level == "hard" else 0,
                    clocks.get(opportunity.clock, 0.0) / threshold)
        return max(self._armed.values(), key=rank)

    def _consume(self, ids):
        self._delivered.update(ids)
        for clock, item in tuple(self._armed.items()):
            if item.candidate_id in ids:
                self._armed.pop(clock, None)

    @staticmethod
    def _decision(action, selected, at, reasons, coalesced=()):
        opportunity = selected.opportunity
        return PolicyDecision(
            action=action,
            candidate_id=selected.candidate_id,
            clock=opportunity.clock,
            level=opportunity.level,
            at=at,
            reason_codes=tuple(reasons),
            coalesced_ids=tuple(coalesced),
        )
