from datetime import datetime, timezone

from features.salm.intervention import InterventionGate
from features.salm.models import (ActivityKind, ActivitySnapshot,
                                  BreakOpportunity, Confidence, DerivedState,
                                  DisplayState, MediaKind, Presence)
from features.salm.policy import (BreakOutcomeTracker, BreakPolicy,
                                  PolicyDecision)


WALL = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _sample(now, app="code", idle=0, presence=Presence.PRESENT,
            fullscreen=False, meeting=False, since=None):
    snapshot = ActivitySnapshot(
        monotonic=now, wall_time=WALL, idle_seconds=idle,
        foreground_app=app, foreground_fullscreen=fullscreen,
        display=DisplayState.ON, session_locked=False, meeting_open=meeting)
    state = DerivedState(
        presence=presence, display=DisplayState.ON,
        activity=ActivityKind.ACTIVE_INTERACTIVE,
        media=MediaKind.NONE, primary_app=app, confidence=Confidence.HIGH,
        evidence=(), since_monotonic=now if since is None else since,
        since_wall=WALL, meeting_open=meeting)
    return snapshot, state


def _opp(clock="work_engagement", level="soft", cycle=0):
    threshold = 3000 if clock == "work_engagement" and level == "soft" else 5400
    if clock == "screen_exposure":
        threshold = 2700 if level == "soft" else 7200
    return BreakOpportunity(clock, level, WALL, threshold, threshold,
                            (f"{level}_threshold",), cycle)


def _evaluate(policy, gate, now, opportunities=(), app="code", idle=0,
              presence=Presence.PRESENT, fullscreen=False, cycles=None):
    snapshot, state = _sample(now, app, idle, presence, fullscreen)
    gate.update_activity(snapshot, state, now=now)
    return policy.evaluate(opportunities, state, snapshot, gate,
                           {"work_engagement": 5400, "screen_exposure": 7200},
                           cycles or {"work_engagement": 0, "screen_exposure": 0})


def test_soft_waits_for_a_natural_transition_then_dispatches():
    policy, gate = BreakPolicy(), InterventionGate()
    first = _evaluate(policy, gate, 0, (_opp(),))
    assert first.action == "defer"
    _evaluate(policy, gate, 5, app="chrome")
    decision = _evaluate(policy, gate, 8, app="chrome")
    assert decision.action == "dispatch"
    assert decision.reason_codes == ("foreground_stable",)


def test_global_cooldown_coalesces_current_candidates_without_backlog():
    policy, gate = BreakPolicy(), InterventionGate()
    _evaluate(policy, gate, 0, (_opp(),))
    assert _evaluate(policy, gate, 8, idle=8).action == "dispatch"
    decision = _evaluate(policy, gate, 100,
                         (_opp("screen_exposure", "soft"),))
    assert decision.action == "coalesce"
    assert decision.reason_codes == ("global_cue_cooldown",)
    assert _evaluate(policy, gate, 101) is None


def test_hard_candidate_dispatches_after_bounded_wait_without_transition():
    policy, gate = BreakPolicy(), InterventionGate()
    assert _evaluate(policy, gate, 0, (_opp(level="hard"),)).action == "defer"
    decision = _evaluate(policy, gate, 301, app="chrome")
    assert decision.action == "dispatch"
    assert decision.reason_codes == ("hard_wait_elapsed",)


def test_dnd_defers_and_re_evaluates_instead_of_replaying_transition():
    policy, gate = BreakPolicy(), InterventionGate()
    gate.set_work_mode(True)
    assert _evaluate(policy, gate, 0, (_opp(),), idle=8).reason_codes == ("work_mode",)
    gate.set_work_mode(False)
    decision = _evaluate(policy, gate, 1, idle=0)
    assert decision.action == "defer"
    assert decision.reason_codes == ("waiting_natural_transition",)


def test_fullscreen_and_post_return_courtesy_block_break_cue():
    policy, gate = BreakPolicy(), InterventionGate()
    decision = _evaluate(policy, gate, 0, (_opp(),), idle=8, fullscreen=True)
    assert "foreground_fullscreen" in decision.reason_codes

    policy, gate = BreakPolicy(), InterventionGate()
    _evaluate(policy, gate, 0, presence=Presence.AWAY)
    decision = _evaluate(policy, gate, 130, (_opp(),), idle=8,
                         presence=Presence.PRESENT)
    assert decision.reason_codes == ("courtesy_after_return",)


def test_cycle_change_discards_old_candidate_and_record_has_no_sensitive_context():
    policy, gate = BreakPolicy(), InterventionGate()
    decision = _evaluate(policy, gate, 0, (_opp(),))
    record = decision.to_record()
    assert "primary_app" not in record and "title" not in record and "url" not in record
    assert _evaluate(policy, gate, 1,
                     cycles={"work_engagement": 1, "screen_exposure": 0}) is None


def test_outcomes_are_neutral_and_driven_by_cycle_reset_or_timeout():
    decision = PolicyDecision("dispatch", "work_engagement:soft:4",
                              "work_engagement", "soft", WALL, ("natural_pause",))
    tracker = BreakOutcomeTracker(window_seconds=300)
    tracker.watch(decision, cycle_id=4, now=10)
    assert tracker.observe({"work_engagement": 4}, 100, WALL) == ()
    outcome = tracker.observe({"work_engagement": 5}, 101, WALL)[0]
    assert outcome.outcome == "qualifying_break_observed"
    assert "accepted" not in str(outcome.to_record())

    tracker.watch(decision, cycle_id=5, now=200)
    outcome = tracker.observe({"work_engagement": 5}, 501, WALL)[0]
    assert outcome.outcome == "no_qualifying_break_observed"


def test_cancelled_cue_ends_outcome_watch():
    decision = PolicyDecision("dispatch", "screen_exposure:hard:2",
                              "screen_exposure", "hard", WALL, ("hard_wait_elapsed",))
    tracker = BreakOutcomeTracker()
    tracker.watch(decision, cycle_id=2, now=0)
    outcome = tracker.cancel(decision.candidate_id, WALL)
    assert outcome.outcome == "cue_cancelled"
    assert tracker.observe({"screen_exposure": 3}, 1, WALL) == ()
