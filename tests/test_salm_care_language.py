from datetime import datetime, timezone

from features.salm.care_action import CareActionResult
from features.salm.care_language import CareLanguage, clean_care_language
from features.salm.checkin import checkin_text
from features.salm.intervention import InterventionGate
from features.salm.policy import PolicyDecision
from features.salm.runtime import SalmRuntime
from llm.client import AssistantTurn, ToolCall


AT = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)


class _LLM:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return self.turns.pop(0)


class _Dispatcher:
    def __init__(self):
        self.items = []

    def submit(self, item):
        self.items.append(item)
        return True


class _Storage:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)


class _Policy:
    def __init__(self):
        self.snoozes = []

    def snooze(self, candidate_id, now, seconds=600):
        self.snoozes.append((candidate_id, now, seconds))
        return True

    def discard_pending(self):
        return ()


def test_initial_language_uses_only_whitelisted_context_and_address():
    text = "Cậu chủ, mình nhìn xa vài nhịp nhé. Em ở đây khi cậu chủ cần."
    llm = _LLM(AssistantTurn(text=text))
    language = CareLanguage(llm, address_form_provider=lambda: "cậu chủ")

    assert language.generate_initial("screen_exposure", "soft") == text
    call = llm.calls[0]
    assert call["tools"] == [] and len(call["messages"]) == 1
    prompt = call["messages"][0].text
    assert "clock: screen_exposure" in prompt
    assert "level: soft" in prompt
    assert "addressing_style: cậu chủ" in prompt
    for forbidden in ("app_name", "window", "url", "timeline", "utterance"):
        assert forbidden not in prompt.lower()


def test_care_language_uses_shared_persona_without_weakening_contract():
    text = "Cậu chủ, cậu chủ! Mình nhìn xa rồi chớp mắt chậm vài nhịp nhé?"
    llm = _LLM(AssistantTurn(text=text))
    language = CareLanguage(
        llm, address_form_provider=lambda: "cậu chủ",
        persona_context_provider=lambda: (
            "Bạn là một tiểu quản gia lí lắc. Văn phong: hoạt bát."))

    assert language.generate_initial("screen_exposure", "soft") == text
    system = llm.calls[0]["system"]
    assert "tiểu quản gia lí lắc" in system
    assert "Không nói rằng người dùng đang mệt" in system


def test_disabled_care_llm_uses_persona_owned_validated_fallback():
    def proactive(key, **values):
        assert key == "care_initial_screen_soft"
        return (f"{values['address_form']}, {values['address_form']}! "
                "Mình nhìn xa rồi chớp mắt chậm vài nhịp nhé?")

    language = CareLanguage(
        None, address_form_provider=lambda: "cậu chủ",
        proactive_text_provider=proactive)
    assert language.generate_initial("screen_exposure", "soft").startswith(
        "cậu chủ, cậu chủ!")


def test_validated_reply_contains_committed_action_but_not_raw_utterance():
    text = "Vâng, em để cậu chủ thêm 10 phút nhé. Sau đó mình tính tiếp."
    llm = _LLM(AssistantTurn(text=text))
    language = CareLanguage(llm, address_form_provider=lambda: "cậu chủ")
    action = CareActionResult(
        True, True, "snooze", "fallback không được dùng", "short_delay", 10)

    assert language.generate_reply(action, "work_engagement", "soft") == text
    prompt = llm.calls[0]["messages"][0].text
    assert "validated_action: snooze(10m)" in prompt
    assert "Tôi sẽ cố làm thêm" not in prompt


def test_language_rejects_health_claim_wrong_address_and_wrong_action_detail():
    fallback = checkin_text("screen_exposure", "soft", "cậu chủ")
    language = CareLanguage(
        _LLM(AssistantTurn(text="Anh mệt rồi, em biết anh cần nghỉ.")),
        address_form_provider=lambda: "cậu chủ")
    assert language.generate_initial("screen_exposure", "soft") == fallback

    action = CareActionResult(
        True, True, "snooze", "Được rồi, thêm 10 phút nhé.", "short_delay", 10)
    wrong = CareLanguage(
        _LLM(AssistantTurn(text="Vâng, em để cậu chủ thêm 20 phút nhé.")),
        address_form_provider=lambda: "cậu chủ")
    assert wrong.generate_reply(action) == action.reply

    assert clean_care_language(
        "Em biết cậu chủ đang quá mệt rồi.", purpose="initial_checkin",
        address_form="cậu chủ") is None
    assert clean_care_language(
        "Em sẽ đợi tới khi cậu chủ làm xong.", purpose="validated_reply",
        address_form="cậu chủ", action="cycle_dnd") is None
    assert clean_care_language(
        "Dạ, em đã thêm 10 phút nghỉ cho cậu chủ.",
        purpose="validated_reply", address_form="cậu chủ",
        action="snooze", minutes=10) is None
    assert clean_care_language(
        "Em mời cậu chủ tạm dừng một chút nhé.",
        purpose="validated_reply", address_form="cậu chủ",
        action="accept")


def test_initial_repetition_guard_rejects_same_generated_structure_twice():
    text = "Cậu chủ, mình nhìn xa vài nhịp nhé. Em ở đây khi cậu chủ cần."
    llm = _LLM(AssistantTurn(text=text), AssistantTurn(text=text))
    language = CareLanguage(llm, address_form_provider=lambda: "cậu chủ")

    assert language.generate_initial("screen_exposure", "soft") == text
    assert language.generate_initial("screen_exposure", "soft") == checkin_text(
        "screen_exposure", "soft", "cậu chủ")
    # Balanced giữ cấu trúc hai lượt; guard nội dung vẫn chặn câu lặp y hệt.
    first = llm.calls[0]["messages"][0].text
    second = llm.calls[1]["messages"][0].text
    assert first.split("variation_structure: ", 1)[1] == second.split(
        "variation_structure: ", 1)[1]


def test_style_preferences_are_bounded_and_only_structured_values_reach_prompt():
    text = "Cậu chủ, mình nhìn xa vài nhịp nhé. Em vẫn ở đây."
    llm = _LLM(AssistantTurn(text=text))
    style = {"length": "concise", "directness": "gentle",
             "variation": "high", "address_frequency": "frequent",
             "raw_utterance": "không được lộ"}
    language = CareLanguage(
        llm, address_form_provider=lambda: "cậu chủ",
        style_provider=lambda: style)

    assert language.generate_initial("screen_exposure", "soft") == text
    prompt = llm.calls[0]["messages"][0].text
    assert "length_preference: concise" in prompt
    assert "directness_preference: gentle" in prompt
    assert "address_frequency: frequent" in prompt
    assert "không được lộ" not in prompt


def test_language_enforces_length_and_address_frequency():
    long_text = "Cậu chủ, mình nhìn xa một chút rồi chớp mắt thật chậm, thả lỏng " \
                "từng ngón tay và hít thở đều để tạo một khoảng nghỉ thật êm nhé."
    assert clean_care_language(
        long_text, purpose="initial_checkin", address_form="cậu chủ",
        clock="screen_exposure", level="soft", max_words=22) is None
    assert clean_care_language(
        "Mình nhìn xa vài nhịp nhé, em vẫn ở đây.",
        purpose="initial_checkin", address_form="cậu chủ",
        clock="screen_exposure", level="soft",
        address_frequency="frequent") is None
    assert clean_care_language(
        "Cậu chủ, mình nhìn xa vài nhịp nhé, em vẫn ở đây.",
        purpose="initial_checkin", address_form="cậu chủ",
        clock="screen_exposure", level="soft",
        address_frequency="sparse") is None


def test_uncommitted_action_never_calls_reply_language_model():
    llm = _LLM(AssistantTurn(text="không được gọi"))
    language = CareLanguage(llm)
    result = CareActionResult(True, False, "none", "Xin nói rõ hơn.")
    assert language.generate_reply(result) == result.reply
    assert llm.calls == []


def test_runtime_defers_initial_generation_until_dispatch_and_rechecks_gate(tmp_path):
    text = "Mình thả lỏng tay một chút nhé. Em đợi ở đây."
    llm = _LLM(AssistantTurn(text=text))
    dispatcher, shown = _Dispatcher(), []
    gate = InterventionGate()
    runtime = SalmRuntime(
        tmp_path, storage=_Storage(), policy=_Policy(), dispatcher=dispatcher,
        gate=gate, gentle_checkin=True,
        on_checkin=lambda action, decision, value: shown.append(value),
        care_llm=llm, care_llm_language=True)
    decision = PolicyDecision(
        "dispatch", "work_engagement:soft:2", "work_engagement", "soft", AT,
        ("natural_pause",))

    runtime._handle_policy_decision(
        decision, now=1, cycles={"work_engagement": 2})
    assert llm.calls == []
    # Gate mặc định UNKNOWN: sau model phải drop, tuyệt đối không phát TTS.
    dispatcher.items[0].present()
    assert len(llm.calls) == 1 and shown == []


def test_disabled_language_lane_keeps_dynamic_profile_fallback(tmp_path):
    dispatcher, shown = _Dispatcher(), []
    runtime = SalmRuntime(
        tmp_path, storage=_Storage(), policy=_Policy(), dispatcher=dispatcher,
        gentle_checkin=True,
        on_checkin=lambda action, decision, value: shown.append(value),
        address_form_provider=lambda: "cậu chủ")
    decision = PolicyDecision(
        "dispatch", "screen_exposure:soft:2", "screen_exposure", "soft", AT,
        ("natural_pause",))

    runtime._handle_policy_decision(
        decision, now=1,
        cycles={"screen_exposure": 2, "work_engagement": 1})
    dispatcher.items[0].present()
    assert shown == [checkin_text("screen_exposure", "soft", "cậu chủ")]


def test_runtime_generates_reply_only_after_policy_commits_action(tmp_path):
    intent = {
        "intent": "snooze",
        "requested_minutes": None,
        "until_local_time": None,
        "release_condition": None,
        "confidence": 0.95,
        "reason_code": "short_delay",
    }
    generated = "Vâng, em để cậu chủ thêm 10 phút nhé. Sau đó mình tính tiếp."
    llm = _LLM(
        AssistantTurn(tool_calls=[
            ToolCall("care-1", "submit_care_intent", intent)]),
        AssistantTurn(text=generated),
    )
    storage, policy = _Storage(), _Policy()
    runtime = SalmRuntime(
        tmp_path, storage=storage, policy=policy, gentle_checkin=True,
        care_llm=llm, care_llm_intent=True, care_llm_language=True,
        address_form_provider=lambda: "cậu chủ")
    decision = PolicyDecision(
        "dispatch", "work_engagement:soft:4", "work_engagement", "soft", AT,
        ("natural_pause",))
    runtime.checkins.arm(decision, cycle_id=4, now=100)
    utterance = "Tôi sẽ cố làm thêm tí nữa"

    assert runtime.try_care_response(utterance, now=101, at=AT) == generated
    assert policy.snoozes == [(decision.candidate_id, 101, 600.0)]
    assert len(llm.calls) == 2
    assert llm.calls[0]["messages"][0].text == utterance
    assert utterance not in llm.calls[1]["messages"][0].text
    assert "validated_action: snooze(10m)" in llm.calls[1]["messages"][0].text
    assert llm.calls[1]["tools"] == []


def test_policy_fallback_reply_uses_current_profile_address(tmp_path):
    from features.salm.care_action import CareActionPolicy
    from features.salm.care_dnd import UserCareDnd
    from features.salm.checkin import CheckInSession
    from features.salm.dialogue import CareIntent

    policy = _Policy()
    action = CareActionPolicy(
        policy, UserCareDnd(tmp_path / "dnd.json", enabled=True),
        InterventionGate(), user_dnd_enabled=True,
        address_form_provider=lambda: "cậu chủ")
    session = CheckInSession(
        "work_engagement:soft:4", "work_engagement", "soft", 4, 120)
    result = action.apply(
        CareIntent("snooze", 20, None, None, 0.95, "explicit_duration"),
        session, 101, AT)

    assert result.committed and "cậu chủ" in result.reply
    assert "anh" not in result.reply.lower()
