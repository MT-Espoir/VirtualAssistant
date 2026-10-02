"""Phục hồi lỗi STT có giới hạn: nhận ra không chắc, không tự bịa lại câu lệnh."""

from dataclasses import dataclass
from difflib import SequenceMatcher

from utils.text_norm import norm


class VoiceUtterance(str):
    """Chuỗi tương thích ngược, kèm metadata không nhạy cảm của STT/VAD."""

    def __new__(cls, text, *, confidence=None, alternatives=(), capture=None,
                engine=None):
        value = str.__new__(cls, text or "")
        value.confidence = confidence
        value.alternatives = tuple(alternatives or ())
        value.capture = dict(capture or {})
        value.engine = engine
        return value


@dataclass(frozen=True)
class VoiceAssessment:
    retry: bool
    reason_codes: tuple = ()
    prompt: str = ""


_DANGLING_LAST_WORDS = {
    "sau", "luc", "vao", "cho", "voi", "cua", "ma", "so", "mo",
}


def _similarity(first, second):
    return SequenceMatcher(None, norm(first or ""), norm(second or "")).ratio()


def assess_voice_utterance(value, *, allow_short_confirmation=False):
    """Fail closed khi có bằng chứng transcript bị cắt hoặc rất không chắc."""
    if not isinstance(value, VoiceUtterance):
        return VoiceAssessment(False)
    reasons = []
    if value.capture.get("hit_max_utterance"):
        reasons.append("audio_cut_at_max_duration")

    words = norm(str(value)).split()
    if words and words[-1] in _DANGLING_LAST_WORDS:
        reasons.append("dangling_final_word")
    if len(words) >= 3 and len(set(words[-3:])) == 1:
        reasons.append("repeated_tail_token")

    confidence = value.confidence
    if confidence is not None and float(confidence) < 0.45:
        reasons.append("low_stt_confidence")
    alternatives = tuple(a for a in value.alternatives if a)
    if (confidence is not None and float(confidence) < 0.65
            and len(alternatives) > 1
            and _similarity(alternatives[0], alternatives[1]) < 0.5):
        reasons.append("alternatives_disagree")

    if allow_short_confirmation and len(words) <= 2:
        reasons = [reason for reason in reasons
                   if reason == "audio_cut_at_max_duration"]
    if not reasons:
        return VoiceAssessment(False)
    return VoiceAssessment(
        True, tuple(dict.fromkeys(reasons)),
        "Em nghe câu vừa rồi chưa trọn hoặc chưa đủ chắc. Bạn nói lại giúp em nhé.")
