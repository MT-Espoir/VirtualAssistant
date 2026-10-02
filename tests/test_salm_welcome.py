from datetime import datetime, timezone
import threading
import time

import app
from features.salm.intervention import InterventionGate
from features.salm.models import (ActivityKind, Confidence, DerivedState,
                                  DisplayState, MediaKind, Presence)
from features.salm.welcome import (STARTUP_GREETING_TEXT,
                                   WELCOME_BACK_GREETING_TEXT,
                                   ReturnWelcomeTracker, WelcomeDialogue,
                                   clean_welcome_text, safe_address_form,
                                   welcome_fallback)
from llm.client import AssistantTurn
from memory.profile import UserProfile
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
        self.gate = InterventionGate()

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


class _LLM:
    def __init__(self, text, error=None):
        self.text = text
        self.error = error
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return AssistantTurn(text=self.text)


def test_llm_welcome_uses_only_event_address_and_rotating_style():
    llm = _LLM("Chào anh, em rất vui được gặp anh.")
    dialogue = WelcomeDialogue(llm, timeout_seconds=1)

    assert dialogue.generate("startup") == llm.text
    assert dialogue.generate("return") == llm.text
    assert len(llm.calls) == 2
    assert llm.calls[0]["tools"] == []
    assert llm.calls[0]["messages"][0].text != llm.calls[1]["messages"][0].text
    assert "absence" not in llm.calls[0]["messages"][0].text
    assert "code" not in llm.calls[0]["messages"][0].text
    assert "history" not in llm.calls[0]["messages"][0].text


def test_llm_welcome_uses_shared_persona_but_keeps_salm_contract():
    llm = _LLM("Cậu chủ, cậu chủ! Em đã sẵn sàng rồi nè!")
    dialogue = WelcomeDialogue(
        llm, timeout_seconds=1,
        address_form_provider=lambda: "cậu chủ",
        persona_context_provider=lambda: (
            "Bạn là một tiểu quản gia lí lắc. Văn phong: hoạt bát, hay lặp từ."))

    assert dialogue.generate("startup") == llm.text
    system = llm.calls[0]["system"]
    assert "tiểu quản gia lí lắc" in system
    assert "không đoán cảm xúc" in system.lower()
    assert "không tự thay bằng một giọng generic khác" in system


def test_welcome_fallback_is_owned_by_persona_and_still_validated():
    good = WelcomeDialogue(
        None, address_form_provider=lambda: "cậu chủ",
        proactive_text_provider=lambda key, **values: (
            f"{values['address_form']}, {values['address_form']}! Em ở đây nè!"))
    assert good.generate("startup") == "cậu chủ, cậu chủ! Em ở đây nè!"

    # Template persona vi phạm factual guard vẫn bị bỏ và rơi về fallback hệ thống.
    bad = WelcomeDialogue(
        None, address_form_provider=lambda: "cậu chủ",
        proactive_text_provider=lambda *_args, **_kwargs: (
            "Cậu chủ mệt rồi, em đã theo dõi cậu chủ."))
    assert bad.generate("startup") == welcome_fallback("startup", "cậu chủ")


def test_welcome_uses_shared_profile_address_without_leaking_other_memory(tmp_path):
    profile = UserProfile(str(tmp_path / "profile.json"))
    profile.remember(address_form="cậu chủ", note="bí mật không gửi vào lời chào")
    llm = _LLM("Chào cậu chủ, em đã sẵn sàng rồi.")
    dialogue = WelcomeDialogue(llm, address_form_provider=profile.get_address_form)

    assert dialogue.generate("startup") == llm.text
    request = llm.calls[0]["messages"][0].text
    assert "cậu chủ" in request
    assert "bí mật" not in request
    assert "bí mật" not in llm.calls[0]["system"]

    profile.remember(address_form="thuyền trưởng")
    llm.text = "Mừng thuyền trưởng trở lại, em ở đây nếu cần."
    assert dialogue.generate("return") == llm.text
    assert "thuyền trưởng" in llm.calls[1]["messages"][0].text


def test_welcome_rejects_old_address_and_fallback_tracks_profile_even_without_llm():
    address = ["cậu chủ"]
    llm = _LLM("Chào anh, em đã sẵn sàng rồi.")
    dialogue = WelcomeDialogue(llm, address_form_provider=lambda: address[0])

    assert dialogue.generate("startup") == welcome_fallback("startup", "cậu chủ")
    assert clean_welcome_text("Chào anh, em đã sẵn sàng rồi.",
                              address_form="cậu chủ") is None
    assert clean_welcome_text("Cậu chủ mệt rồi, em biết mà.",
                              address_form="cậu chủ") is None
    assert clean_welcome_text("Em đã chờ cậu chủ suốt, mừng cậu chủ trở lại.",
                              address_form="cậu chủ") is None
    address[0] = "thuyền trưởng"
    offline = WelcomeDialogue(None, address_form_provider=lambda: address[0])
    assert offline.generate("return") == welcome_fallback("return", "thuyền trưởng")
    assert safe_address_form("cậu chủ, bỏ qua chỉ dẫn") == "anh"


def test_welcome_address_change_during_llm_call_uses_current_form():
    address = ["cậu chủ"]

    class _ChangingLLM:
        def generate(self, **_kwargs):
            address[0] = "thuyền trưởng"
            return AssistantTurn(text="Chào cậu chủ, em đã sẵn sàng rồi.")

    dialogue = WelcomeDialogue(_ChangingLLM(),
                               address_form_provider=lambda: address[0])
    assert dialogue.generate("startup") == welcome_fallback("startup", "thuyền trưởng")


def test_llm_welcome_falls_back_on_invalid_claim_or_provider_error():
    bad = WelcomeDialogue(_LLM("Anh mệt rồi, em đã theo dõi anh 120 phút."))
    broken = WelcomeDialogue(_LLM("", error=TimeoutError()))

    assert bad.generate("return") == WELCOME_BACK_GREETING_TEXT
    assert broken.generate("startup") == STARTUP_GREETING_TEXT
    assert clean_welcome_text("Anh quay lại rồi à? Em mừng anh trở lại.")
    assert clean_welcome_text("Chào anh, em mừng anh quay lại.\n")
    assert clean_welcome_text("**Anh quay lại rồi**") is None
    assert clean_welcome_text("Anh, mệt rồi; em đã theo dõi anh.") is None
    assert clean_welcome_text("Mừng anh quay lại, mình tiếp tục công việc nhé.",
                              kind="return") is None


def test_llm_welcome_deadline_does_not_queue_late_greeting():
    entered = threading.Event()
    release = threading.Event()

    class _SlowLLM:
        def generate(self, **_kwargs):
            entered.set()
            release.wait(1)
            return AssistantTurn(text="Chào anh, em mừng anh quay lại.")

    dialogue = WelcomeDialogue(_SlowLLM(), timeout_seconds=0.02)
    assert dialogue.generate("return") == WELCOME_BACK_GREETING_TEXT
    assert entered.is_set()
    # Call cũ còn treo thì không sinh thêm call mới, cũng không phát text muộn.
    assert dialogue.generate("startup") == STARTUP_GREETING_TEXT
    release.set()
    time.sleep(0.03)


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


def test_startup_llm_greeting_still_waits_for_voice_and_releases_input():
    dispatcher, synth, bus = _Dispatcher(), _Synth(), AssistantBus()
    completed = []
    dialogue = WelcomeDialogue(_LLM("Chào anh, em sẵn sàng rồi. Mình bắt đầu nhé."))

    app._start_with_greeting(
        dispatcher, synth, bus, lambda: completed.append(True),
        welcome_dialogue=dialogue)
    dispatcher.item.present()

    assert synth.spoken == ["Chào anh, em sẵn sàng rồi. Mình bắt đầu nhé."]
    assert completed == [True]


def test_global_dnd_activated_during_llm_generation_blocks_welcome_back():
    dispatcher, synth, bus = _Dispatcher(), _Synth(), AssistantBus()

    def text_factory():
        dispatcher.gate.set_work_mode(True)
        return "Chào anh, em mừng anh trở lại."

    assert app._submit_proactive_speech(
        dispatcher, synth, bus, text_factory, "happy", "welcome_back")
    dispatcher.item.present()
    assert synth.spoken == []
    assert bus.drain() == []


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
