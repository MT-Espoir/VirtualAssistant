"""Validate intent và là nơi duy nhất commit snooze/User Care DND."""

from dataclasses import dataclass
from datetime import timedelta

from features.salm.dialogue import CareIntent
from features.salm.checkin import SNOOZE_REPLY_TEXT
from features.salm.welcome import safe_address_form

DEFAULT_SNOOZE_MINUTES = 10
MIN_SNOOZE_MINUTES = 1
MAX_SNOOZE_MINUTES = 120
MAX_DND_MINUTES = 24 * 60

_CLARIFY_TEMPLATE = (
    "{address_form} muốn em hoãn nhắc nghỉ bao lâu, hay im lặng trong phiên làm việc này ạ?")
_ACCEPT_TEMPLATE = "Vâng, mình nghỉ một chút nhé {address_form}."
CLARIFY_REPLY = _CLARIFY_TEMPLATE.format(address_form="Anh")
ACCEPT_REPLY = _ACCEPT_TEMPLATE.format(address_form="anh")
DECLINE_REPLY = "Vâng, em hiểu rồi. Em sẽ không nhắc lại lượt này nữa."
RESUME_REPLY = "Được ạ, em đã bật lại nhắc nghỉ. Em sẽ chỉ nhắc khi đúng lúc nhé."


@dataclass(frozen=True)
class CareActionResult:
    handled: bool
    committed: bool = False
    action: str = "none"
    reply: str = None
    reason_code: str = "unrelated"
    minutes: int = None

    def to_record(self, at):
        return {
            "kind": "care_action",
            "at": at.isoformat(),
            "action": self.action,
            "committed": self.committed,
            "reason_code": self.reason_code,
            "minutes": self.minutes,
        }


class CareActionPolicy:
    """LLM chỉ đề xuất; lớp này kiểm schema ngữ nghĩa rồi mới mutate state."""

    def __init__(self, break_policy, care_dnd, gate, user_dnd_enabled=False,
                 address_form_provider=None):
        self.break_policy = break_policy
        self.care_dnd = care_dnd
        self.gate = gate
        self.user_dnd_enabled = bool(user_dnd_enabled)
        self.address_form_provider = address_form_provider

    def apply(self, intent, session, now, at):
        address_form = self._address_form()
        if not isinstance(intent, CareIntent):
            return CareActionResult(False)
        if intent.intent == "unrelated" or intent.confidence < 0.55:
            return CareActionResult(False, reason_code="low_confidence")
        if intent.intent == "unclear" or intent.confidence < 0.80:
            return CareActionResult(True, reply=self._clarify(address_form),
                                    reason_code="clarification_required")

        if intent.intent == "accept":
            if not self._empty_payload(intent):
                return self._invalid(address_form=address_form)
            return CareActionResult(True, True, "accept",
                                    _ACCEPT_TEMPLATE.format(address_form=address_form),
                                    intent.reason_code)
        if intent.intent == "decline_once":
            if not self._empty_payload(intent):
                return self._invalid(address_form=address_form)
            return CareActionResult(True, True, "decline_once", DECLINE_REPLY,
                                    intent.reason_code)
        if intent.intent == "resume_care":
            if (intent.release_condition not in (None, "explicit_resume")
                    or intent.requested_minutes is not None
                    or intent.until_local_time is not None):
                return self._invalid(address_form=address_form)
            changed = self.care_dnd.clear()
            self.gate.set_user_care_dnd(False)
            self.break_policy.discard_pending()
            return CareActionResult(True, changed, "resume_care", RESUME_REPLY,
                                    intent.reason_code)
        if session is None:
            return CareActionResult(False, reason_code="no_active_checkin")
        if intent.intent == "snooze":
            return self._snooze(intent, session, now, at, address_form)
        if intent.intent == "care_dnd":
            return self._dnd(intent, session, now, at, address_form)
        return self._invalid(address_form=address_form)

    def _snooze(self, intent, session, now, at, address_form):
        if intent.release_condition not in (None, "deadline") or intent.until_local_time:
            return self._invalid(address_form=address_form)
        minutes = (DEFAULT_SNOOZE_MINUTES if intent.requested_minutes is None
                   else intent.requested_minutes)
        if not isinstance(minutes, int) or minutes < MIN_SNOOZE_MINUTES:
            return self._invalid(address_form=address_form)
        if minutes > MAX_DND_MINUTES:
            return self._invalid(address_form=address_form)
        if minutes > MAX_SNOOZE_MINUTES:
            if not self.user_dnd_enabled:
                return self._invalid(address_form=address_form)
            return self._commit_timed(
                session, now, at, minutes, intent.reason_code, address_form)
        if not self.break_policy.snooze(
                session.candidate_id, now, seconds=minutes * 60.0):
            return self._invalid("candidate_not_dispatchable", address_form)
        reply = (SNOOZE_REPLY_TEXT if minutes == DEFAULT_SNOOZE_MINUTES else
                 f"Vâng, em để {address_form} thêm {minutes} phút nhé. "
                 "Sau đó nếu đúng lúc em sẽ nhắc lại.")
        return CareActionResult(True, True, "snooze", reply,
                                intent.reason_code, minutes)

    def _dnd(self, intent, session, now, at, address_form):
        if not self.user_dnd_enabled:
            return self._invalid("user_dnd_disabled", address_form)
        release = intent.release_condition
        if release == "deadline":
            minutes = intent.requested_minutes
            if minutes is None and intent.until_local_time:
                minutes = self._minutes_until(intent.until_local_time, at)
            if not isinstance(minutes, int) or not 1 <= minutes <= MAX_DND_MINUTES:
                return self._invalid(address_form=address_form)
            return self._commit_timed(
                session, now, at, minutes, intent.reason_code, address_form)
        if (release == "work_cycle_reset" and intent.requested_minutes is None
                and intent.until_local_time is None):
            cycle_id = (session.work_cycle_id if session.work_cycle_id is not None
                        else session.cycle_id)
            if not self.care_dnd.set_cycle(at, cycle_id):
                return self._invalid("dnd_commit_failed", address_form)
            self.gate.set_user_care_dnd(True)
            return CareActionResult(
                True, True, "cycle_dnd",
                "Được ạ, em sẽ không chen vào phiên làm việc này nữa. "
                f"Khi muốn em nhắc lại, {address_form} cứ gọi.",
                intent.reason_code)
        if (release == "app_session" and intent.requested_minutes is None
                and intent.until_local_time is None):
            if not self.care_dnd.set_session(at):
                return self._invalid("dnd_commit_failed", address_form)
            self.gate.set_user_care_dnd(True)
            return CareActionResult(
                True, True, "session_dnd",
                "Được ạ, em sẽ tạm ngừng nhắc nghỉ trong phiên này. "
                f"{address_form[0].upper() + address_form[1:]} có thể bảo em bật lại bất cứ lúc nào.",
                intent.reason_code)
        return self._invalid(address_form=address_form)

    def _commit_timed(self, session, now, at, minutes, reason_code, address_form):
        # Re-use one-shot snooze recheck: tới deadline, runtime mở gate trước khi policy
        # evaluate; policy sẽ dispatch/drop đúng một lần và consume mọi armed candidate.
        deadline = at + timedelta(minutes=minutes)
        if not self.care_dnd.set_timed(at, deadline):
            return self._invalid("dnd_commit_failed", address_form)
        if not self.break_policy.snooze(
                session.candidate_id, now, seconds=minutes * 60.0):
            self.care_dnd.clear()
            return self._invalid("candidate_not_dispatchable", address_form)
        self.gate.set_user_care_dnd(True)
        reply = (f"Được ạ, em sẽ không nhắc nghỉ trong {minutes} phút. "
                 "Sau đó nếu đúng lúc em mới nhắc lại nhé.")
        return CareActionResult(True, True, "timed_dnd", reply,
                                reason_code, minutes)

    @staticmethod
    def _minutes_until(raw, at):
        try:
            hour, minute = (int(part) for part in raw.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
            deadline = at.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if deadline <= at:
                deadline += timedelta(days=1)
            seconds = (deadline - at).total_seconds()
            return int((seconds + 59) // 60)
        except (AttributeError, TypeError, ValueError):
            return None

    def _address_form(self):
        try:
            value = (self.address_form_provider()
                     if self.address_form_provider is not None else None)
        except Exception:
            value = None
        return safe_address_form(value)

    @staticmethod
    def _clarify(address_form):
        titled = address_form[0].upper() + address_form[1:]
        return _CLARIFY_TEMPLATE.format(address_form=titled)

    @classmethod
    def _invalid(cls, reason="invalid_intent_contract", address_form="anh"):
        return CareActionResult(
            True, False, "none", cls._clarify(address_form), reason)

    @staticmethod
    def _empty_payload(intent):
        return (intent.requested_minutes is None
                and intent.until_local_time is None
                and intent.release_condition is None)
