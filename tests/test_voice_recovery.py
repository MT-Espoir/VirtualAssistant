from unittest.mock import MagicMock

from voice.recovery import VoiceUtterance, assess_voice_utterance
from voice.speech_recognizer import SpeechRecognizer, _google_candidates
from utils.events import AssistantBus


def test_google_candidates_keep_alternatives_and_confidence():
    candidates = _google_candidates({"alternative": [
        {"transcript": "bật nhắc khuya", "confidence": 0.82},
        {"transcript": "bật nhạc khuya"},
    ]})
    assert candidates == [
        ("bật nhắc khuya", 0.82), ("bật nhạc khuya", None)]


def test_google_recognizer_requests_nbest_and_exposes_metadata():
    recognizer = SpeechRecognizer.__new__(SpeechRecognizer)
    recognizer.recognizer = MagicMock()
    recognizer.recognizer.recognize_google.return_value = {
        "alternative": [
            {"transcript": "bật nhắc khuya", "confidence": 0.78},
            {"transcript": "bật nhạc khuya"},
        ]}
    recognizer.language = "vi-VN"
    recognizer.engine = "google"
    recognizer.sample_rate = 16000
    recognizer.last_result = None

    assert recognizer.recognize_speech_from_data(b"\x00\x00" * 100) == "bật nhắc khuya"
    assert recognizer.last_result.confidence == 0.78
    assert recognizer.last_result.alternatives == (
        "bật nhắc khuya", "bật nhạc khuya")
    recognizer.recognizer.recognize_google.assert_called_once()
    assert recognizer.recognizer.recognize_google.call_args.kwargs["show_all"] is True


def test_capture_cut_at_max_duration_always_requests_repeat():
    utterance = VoiceUtterance(
        "Alice mở Chrome", capture={"hit_max_utterance": True})
    assessment = assess_voice_utterance(utterance)
    assert assessment.retry is True
    assert "audio_cut_at_max_duration" in assessment.reason_codes


def test_dangling_or_hallucinated_tail_requests_repeat():
    assert assess_voice_utterance(VoiceUtterance("Alice mở")).retry is True
    repeated = assess_voice_utterance(
        VoiceUtterance("xem cài đặt nhắc here here here"))
    assert repeated.retry is True
    assert "repeated_tail_token" in repeated.reason_codes


def test_low_confidence_disagreeing_alternatives_request_repeat():
    utterance = VoiceUtterance(
        "Alice bật nhắc khuya", confidence=0.4,
        alternatives=("Alice bật nhắc khuya", "Alice mở YouTube"))
    assessment = assess_voice_utterance(utterance)
    assert assessment.retry is True
    assert "low_stt_confidence" in assessment.reason_codes
    assert "alternatives_disagree" in assessment.reason_codes


def test_short_confirmation_is_allowed_despite_low_confidence():
    utterance = VoiceUtterance("có", confidence=0.2, alternatives=("có", "không"))
    assert assess_voice_utterance(
        utterance, allow_short_confirmation=True).retry is False


def test_plain_keyboard_string_is_never_subject_to_stt_recovery():
    assert assess_voice_utterance("Alice mở").retry is False


def _run_voice_loop(monkeypatch, utterance):
    import app

    inputs = [utterance, None]
    monkeypatch.setattr(app, "_next_input", lambda _voice_io, _bus: inputs.pop(0))
    monkeypatch.setattr(app.config, "REQUIRE_WAKE_WORD", True)
    monkeypatch.setattr(app.config, "WAKE_WORDS", "alice")
    monkeypatch.setattr(app.config, "FOLLOW_UP_SECONDS", 0.0)
    monkeypatch.setattr(app.config, "BARGE_IN", False)

    recorder = MagicMock()
    recorder.speech_started_at = None
    agent = MagicMock()
    agent.pending = None
    agent.persona = None
    bus = AssistantBus()
    app._assistant_loop(agent, bus, None, (recorder, MagicMock()))
    return agent, recorder, bus


def test_cut_audio_without_wake_word_is_silent(monkeypatch):
    """Noise hitting the duration cap must not make recovery bypass the wake gate."""
    agent, recorder, bus = _run_voice_loop(
        monkeypatch,
        VoiceUtterance("Xem đài", capture={"hit_max_utterance": True}),
    )

    debug = bus.drain_debug()
    assert any(event['data'].get('event_code') == 'wake_word_missing'
               for event in debug)
    assert not any(event["category"] == "assistant" for event in debug)
    assert not any(event['data'].get('event_code') == 'repeat_required'
                   for event in debug)
    agent.run.assert_not_called()
    recorder.discard_buffered.assert_not_called()


def test_cut_audio_with_wake_word_still_requests_repeat(monkeypatch):
    """Recovery remains active after an intentional voice turn is established."""
    agent, recorder, bus = _run_voice_loop(
        monkeypatch,
        VoiceUtterance("Alice mở Chrome", capture={"hit_max_utterance": True}),
    )

    debug = bus.drain_debug()
    assert any(event['data'].get('event_code') == 'repeat_required'
               for event in debug)
    assert any(event["category"] == "assistant"
               and event['data'].get('event_code') == 'tts_input'
               for event in debug)
    agent.run.assert_not_called()
    recorder.discard_buffered.assert_called_once()
