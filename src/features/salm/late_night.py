"""Late-night Care: explicit policy now, replaceable observed baseline later."""

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

from features.salm.models import ActivityKind, DisplayState, Presence
from features.salm.voice import compose_speech_system
from features.salm.welcome import safe_address_form
from llm.client import Message
from utils.atomic_json import write_json
from utils.logger import get_logger
from utils.text_norm import norm

logger = get_logger(__name__)

POLICY_KEY = "salm.late_night_policy"
CARE_DAY_START_MINUTE = 4 * 60
DEFAULT_MIN_ACTIVE_SECONDS = 15 * 60.0
ACTIVE_GAP_GRACE_SECONDS = 2 * 60.0
MAX_SNOOZE_MINUTES = 180
_LATE_MINUTE_MIN = 18 * 60
_LATE_MINUTE_MAX = 3 * 60 + 30


@dataclass(frozen=True)
class RoutineBaseline:
    status: str = "insufficient_data"
    expected_end_minute: Optional[int] = None
    confidence: str = "low"
    valid_days: int = 0
    source: str = "none"


class NoRoutineBaselineProvider:
    """LN-A/B seam: future observed learner implements the same method."""

    def snapshot(self, _at=None):
        return RoutineBaseline()


@dataclass(frozen=True)
class LateNightSignal:
    action: str
    candidate_id: str
    care_day: str
    at: datetime
    reason_codes: Tuple[str, ...]
    confidence: str = "high"
    basis: str = "explicit_cutoff"
    baseline_status: str = "insufficient_data"

    @property
    def clock(self):
        return "late_night_activity"

    @property
    def level(self):
        return "gentle"

    def to_record(self):
        return {
            "kind": "late_night_signal",
            "at": self.at.isoformat(),
            "candidate_id": self.candidate_id,
            "care_day": self.care_day,
            "decision": self.action,
            "reason_codes": list(self.reason_codes),
            "confidence": self.confidence,
            "basis": self.basis,
            "baseline_status": self.baseline_status,
        }


class LateNightPolicyStore:
    """Explicit-only preference; observed behavior never writes this store."""

    def __init__(self, path=None, database=None):
        self.path = Path(path) if path else None
        self.database = database
        self._lock = threading.RLock()
        self._value = {"enabled": False, "cutoff_minute": None,
                       "source": "explicit_user"}
        self._load()

    @staticmethod
    def _validated(value):
        if not isinstance(value, dict):
            return None
        enabled = value.get("enabled")
        cutoff = value.get("cutoff_minute")
        if not isinstance(enabled, bool):
            return None
        if cutoff is not None and (isinstance(cutoff, bool)
                                   or not isinstance(cutoff, int)
                                   or not 0 <= cutoff <= 1439):
            return None
        if enabled and cutoff is None:
            return None
        if cutoff is not None and not _is_late_minute(cutoff):
            return None
        return {"enabled": enabled, "cutoff_minute": cutoff,
                "source": "explicit_user"}

    def snapshot(self):
        with self._lock:
            return dict(self._value)

    def configure(self, cutoff_minute):
        clean = self._validated({"enabled": True,
                                 "cutoff_minute": int(cutoff_minute)})
        if clean is None:
            raise ValueError("Giờ nhắc khuya phải nằm từ 18:00 đến 03:30.")
        with self._lock:
            self._value = clean
            self._save()
        return self.snapshot()

    def disable(self):
        with self._lock:
            cutoff = self._value.get("cutoff_minute")
            self._value = {"enabled": False, "cutoff_minute": cutoff,
                           "source": "explicit_user"}
            self._save()
        return self.snapshot()

    def reset(self):
        with self._lock:
            self._value = {"enabled": False, "cutoff_minute": None,
                           "source": "explicit_user"}
            if self.database is not None:
                try:
                    self.database.delete_user_preference(POLICY_KEY)
                except Exception:
                    logger.warning("Không xóa được Late-night policy khỏi SQLite",
                                   exc_info=True)
            if self.path and self.path.exists():
                try:
                    os.remove(self.path)
                except OSError:
                    logger.warning("Không xóa được fallback Late-night policy",
                                   exc_info=True)
        return self.snapshot()

    def _load(self):
        raw = None
        if self.database is not None:
            try:
                row = self.database.user_preference(POLICY_KEY)
                raw = (row or {}).get("value")
            except Exception:
                logger.warning("Không đọc được Late-night policy từ SQLite",
                               exc_info=True)
        if raw is None and self.path and self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                logger.warning("Bỏ qua fallback Late-night policy hỏng",
                               exc_info=True)
        clean = self._validated(raw)
        if clean is not None:
            self._value = clean

    def _save(self):
        payload = dict(self._value)
        if self.database is not None:
            try:
                self.database.set_user_preference(
                    POLICY_KEY, payload, source="explicit_user",
                    consent_scope="late_night_care")
                return
            except Exception:
                logger.warning("Không lưu được Late-night policy vào SQLite; "
                               "dùng fallback local", exc_info=True)
        if self.path:
            write_json(str(self.path), payload)


def _is_late_minute(value):
    return value >= _LATE_MINUTE_MIN or value <= _LATE_MINUTE_MAX


def care_day_for(at):
    local = at if at.tzinfo else at.astimezone()
    return (local - timedelta(minutes=CARE_DAY_START_MINUTE)).date().isoformat()


def _care_coordinate(minute):
    return (int(minute) - CARE_DAY_START_MINUTE) % (24 * 60)


def _after_cutoff(at, cutoff_minute):
    local = at if at.tzinfo else at.astimezone()
    minute = local.hour * 60 + local.minute
    return _care_coordinate(minute) >= _care_coordinate(cutoff_minute)


def format_clock(minute):
    minute = int(minute) % (24 * 60)
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _parse_clock(value):
    match = re.search(r"(?<!\d)(\d{1,2})(?:\s*(?::|h|gio)\s*(\d{1,2}))?(?!\d)",
                      value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    tail = value[match.end():match.end() + 18]
    if minute > 59:
        return None
    if "dem" in tail or "khuya" in tail:
        if hour == 12:
            hour = 0
        elif 6 <= hour <= 11:
            hour += 12
    elif "sang" in tail and hour == 12:
        hour = 0
    elif "buoi toi" in tail and 1 <= hour <= 11:
        hour += 12
    if hour > 23:
        return None
    result = hour * 60 + minute
    return result if _is_late_minute(result) else None


def match_late_night_command(text):
    """Narrow deterministic matcher; unrelated mentions of staying late pass through."""
    value = " ".join(norm(text or "").split())
    # Whisper/STT tiếng Việt thường thay phụ âm cuối của "nhắc" thành "nhất". Chỉ
    # sửa đúng cụm domain này, không fuzzy-match từ "nhất" ở nơi khác.
    value = re.sub(r"\b(?:nhat khuya|nhac khue)\b", "nhac khuya", value)
    scoped = any(phrase in value for phrase in (
        "nhac khuya", "nhac toi khi dung may khuya", "nhac toi khi lam viec khuya",
        "nhac dung may khuya", "late night care", "nhac qua khuya"))
    if not scoped:
        return None
    if any(phrase in value for phrase in (
            "xem", "dang cai", "cai dat", "may gio")):
        return {"action": "show"}
    if any(phrase in value for phrase in ("dat lai", "reset", "xoa cai dat")):
        return {"action": "reset"}
    duration = re.search(r"(?:sau|them)\s+(\d{1,3})\s*phut", value)
    if duration and any(phrase in value for phrase in ("nhac lai", "nhac khuya")):
        minutes = int(duration.group(1))
        if 1 <= minutes <= MAX_SNOOZE_MINUTES:
            return {"action": "snooze", "minutes": minutes}
        return {"action": "invalid_snooze"}
    if "dem nay" in value and any(phrase in value for phrase in (
            "dung nhac", "khong nhac", "bo qua")):
        return {"action": "mute_tonight"}
    if any(phrase in value for phrase in (
            "tat", "dung nhac", "khong nhac nua", "ngung")):
        return {"action": "disable"}
    cutoff = _parse_clock(value)
    if cutoff is not None:
        return {"action": "enable", "cutoff_minute": cutoff}
    if any(word in value for word in ("bat", "nhac toi", "kich hoat")):
        return {"action": "need_cutoff"}
    return None


class LateNightEvaluator:
    def __init__(self, policy, baseline=None,
                 min_active_seconds=DEFAULT_MIN_ACTIVE_SECONDS,
                 active_gap_grace=ACTIVE_GAP_GRACE_SECONDS):
        self.policy = policy
        self.baseline = baseline or NoRoutineBaselineProvider()
        self.min_active_seconds = max(0.0, float(min_active_seconds))
        self.active_gap_grace = max(0.0, float(active_gap_grace))
        self._lock = threading.RLock()
        self._streak_start = None
        self._last_active = None
        self._handled_day = None
        self._muted_day = None
        self._snooze_until = 0.0

    def reset_runtime(self):
        with self._lock:
            self._streak_start = self._last_active = None
            self._handled_day = self._muted_day = None
            self._snooze_until = 0.0

    def mute_tonight(self, at):
        with self._lock:
            self._muted_day = care_day_for(at)
            self._streak_start = self._last_active = None
        return self._muted_day

    def snooze(self, now, minutes):
        minutes = max(1, min(MAX_SNOOZE_MINUTES, int(minutes)))
        with self._lock:
            self._snooze_until = max(self._snooze_until,
                                     float(now) + minutes * 60.0)
        return minutes

    def evaluate(self, snapshot, state, gate, *, shared_cooldown=False):
        policy = self.policy.snapshot()
        if not policy.get("enabled") or policy.get("cutoff_minute") is None:
            return None
        now = float(snapshot.monotonic)
        at = snapshot.wall_time
        day = care_day_for(at)
        active = (state.presence == Presence.PRESENT
                  and state.activity == ActivityKind.ACTIVE_INTERACTIVE
                  and state.display in (DisplayState.ON, DisplayState.DIM)
                  and _after_cutoff(at, policy["cutoff_minute"]))
        with self._lock:
            if self._handled_day == day or self._muted_day == day:
                return None
            if not active:
                self._streak_start = self._last_active = None
                return None
            if (self._last_active is None
                    or now - self._last_active > self.active_gap_grace):
                self._streak_start = now
            self._last_active = now
            if now < self._snooze_until or shared_cooldown:
                return None
            if now - self._streak_start < self.min_active_seconds:
                return None

            baseline = self.baseline.snapshot(at)
            reasons = tuple(gate.reasons("break_care", now=now))
            transient = {"assistant_busy", "post_dnd_grace"}
            hard_reasons = tuple(reason for reason in reasons
                                 if reason not in transient)
            if reasons and not hard_reasons:
                return None
            self._handled_day = day
            action = "drop" if hard_reasons else "dispatch"
            reason_codes = (("explicit_cutoff_crossed", "sustained_interaction")
                            if action == "dispatch" else
                            ("gate_blocked",) + hard_reasons)
            return LateNightSignal(
                action=action, candidate_id=f"late_night:{day}",
                care_day=day, at=at, reason_codes=reason_codes,
                baseline_status=baseline.status)


_LANGUAGE_SYSTEM = """Bạn viết một lời nhắc Late-night Care ngắn bằng tiếng Việt.
Code đã xác nhận người dùng vẫn tương tác với máy sau cutoff do chính họ đặt. Bạn chỉ
diễn đạt; không quyết định có nhắc hay không. Giữ đúng persona được cung cấp, tối đa hai
câu và 35 từ, không markdown. Nói trung tính rằng đã khá khuya và mời cân nhắc khép lại
phiên dùng máy/nghỉ ngơi. Không nói người dùng đang làm việc, chạy deadline, stress, mệt,
thiếu ngủ, làm quá sức hoặc có vấn đề sức khỏe. Không nói đã theo dõi/quan sát, không nêu
app, giờ chính xác, thời lượng hay dữ liệu lịch sử. Không gây tội lỗi hoặc ra lệnh."""

_LANGUAGE_FORBIDDEN = (
    "theo doi", "quan sat", "lam viec", "deadline", "stress", "met", "thieu ngu",
    "qua suc", "suc khoe", "bat buoc", "phai nghi", "cham chi", "hieu qua",
)


def clean_late_night_language(value, address_form="bạn"):
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if any(mark in raw for mark in ("\n", "\r", "`", "*", "#", "<", ">")):
        return None
    text = re.sub(r"\s+", " ", raw).strip().strip('"“”')
    lowered = norm(text)
    if not 8 <= len(text) <= 220 or len(text.split()) > 35:
        return None
    if re.search(r"\d", lowered) or any(term in lowered
                                         for term in _LANGUAGE_FORBIDDEN):
        return None
    if not any(term in lowered for term in ("khuya", "muon")):
        return None
    expected = norm(safe_address_form(address_form))
    words = lowered.split()
    if expected != "anh" and "anh" in words:
        return None
    if expected != "ban" and "ban" in words:
        return None
    return text


class LateNightLanguage:
    def __init__(self, llm=None, timeout_seconds=3.5,
                 address_form_provider=None, persona_context_provider=None,
                 proactive_text_provider=None):
        self.llm = llm
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.address_form_provider = address_form_provider
        self.persona_context_provider = persona_context_provider
        self.proactive_text_provider = proactive_text_provider
        self._lock = threading.Lock()
        self._pending = False

    def _address(self):
        try:
            return safe_address_form(
                self.address_form_provider() if self.address_form_provider else None)
        except Exception:
            return "bạn"

    def generate(self, _signal):
        address = self._address()
        builtin = (f"{address[:1].upper() + address[1:]}, đã khá khuya rồi. "
                   "Mình cân nhắc khép lại phiên dùng máy và nghỉ ngơi nhé?")
        fallback = builtin
        if self.proactive_text_provider is not None:
            try:
                candidate = self.proactive_text_provider(
                    "care_late_night", address_form=address)
                fallback = clean_late_night_language(candidate, address) or builtin
            except Exception:
                fallback = builtin
        if self.llm is None:
            return fallback
        with self._lock:
            if self._pending:
                return fallback
            self._pending = True
        done = threading.Event()
        result = []

        def call_model():
            try:
                turn = self.llm.generate(
                    system=compose_speech_system(
                        _LANGUAGE_SYSTEM, self.persona_context_provider),
                    messages=[Message(
                        role="user",
                        text=("purpose: late_night_checkin\n"
                              f"addressing_style: {address}\n"
                              "basis: explicit_cutoff\n"
                              "baseline_status: insufficient_data"))],
                    tools=[])
                if not getattr(turn, "tool_calls", ()):
                    result.append(clean_late_night_language(
                        getattr(turn, "text", None), address))
            except Exception as exc:
                logger.warning("Late-night language lỗi: %s", type(exc).__name__)
            finally:
                with self._lock:
                    self._pending = False
                done.set()

        try:
            threading.Thread(target=call_model, name="salm-late-night-language",
                             daemon=True).start()
        except RuntimeError:
            with self._lock:
                self._pending = False
            logger.warning("Không khởi động được Late-night language worker.")
            return fallback
        if not done.wait(self.timeout_seconds):
            logger.warning("Late-night language quá deadline, dùng fallback.")
            return fallback
        return result[0] if result and result[0] else fallback
