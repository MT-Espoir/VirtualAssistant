"""Ngôn ngữ LLM cho Break Care sau khi policy đã quyết định.

Lane này không thấy raw activity, app/window, lịch sử Agent hay câu người dùng vừa nói.
Nó chỉ diễn đạt context đã whitelist và luôn có fallback tất định.
"""

import re
import threading
from difflib import SequenceMatcher

from features.salm.checkin import checkin_text
from features.salm.voice import compose_speech_system
from features.salm.welcome import safe_address_form
from llm.client import Message
from utils.logger import get_logger
from utils.text_norm import norm

logger = get_logger(__name__)

CARE_LANGUAGE_TIMEOUT_SECONDS = 3.5
_INITIAL_STYLES = (
    "mở bằng một lời mời nhẹ rồi nêu động tác nghỉ ngắn",
    "nêu động tác nghỉ ngắn trước, kết bằng lời mời mềm",
    "một câu đơn có nhịp ngắt rõ, không thúc ép",
    "đổi cấu trúc câu nhưng giữ nguyên hành động được phép",
)
_REPLY_STYLES = (
    "xác nhận action trước rồi kết câu ngắn",
    "gọi người dùng trước rồi xác nhận action",
    "một câu đơn, không thêm lời khuyên",
)

_SYSTEM = """Bạn viết lời thoại Break Care ngắn cho trợ lý Alice bằng tiếng Việt.
LLM chỉ diễn đạt; action đã được code xác thực và commit trước khi bạn được gọi.
Xưng em. Nếu gọi người dùng, dùng đúng addressing_style; không tự đổi sang anh, bạn hoặc
cách gọi khác. Chỉ trả đúng một hoặc hai câu để đọc bằng TTS, không markdown/ngoặc kép.
Giữ dưới 35 từ và giữ đúng nhân cách chung được cung cấp ở phía trên. Không gây sức ép.
Tuân theo preference có enum: length concise thì tối đa 22 từ; directness chỉ điều
chỉnh độ thẳng của cách diễn đạt, không tăng sức ép; address_frequency frequent thì
phải dùng đúng addressing_style, sparse thì không gọi người dùng trong câu.

Không nói rằng người dùng đang mệt, đau, stress, căng vai, khô/mỏi mắt, cố quá sức hoặc có
vấn đề sức khỏe. Không đe dọa hậu quả, tạo tội lỗi, lên lớp hay tranh luận sau từ chối.
Không nói đã theo dõi, biết nội dung công việc, biết việc sắp xong hoặc biết lúc việc hoàn tất.
Không nhắc app, cửa sổ, URL, raw activity hay thời lượng đã quan sát.
Với initial_checkin: chỉ gợi ý một nghỉ chuyển động/nhìn xa phù hợp clock; không đọc số phút.
work_engagement gợi ý thả lỏng tay/vai hoặc đứng dậy; screen_exposure soft gợi ý nhìn xa,
chớp mắt; screen_exposure hard phải gợi ý rời màn hình, đứng lên hoặc đi lại.
Với validated_reply: phản ánh đúng validated_action, không thêm hay đổi action. Chỉ đọc số
phút khi action chính nó chứa số phút. cycle_dnd phải gọi là phiên làm việc này, không hứa
nhận biết công việc hoàn thành. resume_care chỉ xác nhận đã bật lại, không phát nhắc bù.

Contract diễn đạt validated_action:
- snooze(Nm): phải nói rõ "thêm N phút"; không gọi là tắt nhắc hay không làm phiền.
- timed_dnd(Nm): phải nói rõ "không nhắc nghỉ trong N phút"; scope chỉ là nhắc nghỉ.
- cycle_dnd: phải nói "không nhắc" hoặc "không chen" trong "phiên làm việc này".
- session_dnd: phải nói "tạm ngừng nhắc nghỉ" hoặc "không nhắc" trong "phiên này".
- resume_care: phải xác nhận đúng cụm "đã bật lại nhắc nghỉ".
- decline_once: phải xác nhận "không nhắc lại lượt này/lần này", không khuyên làm tiếp.
- accept: chỉ mời "nghỉ một chút", không nói đã ghi nhận hay biết người dùng đã nghỉ.
Không thay các contract trên bằng cụm rộng "chế độ không làm phiền".
"""

_FORBIDDEN = (
    "theo doi", "quan sat anh", "quan sat ban", "met", "dau", "stress",
    "cang thang", "kho mat", "moi mat", "mat da moi", "vai da cung",
    "vai cung", "co qua suc", "gang suc", "suc khoe", "benh", "nguy hiem",
    "bat buoc", "phai nghi", "mai me qua", "da lam viec", "lam viec qua lau",
    "em biet anh", "em biet ban", "sap xong", "sap hoan thanh",
    "khong bao gio", "vinh vien", "mai mai",
    "dong hanh", "san sang", "ho tro", "cu tiep tuc", "tap trung hoan toan",
    "that hieu qua",
)


def clean_care_language(value, *, purpose, address_form="anh", action="none",
                        minutes=None, clock=None, level=None, max_words=35,
                        address_frequency="balanced"):
    """Fail closed với câu không phản ánh đúng context/action đã validate."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if any(mark in raw for mark in ("\n", "\r", "`", "*", "#", "<", ">")):
        return None
    text = re.sub(r"\s+", " ", raw).strip().strip('"“”')
    if not 8 <= len(text) <= 220 or len(text.split()) > max_words:
        return None
    lowered = " ".join(re.findall(r"[a-z0-9]+", norm(text)))
    words = lowered.split()
    if "http" in lowered or any(phrase in lowered for phrase in _FORBIDDEN):
        return None

    address_form = safe_address_form(address_form)
    address_words = norm(address_form).split()
    has_address = _contains_words(words, address_words)
    if address_frequency == "frequent" and not has_address:
        return None
    if address_frequency == "sparse" and has_address:
        return None
    # Không bắt buộc gọi người dùng trong mọi câu, nhưng nếu model dùng cách gọi phổ biến
    # thì không được tự thay thế lựa chọn đã lưu.
    if "anh" not in address_words and "anh" in words:
        return None
    if "ban" not in address_words and "ban" in words:
        return None
    if purpose == "initial_checkin":
        if re.search(r"\d", lowered) or "phut" in words or "gio" in words:
            return None
        if clock == "screen_exposure" and level == "hard" and not any(
                phrase in lowered for phrase in (
                    "roi man hinh", "di lai", "dung len")):
            return None
        if clock == "screen_exposure" and level != "hard" and not any(
                phrase in lowered for phrase in ("nhin xa", "chop mat")):
            return None
        return text
    if purpose != "validated_reply" or "em" not in words:
        return None

    if action in ("snooze", "timed_dnd"):
        if (not isinstance(minutes, int)
                or f"{minutes} phut" not in lowered):
            return None
        other_numbers = {int(number) for number in re.findall(r"\d+", lowered)}
        if other_numbers and other_numbers != {minutes}:
            return None
        if action == "snooze" and f"{minutes} phut nghi" in lowered:
            return None
    elif re.search(r"\d", lowered) or "phut" in words or "gio" in words:
        return None

    if action == "cycle_dnd":
        if "phien" not in words or "xong" in words or "hoan thanh" in lowered:
            return None
    if action == "session_dnd" and "phien" not in words:
        return None
    if action in ("timed_dnd", "cycle_dnd", "session_dnd") and not any(
            phrase in lowered for phrase in (
                "khong nhac", "im lang", "khong chen", "tam ngung", "de yen")):
        return None
    if action == "accept" and not any(
            phrase in lowered for phrase in ("nghi", "tam dung")):
        return None
    if action == "decline_once" and not any(
            phrase in lowered for phrase in ("luot nay", "lan nay")):
        return None
    if action == "resume_care":
        if "nhac" not in words or not any(
                phrase in lowered for phrase in ("bat lai", "mo lai", "tiep tuc")):
            return None
    return text


def _contains_words(words, needle):
    if not needle or len(needle) > len(words):
        return False
    return any(words[i:i + len(needle)] == needle
               for i in range(len(words) - len(needle) + 1))


def _similar(left, right, threshold=0.82):
    left, right = norm(left or ""), norm(right or "")
    if not left or not right:
        return False
    return left == right or SequenceMatcher(None, left, right).ratio() >= threshold


class CareLanguage:
    """Sinh initial/reply có deadline; một call treo khiến các call sau dùng fallback."""

    def __init__(self, llm, timeout_seconds=CARE_LANGUAGE_TIMEOUT_SECONDS,
                 address_form_provider=None, style_provider=None,
                 persona_context_provider=None, proactive_text_provider=None):
        self.llm = llm
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.address_form_provider = address_form_provider
        self.style_provider = style_provider
        self.persona_context_provider = persona_context_provider
        self.proactive_text_provider = proactive_text_provider
        self._lock = threading.RLock()
        self._pending = False
        self._idle = threading.Event()
        self._idle.set()
        self._initial_style = 0
        self._reply_style = 0
        self._last_initial = None
        self._last_candidate = None
        self._recent_care_count = 0
        self._last_outcome = "unknown"

    def generate_initial(self, clock, level):
        address = self._address_form()
        preferences = self._style_preferences()
        validator = lambda value: clean_care_language(
            value, purpose="initial_checkin", address_form=address,
            clock=clock, level=level,
            max_words=self._max_words(preferences),
            address_frequency=preferences["address_frequency"])
        builtin_fallback = checkin_text(clock, level, address_form=address)
        key = ("care_initial_work_engagement" if clock != "screen_exposure"
               else "care_initial_screen_hard" if level == "hard"
               else "care_initial_screen_soft")
        fallback = self._persona_fallback(
            key, validator, builtin_fallback, address_form=address)
        with self._lock:
            style = _INITIAL_STYLES[
                self._style_index(self._initial_style, preferences["variation"])
                % len(_INITIAL_STYLES)]
            self._initial_style += 1
            recent = min(self._recent_care_count, 9)
            last_outcome = self._last_outcome
        prompt = (
            "purpose: initial_checkin\n"
            f"clock: {clock if clock in ('work_engagement', 'screen_exposure') else 'work_engagement'}\n"
            f"level: {level if level in ('soft', 'hard') else 'soft'}\n"
            "validated_action: none\n"
            f"last_outcome: {last_outcome}\n"
            f"recent_care_count: {recent}\n"
            f"addressing_style: {address}\n"
            f"length_preference: {preferences['length']}\n"
            f"directness_preference: {preferences['directness']}\n"
            f"variation_preference: {preferences['variation']}\n"
            f"address_frequency: {preferences['address_frequency']}\n"
            f"variation_structure: {style}"
        )
        text = self._generate(
            prompt, fallback, validator)
        current_address = self._address_form()
        if current_address != address:
            current_builtin = checkin_text(clock, level, address_form=current_address)
            current_validator = lambda value: clean_care_language(
                value, purpose="initial_checkin", address_form=current_address,
                clock=clock, level=level,
                max_words=self._max_words(preferences),
                address_frequency=preferences["address_frequency"])
            return self._persona_fallback(
                key, current_validator, current_builtin,
                address_form=current_address)
        with self._lock:
            if text != fallback and _similar(
                    text, self._last_initial,
                    self._similarity_threshold(preferences["variation"])):
                text = fallback
            elif text != fallback:
                self._last_initial = text
            self._recent_care_count += 1
        return text

    def generate_reply(self, result, clock=None, level=None):
        builtin_fallback = getattr(result, "reply", None)
        action = getattr(result, "action", "none")
        minutes = getattr(result, "minutes", None)
        if not builtin_fallback or not getattr(result, "committed", False):
            return builtin_fallback
        address = self._address_form()
        preferences = self._style_preferences()
        validator = lambda value: clean_care_language(
            value, purpose="validated_reply", address_form=address,
            action=action, minutes=minutes,
            max_words=self._max_words(preferences),
            address_frequency=preferences["address_frequency"])
        fallback = self._persona_fallback(
            f"care_reply_{action}", validator, builtin_fallback,
            address_form=address, minutes=minutes)
        with self._lock:
            style = _REPLY_STYLES[
                self._style_index(self._reply_style, preferences["variation"])
                % len(_REPLY_STYLES)]
            self._reply_style += 1
            recent = min(self._recent_care_count, 9)
            last_outcome = self._last_outcome
        validated = (f"{action}({minutes}m)"
                     if action in ("snooze", "timed_dnd") else action)
        prompt = (
            "purpose: validated_reply\n"
            f"clock: {clock if clock in ('work_engagement', 'screen_exposure') else 'unknown'}\n"
            f"level: {level if level in ('soft', 'hard') else 'unknown'}\n"
            f"validated_action: {validated}\n"
            f"last_outcome: {last_outcome}\n"
            f"recent_care_count: {recent}\n"
            f"addressing_style: {address}\n"
            f"length_preference: {preferences['length']}\n"
            f"directness_preference: {preferences['directness']}\n"
            f"variation_preference: {preferences['variation']}\n"
            f"address_frequency: {preferences['address_frequency']}\n"
            f"variation_structure: {style}"
        )
        text = self._generate(
            prompt, fallback, validator)
        if self._address_form() != address:
            return fallback
        with self._lock:
            self._last_outcome = {
                "snooze": "snoozed",
                "decline_once": "declined",
            }.get(action, "unknown")
        return text

    def _generate(self, prompt, fallback, validator):
        if self.llm is None:
            return fallback
        with self._lock:
            if self._pending:
                return fallback
            self._pending = True
            self._idle.clear()
            self._last_candidate = None
        completed = threading.Event()
        result = []

        def call_model():
            try:
                turn = self.llm.generate(
                    system=compose_speech_system(
                        _SYSTEM, self.persona_context_provider),
                    messages=[Message(role="user", text=prompt)],
                    tools=[],
                )
                if not getattr(turn, "tool_calls", ()):
                    raw = getattr(turn, "text", None)
                    cleaned = validator(raw)
                    with self._lock:
                        self._last_candidate = (raw, cleaned is not None)
                    result.append(cleaned)
            except Exception as exc:
                logger.warning("SALM Care Language lỗi: %s", type(exc).__name__)
            finally:
                with self._lock:
                    self._pending = False
                self._idle.set()
                completed.set()

        try:
            threading.Thread(
                target=call_model, name="salm-care-language", daemon=True).start()
        except RuntimeError:
            with self._lock:
                self._pending = False
            self._idle.set()
            return fallback
        if not completed.wait(self.timeout_seconds):
            logger.warning("SALM Care Language quá deadline, dùng fallback.")
            return fallback
        return result[0] if result and result[0] else fallback

    def _persona_fallback(self, key, validator, fallback, **values):
        if self.proactive_text_provider is None:
            return fallback
        try:
            candidate = self.proactive_text_provider(key, **values)
            return validator(candidate) or fallback
        except Exception as exc:
            logger.warning("SALM không đọc được care fallback persona: %s",
                           type(exc).__name__)
            return fallback

    def wait_until_idle(self, timeout=None):
        """Chỉ phục vụ pilot/diagnostic; production không chờ lại call đã timeout."""
        return self._idle.wait(timeout)

    def last_candidate(self):
        """Generated text gần nhất cho pilot; không chứa utterance hay activity raw."""
        with self._lock:
            return self._last_candidate

    def _address_form(self):
        try:
            value = (self.address_form_provider()
                     if self.address_form_provider is not None else None)
        except Exception as exc:
            logger.warning("SALM không đọc được cách xưng hô: %s", type(exc).__name__)
            value = None
        return safe_address_form(value)

    def _style_preferences(self):
        defaults = {
            "length": "balanced", "directness": "balanced",
            "variation": "balanced", "address_frequency": "balanced",
        }
        try:
            supplied = self.style_provider() if self.style_provider else {}
        except Exception as exc:
            logger.warning("SALM không đọc được care style: %s", type(exc).__name__)
            supplied = {}
        allowed = {
            "length": ("concise", "balanced"),
            "directness": ("gentle", "balanced", "direct"),
            "variation": ("low", "balanced", "high"),
            "address_frequency": ("sparse", "balanced", "frequent"),
        }
        for field, choices in allowed.items():
            if isinstance(supplied, dict) and supplied.get(field) in choices:
                defaults[field] = supplied[field]
        return defaults

    @staticmethod
    def _max_words(preferences):
        return 22 if preferences["length"] == "concise" else 35

    @staticmethod
    def _style_index(index, variation):
        return index // {"low": 3, "balanced": 2, "high": 1}[variation]

    @staticmethod
    def _similarity_threshold(variation):
        return {"low": 0.92, "balanced": 0.82, "high": 0.72}[variation]
