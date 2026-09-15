from datetime import datetime, timedelta, timezone

from features.salm.care_action import (CLARIFY_REPLY, CareActionPolicy,
                                       DEFAULT_SNOOZE_MINUTES)
from features.salm.care_dnd import UserCareDnd
from features.salm.checkin import CheckInSession
from features.salm.dialogue import (CARE_INTENT_TOOL, CareDialogue, CareIntent,
                                    parse_care_intent)
from features.salm.intervention import InterventionGate
from features.salm.policy import PolicyDecision
from features.salm.runtime import SalmRuntime
from llm.client import AssistantTurn, ToolCall


AT = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)


def _args(**changes):
    value = {
        "intent": "snooze",
        "requested_minutes": None,
        "until_local_time": None,
        "release_condition": None,
        "confidence": 0.95,
        "reason_code": "short_delay",
    }
    value.update(changes)
    return value


class _LLM:
    def __init__(self, turn=None, error=None):
        self.turn = turn
        self.error = error
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.turn


class _Policy:
    def __init__(self, accepts=True):
        self.accepts = accepts
        self.snoozes = []
        self.discards = 0

    def snooze(self, candidate_id, now, seconds=600):
        self.snoozes.append((candidate_id, now, seconds))
        return self.accepts

    def discard_pending(self):
        self.discards += 1
        return ()


class _Storage:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)


def _session():
    return CheckInSession("work_engagement:soft:4", "work_engagement", "soft", 4, 20)


def _intent(intent="snooze", minutes=None, release=None, confidence=0.95,
            reason="short_delay", local_time=None):
    return CareIntent(intent, minutes, local_time, release, confidence, reason)


def test_dialogue_uses_one_isolated_schema_without_agent_history_or_catalog():
    llm = _LLM(AssistantTurn(tool_calls=[
        ToolCall("care-1", "submit_care_intent", _args())
    ]))
    result = CareDialogue(llm).classify("Tôi sẽ cố làm thêm tí nữa", "work_engagement", "soft")

    assert result.intent == "snooze"
    call = llm.calls[0]
    assert len(call["messages"]) == 1
    assert call["messages"][0].text == "Tôi sẽ cố làm thêm tí nữa"
    assert call["tools"] == [CARE_INTENT_TOOL]
    assert "Chrome" not in call["system"] and "timeline" not in call["messages"][0].text


def test_dialogue_fails_closed_on_wrong_multiple_or_invalid_tool_calls():
    invalid = _args(extra="not allowed")
    for turn in (
        AssistantTurn(text="snooze"),
        AssistantTurn(tool_calls=[ToolCall("1", "other", _args())]),
        AssistantTurn(tool_calls=[ToolCall("1", "submit_care_intent", _args()),
                                  ToolCall("2", "submit_care_intent", _args())]),
        AssistantTurn(tool_calls=[ToolCall("1", "submit_care_intent", invalid)]),
    ):
        assert CareDialogue(_LLM(turn)).classify("hoãn") is None


def test_strict_parser_rejects_bad_types_enums_and_confidence():
    assert parse_care_intent(_args(confidence=1.1)) is None
    assert parse_care_intent(_args(requested_minutes=2.5)) is None
    assert parse_care_intent(_args(intent="disable_everything")) is None
    assert parse_care_intent(_args(reason_code="free form rationale")) is None


def test_policy_maps_natural_short_delay_to_default_snooze(tmp_path):
    policy, gate = _Policy(), InterventionGate()
    dnd = UserCareDnd(tmp_path / "dnd.json", enabled=True)
    action = CareActionPolicy(policy, dnd, gate, user_dnd_enabled=True)

    result = action.apply(_intent(), _session(), now=10, at=AT)

    assert result.committed and result.action == "snooze"
    assert result.minutes == DEFAULT_SNOOZE_MINUTES
    assert policy.snoozes == [(_session().candidate_id, 10, 600.0)]
    assert "user_care_dnd" not in gate.reasons("break_care", now=10)


def test_low_or_medium_confidence_never_mutates_state(tmp_path):
    policy, gate = _Policy(), InterventionGate()
    action = CareActionPolicy(
        policy, UserCareDnd(tmp_path / "dnd.json", enabled=True), gate, True)

    low = action.apply(_intent(confidence=0.4), _session(), 1, AT)
    medium = action.apply(_intent(confidence=0.7), _session(), 1, AT)

    assert not low.handled and not policy.snoozes
    assert medium.handled and not medium.committed and medium.reply == CLARIFY_REPLY
    assert not policy.snoozes


def test_timed_dnd_is_break_only_and_persists_without_raw_utterance(tmp_path):
    path = tmp_path / "care-dnd.json"
    policy, gate = _Policy(), InterventionGate()
    dnd = UserCareDnd(path, enabled=True)
    action = CareActionPolicy(policy, dnd, gate, user_dnd_enabled=True)
    intent = _intent("care_dnd", minutes=120, release="deadline",
                     reason="explicit_duration")

    result = action.apply(intent, _session(), now=5, at=AT)

    assert result.action == "timed_dnd" and result.committed
    assert gate.reasons("global", now=5) == ()
    assert "user_care_dnd" in gate.reasons("break_care", now=5)
    raw = path.read_text(encoding="utf-8")
    assert "120" not in raw and "utterance" not in raw
    restored = UserCareDnd(path, enabled=True)
    assert restored.state.mode == "timed_dnd"
    assert restored.refresh(AT + timedelta(minutes=119)).active
    assert restored.refresh(AT + timedelta(minutes=120)).released


def test_cycle_dnd_releases_on_cycle_reset_and_is_not_persisted(tmp_path):
    path = tmp_path / "care-dnd.json"
    policy, gate = _Policy(), InterventionGate()
    dnd = UserCareDnd(path, enabled=True)
    action = CareActionPolicy(policy, dnd, gate, user_dnd_enabled=True)

    result = action.apply(
        _intent("care_dnd", release="work_cycle_reset", reason="finish_current_work"),
        _session(), 5, AT)

    assert result.action == "cycle_dnd" and not path.exists()
    assert dnd.refresh(AT, cycle_id=4).active
    released = dnd.refresh(AT, cycle_id=5)
    assert released.released and released.reason == "work_cycle_reset"


def test_cycle_dnd_uses_work_cycle_even_when_checkin_came_from_screen(tmp_path):
    policy, gate = _Policy(), InterventionGate()
    dnd = UserCareDnd(tmp_path / "care-dnd.json", enabled=True)
    action = CareActionPolicy(policy, dnd, gate, user_dnd_enabled=True)
    screen_session = CheckInSession(
        "screen_exposure:soft:9", "screen_exposure", "soft", 9, 20,
        work_cycle_id=4)

    action.apply(
        _intent("care_dnd", release="work_cycle_reset", reason="finish_current_work"),
        screen_session, 5, AT)

    assert dnd.state.cycle_id == 4
    assert dnd.refresh(AT, cycle_id=4).active


def test_resume_is_deterministic_and_clears_pending_without_immediate_cue(tmp_path):
    policy, gate = _Policy(), InterventionGate()
    dnd = UserCareDnd(tmp_path / "dnd.json", enabled=True)
    dnd.set_session(AT)
    gate.set_user_care_dnd(True)
    action = CareActionPolicy(policy, dnd, gate, user_dnd_enabled=True)

    result = action.apply(
        _intent("resume_care", release="explicit_resume", reason="explicit_resume"),
        None, 5, AT)

    assert result.action == "resume_care" and result.committed
    assert dnd.state is None and policy.discards == 1
    assert "user_care_dnd" not in gate.reasons("break_care", now=5)


def test_over_24_hours_and_semantically_dirty_accept_are_rejected(tmp_path):
    policy, gate = _Policy(), InterventionGate()
    action = CareActionPolicy(
        policy, UserCareDnd(tmp_path / "dnd.json", enabled=True), gate, True)
    too_long = action.apply(_intent(minutes=1441), _session(), 1, AT)
    dirty_accept = action.apply(
        _intent("accept", minutes=10, reason="explicit_accept"), _session(), 1, AT)
    assert not too_long.committed and not dirty_accept.committed
    assert not policy.snoozes


def test_runtime_understands_natural_response_without_agent_and_logs_no_raw(tmp_path):
    utterance = "Tôi sẽ cố làm thêm tí nữa"
    llm = _LLM(AssistantTurn(tool_calls=[
        ToolCall("care-1", "submit_care_intent", _args())
    ]))
    storage, policy = _Storage(), _Policy()
    runtime = SalmRuntime(
        tmp_path, storage=storage, policy=policy, gentle_checkin=True,
        care_llm=llm, care_llm_intent=True, user_dnd=True)
    decision = PolicyDecision(
        "dispatch", _session().candidate_id, "work_engagement", "soft", AT,
        ("natural_pause",))
    runtime.checkins.arm(decision, cycle_id=4, now=100)

    reply = runtime.try_care_response(utterance, now=101, at=AT)

    assert reply and policy.snoozes == [(_session().candidate_id, 101, 600.0)]
    assert llm.calls[0]["tools"] == [CARE_INTENT_TOOL]
    assert all(utterance not in str(record) for record in storage.records)


def test_runtime_llm_failure_keeps_narrow_snooze_fallback(tmp_path):
    storage, policy = _Storage(), _Policy()
    runtime = SalmRuntime(
        tmp_path, storage=storage, policy=policy, gentle_checkin=True,
        care_llm=_LLM(error=TimeoutError()), care_llm_intent=True, user_dnd=True)
    decision = PolicyDecision(
        "dispatch", _session().candidate_id, "work_engagement", "soft", AT,
        ("natural_pause",))
    runtime.checkins.arm(decision, cycle_id=4, now=100)

    assert runtime.try_care_response("hoãn", now=101, at=AT)
    assert policy.snoozes == [(_session().candidate_id, 101, 600.0)]


def test_runtime_deterministic_resume_works_outside_response_window(tmp_path):
    storage, policy = _Storage(), _Policy()
    dnd = UserCareDnd(tmp_path / "dnd.json", enabled=True)
    dnd.set_session(AT)
    gate = InterventionGate()
    gate.set_user_care_dnd(True)
    runtime = SalmRuntime(
        tmp_path, storage=storage, policy=policy, gate=gate,
        gentle_checkin=True, user_dnd=True, care_dnd=dnd)

    reply = runtime.try_care_response("nhắc nghỉ lại đi", now=101, at=AT)

    assert reply and dnd.state is None and policy.discards == 1
    assert "user_care_dnd" not in gate.reasons("break_care", now=101)


def test_runtime_allows_only_one_clarification_turn(tmp_path):
    unclear = _args(intent="unclear", confidence=0.7,
                    reason_code="ambiguous_request")
    llm = _LLM(AssistantTurn(tool_calls=[
        ToolCall("care-1", "submit_care_intent", unclear)
    ]))
    storage, policy = _Storage(), _Policy()
    runtime = SalmRuntime(
        tmp_path, storage=storage, policy=policy, gentle_checkin=True,
        care_llm=llm, care_llm_intent=True, user_dnd=True)
    decision = PolicyDecision(
        "dispatch", _session().candidate_id, "work_engagement", "soft", AT,
        ("natural_pause",))
    runtime.checkins.arm(decision, cycle_id=4, now=100)

    assert runtime.try_care_response("đừng nhắc", now=101, at=AT) == CLARIFY_REPLY
    assert runtime.checkins.active(102).clarifications == 1
    assert runtime.try_care_response("tôi chưa rõ", now=102, at=AT) is None
    assert runtime.checkins.active(102) is None
