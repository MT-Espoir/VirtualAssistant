"""Lane LLM cô lập để hiểu phản hồi cho SALM Break Care.

Model chỉ đề xuất một intent theo schema đóng. Module này không biết Agent, history hay
catalog tool và tuyệt đối không thay đổi policy/state.
"""

from dataclasses import dataclass
from typing import Optional

from features.salm.checkin import match_snooze
from llm.client import Message
from utils.logger import get_logger
from utils.text_norm import norm

logger = get_logger(__name__)

CARE_INTENTS = frozenset({
    "accept", "snooze", "decline_once", "care_dnd", "resume_care",
    "unclear", "unrelated",
})
RELEASE_CONDITIONS = frozenset({
    "deadline", "work_cycle_reset", "app_session", "explicit_resume",
})
REASON_CODES = frozenset({
    "explicit_accept", "explicit_decline", "short_delay", "explicit_duration",
    "finish_current_work", "suppress_session", "explicit_resume",
    "ambiguous_request", "conflicting_request", "unrelated_request",
})
_EXPECTED_KEYS = frozenset({
    "intent", "requested_minutes", "until_local_time", "release_condition",
    "confidence", "reason_code",
})
_TOOL_NAME = "submit_care_intent"

CARE_INTENT_TOOL = {
    "name": _TOOL_NAME,
    "description": (
        "Submit exactly one structured interpretation of the user's response to a "
        "Break Care check-in. This tool proposes intent only and performs no action."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": sorted(CARE_INTENTS)},
            "requested_minutes": {
                "type": "integer", "nullable": True,
                "description": (
                    "Whole minutes explicitly requested, otherwise null. Never infer a "
                    "duration from words such as a little or until finished."),
            },
            "until_local_time": {
                "type": "string", "nullable": True,
                "description": (
                    "Explicit local clock time in HH:MM, otherwise null. Use only for "
                    "care_dnd with release_condition deadline."),
            },
            "release_condition": {
                "type": "string", "nullable": True,
                "enum": sorted(RELEASE_CONDITIONS),
                "description": (
                    "For snooze, accept, decline_once, unclear and unrelated this MUST "
                    "be null. Use deadline/work_cycle_reset/app_session only for "
                    "care_dnd; explicit_resume only for resume_care."),
            },
            "confidence": {"type": "number"},
            "reason_code": {"type": "string", "enum": sorted(REASON_CODES)},
        },
        "required": sorted(_EXPECTED_KEYS),
        "additionalProperties": False,
    },
}

_SYSTEM = """You classify one Vietnamese user response to a gentle break check-in.
Call submit_care_intent exactly once and output no prose.

Rules:
- Output fields must obey the exact intent contract below. Never attach a release condition
  merely because the wording mentions a session, deadline, or current work.
- snooze: requested_minutes is the explicit whole number or null; until_local_time=null;
  release_condition=null. "làm thêm tí nữa", "chốt nốt", "cho tôi thêm 20 phút" are snooze.
- accept: all three optional action fields null; reason_code=explicit_accept.
- decline_once: all three optional action fields null; reason_code=explicit_decline.
- "đừng nhắc trong X" means care_dnd/deadline even when X is 120 minutes or less.
- care_dnd/deadline: release_condition=deadline and exactly one of requested_minutes or
  until_local_time is set. "tắt nhắc nghỉ 30 phút" is care_dnd, never snooze.
- care_dnd/work_cycle_reset: both time fields null. "để tôi làm xong việc này" and
  "đừng chen vào phiên làm việc này nữa" use this mapping. Do not claim task detection.
- care_dnd/app_session: both time fields null. Use only for broad but break-specific wording
  such as "tạm thời đừng nhắc nghỉ nữa".
- resume_care: both time fields null and release_condition=explicit_resume.
- unclear: all optional fields null. A broad "đừng làm phiền" without break-care wording,
  permanent request, contradiction, double negative, over-24-hour or multi-action is unclear.
- unrelated: all optional fields null. Unrelated assistant commands are unrelated.
- requested_minutes is a whole number only when explicitly stated. until_local_time is
  HH:MM only when explicitly stated. Never invent either.
- confidence is 0..1. reason_code must describe the evidence category, not private
  reasoning. Do not diagnose health or infer emotion.

You receive no activity history. The optional clock/level labels are coarse care context,
not evidence about the user's body or work content."""


@dataclass(frozen=True)
class CareIntent:
    intent: str
    requested_minutes: Optional[int]
    until_local_time: Optional[str]
    release_condition: Optional[str]
    confidence: float
    reason_code: str
    source: str = "llm"


class CareDialogue:
    """Một LLM call, một tool schema riêng, không history và không retry tại đây."""

    def __init__(self, llm):
        self.llm = llm

    def classify(self, text, clock=None, level=None):
        raw = str(text or "")
        normalized = norm(raw)
        # Hai guard hẹp, tất định: giữ fast-path SALM-1 cũ và không trao quyền tắt rộng
        # cho model. Chúng không lưu/log raw utterance.
        broad_scope = any(phrase in normalized for phrase in (
            "moi thong bao", "tat ca thong bao", "toan bo thong bao"))
        permanent = any(phrase in normalized for phrase in (
            "khong bao gio", "dung bao gio", "vinh vien", "mai mai",
            "may ngay", "vai ngay"))
        if broad_scope or permanent:
            return CareIntent(
                "unclear", None, None, None, 1.0,
                "conflicting_request" if broad_scope else "ambiguous_request",
                source="guard")
        if match_snooze(raw):
            return CareIntent(
                "snooze", None, None, None, 1.0, "short_delay",
                source="guard")
        # Context coarse nằm trong system để raw utterance vẫn là duy nhất một user message.
        context = f"\nCurrent care context: clock={clock or 'unknown'}, level={level or 'unknown'}."
        try:
            turn = self.llm.generate(
                system=_SYSTEM + context,
                messages=[Message(role="user", text=raw)],
                tools=[CARE_INTENT_TOOL],
            )
        except Exception as exc:
            # Không log raw utterance: log chỉ loại lỗi để giữ privacy contract.
            logger.warning("SALM Care Dialogue intent lỗi: %s", type(exc).__name__)
            return None
        calls = getattr(turn, "tool_calls", ()) or ()
        if len(calls) != 1:
            return None
        call = calls[0]
        if getattr(call, "name", None) != _TOOL_NAME:
            return None
        return parse_care_intent(getattr(call, "arguments", None))


def parse_care_intent(arguments):
    """Strict parse: sai/mất/thừa field đều fail closed, không repair ngầm."""
    if not isinstance(arguments, dict) or frozenset(arguments) != _EXPECTED_KEYS:
        return None
    intent = arguments.get("intent")
    release = arguments.get("release_condition")
    reason = arguments.get("reason_code")
    minutes = arguments.get("requested_minutes")
    local_time = arguments.get("until_local_time")
    confidence = arguments.get("confidence")
    if intent not in CARE_INTENTS:
        return None
    if release is not None and release not in RELEASE_CONDITIONS:
        return None
    if reason not in REASON_CODES:
        return None
    if minutes is not None and (isinstance(minutes, bool)
                                or not isinstance(minutes, int)):
        return None
    if local_time is not None and not isinstance(local_time, str):
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    confidence = float(confidence)
    if not 0.0 <= confidence <= 1.0:
        return None
    return CareIntent(intent, minutes, local_time, release, confidence, reason)
