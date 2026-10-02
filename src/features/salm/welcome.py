"""Consumer presence nhỏ của SALM: nhận diện một lần quay lại đáng để chào.

Không phát UI/TTS và không suy diễn tâm lý. Tracker chỉ biến chuỗi presence thành một
ReturnEvent trung tính; app nộp lời chào qua ProactiveDispatcher.
"""

import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime

from features.salm.models import Presence
from features.salm.voice import compose_speech_system
from llm.client import Message
from utils.logger import get_logger
from utils.text_norm import norm

logger = get_logger(__name__)


WELCOME_BACK_MIN_SECONDS = 2 * 60.0
# Chỉ chống hai transition rung sát nhau; một lần rời máy thật kế tiếp vẫn được chào.
WELCOME_BACK_COOLDOWN_SECONDS = 5 * 60.0

DEFAULT_ADDRESS_FORM = "anh"
_STARTUP_GREETING_TEMPLATE = (
    "Chào {address_form}, em đã sẵn sàng rồi. Mình bắt đầu lúc {address_form} muốn nhé.")
_WELCOME_BACK_GREETING_TEMPLATE = (
    "Mừng {address_form} trở lại. Cứ thong thả nhé, em ở đây nếu {address_form} cần.")
STARTUP_GREETING_TEXT = _STARTUP_GREETING_TEMPLATE.format(
    address_form=DEFAULT_ADDRESS_FORM)
WELCOME_BACK_GREETING_TEXT = _WELCOME_BACK_GREETING_TEMPLATE.format(
    address_form=DEFAULT_ADDRESS_FORM)

WELCOME_LLM_TIMEOUT_SECONDS = 5.0
_WELCOME_STYLES = (
    "mở bằng lời chào trực tiếp rồi nói trạng thái sẵn sàng",
    "đảo thứ tự: nói trạng thái sẵn sàng rồi mới gọi người dùng",
    "một câu đơn, nhịp ngắt rõ để TTS đọc tự nhiên",
    "hai vế ngắn với cấu trúc khác lượt trước",
)
_WELCOME_SYSTEM = """Bạn viết lời chào ngắn cho trợ lý Alice bằng tiếng Việt.
Xưng em, gọi người dùng đúng bằng cách xưng hô được cấp trong yêu cầu; không tự đổi
sang anh, bạn hoặc cách gọi khác. Giữ đúng nhân cách chung được cung cấp ở phía trên.
Viết như một người quen nói chuyện, không như quảng cáo hay tổng đài.
Chỉ trả đúng một hoặc hai câu để đọc bằng TTS, không markdown, không ngoặc kép.
Không nhắc tên app, thời gian sử dụng, thời gian vắng mặt hay dữ liệu quan sát.
Không đoán cảm xúc, sức khỏe, mức mệt, nội dung công việc; không nói rằng đã âm thầm
theo dõi hoặc đợi người dùng. Không tạo lời hứa/cam kết không có bằng chứng.
Tránh các cụm sáo rỗng: "đồng hành", "trải nghiệm", "khoảnh khắc", "hành trình",
"những điều mới mẻ", "sẵn sàng đồng hành". Không phải lời chào nào cũng hỏi cần giúp gì.
Nếu là startup: chào khi ứng dụng vừa mở và giọng đã sẵn sàng.
Nếu là return: mừng người dùng quay lại, không nhắc việc, không mời bắt đầu/tiếp tục.
Giữ dưới 35 từ; thay đổi cấu trúc câu theo nhịp được cấp."""
_FORBIDDEN_WELCOME_PHRASES = (
    "theo doi", "da doi anh", "cho anh suot", "anh met", "anh dau",
    "anh cang thang", "anh stress", "vai anh", "mat anh", "suc khoe anh",
    "anh da lam viec", "anh vang", "phut", "gio roi", "ung dung",
    "trai nghiem", "khoanh khac", "hanh trinh", "dieu moi me",
)
_RETURN_PUSH_PHRASES = ("cong viec", "lam viec", "bat dau", "tiep tuc")


def safe_address_form(value):
    """Chỉ nhận cách xưng hô ngắn, không nhận chỉ dẫn hay dữ liệu hồ sơ khác."""
    if not isinstance(value, str):
        return DEFAULT_ADDRESS_FORM
    address_form = " ".join(value.split())
    if (not address_form or len(address_form) > 40
            or len(address_form.split()) > 4
            or not all(char.isalpha() or char.isspace() for char in address_form)):
        return DEFAULT_ADDRESS_FORM
    return address_form


def welcome_fallback(kind, address_form=DEFAULT_ADDRESS_FORM):
    address_form = safe_address_form(address_form)
    template = (_STARTUP_GREETING_TEMPLATE if kind == "startup"
                else _WELCOME_BACK_GREETING_TEMPLATE)
    return template.format(address_form=address_form)


def _contains_address(words, address_form):
    expected = norm(address_form).split()
    return any(words[index:index + len(expected)] == expected
               for index in range(len(words) - len(expected) + 1))


def clean_welcome_text(value, kind=None, address_form=DEFAULT_ADDRESS_FORM):
    """Nhận đúng thoại ngắn, không metadata/claim quan sát mà SALM không có."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if any(mark in raw for mark in ("\n", "\r", "`", "*", "#", "<", ">")):
        return None
    text = re.sub(r"\s+", " ", raw).strip().strip('"“”')
    if not 8 <= len(text) <= 180 or len(text.split()) > 35:
        return None
    lowered = " ".join(re.findall(r"[a-z0-9]+", norm(text)))
    words = lowered.split()
    address_form = safe_address_form(address_form)
    if (not _contains_address(words, address_form) or "em" not in words
            or "http" in lowered):
        return None
    if "anh" not in norm(address_form).split() and "anh" in words:
        return None
    if any(phrase in lowered for phrase in _FORBIDDEN_WELCOME_PHRASES):
        return None
    normalized_address = norm(address_form)
    if any(phrase in lowered for phrase in (
            f"da doi {normalized_address}",
            f"cho {normalized_address} suot",
            f"da cho {normalized_address}")):
        return None
    if any(f"{normalized_address} {phrase}" in lowered
           for phrase in ("met", "dau", "cang thang", "stress", "da lam viec", "vang")):
        return None
    if any(f"{phrase} {normalized_address}" in lowered
           for phrase in ("vai", "mat", "suc khoe")):
        return None
    if kind == "return" and any(phrase in lowered for phrase in _RETURN_PUSH_PHRASES):
        return None
    return text


class WelcomeDialogue:
    """Lane LLM lời chào có deadline; hết hạn hoặc lỗi trả template tất định.

    Lời chào chỉ dùng loại event, style hint và cách xưng hô từ hồ sơ; không history Agent.
    Một call bị
    timeout có thể kết thúc muộn trong daemon thread, nhưng không được phát muộn và không
    tạo call mới khi call cũ còn treo.
    """

    def __init__(self, llm, timeout_seconds=WELCOME_LLM_TIMEOUT_SECONDS,
                 address_form_provider=None, persona_context_provider=None,
                 proactive_text_provider=None, status_sink=None):
        self.llm = llm
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.address_form_provider = address_form_provider
        self.persona_context_provider = persona_context_provider
        self.proactive_text_provider = proactive_text_provider
        self.status_sink = status_sink
        self._lock = threading.Lock()
        self._pending = False
        self._style_index = 0

    def _report(self, message, data=None, level="INFO"):
        if self.status_sink is not None:
            try:
                self.status_sink(message, data or {}, level=level)
            except Exception:
                pass
        elif level in {"WARNING", "ERROR"}:
            logger.warning("%s %s", message, data or {})

    def generate(self, kind, before_call=None):
        address_form = self._address_form()
        fallback = self._fallback(kind, address_form)
        if kind not in ("startup", "return"):
            return fallback
        if self.llm is None:
            return fallback
        with self._lock:
            if self._pending:
                self._report("Welcome LLM using fallback", {"reason": "in_flight"})
                return fallback
            self._pending = True
            style = _WELCOME_STYLES[self._style_index % len(_WELCOME_STYLES)]
            self._style_index += 1

        completed = threading.Event()
        expired = threading.Event()
        deadline = time.monotonic() + self.timeout_seconds
        result = []

        def classify():
            try:
                system = compose_speech_system(
                    _WELCOME_SYSTEM, self.persona_context_provider)
                messages = [Message(
                    role="user",
                    text=(f"Loại lời chào: {kind}. "
                          f"Cách gọi người dùng: {address_form}. "
                          f"Nhịp diễn đạt: {style}."))]
                if expired.is_set() or time.monotonic() >= deadline:
                    return
                if before_call is not None and not before_call(
                        system=system, messages=messages, tools=[]):
                    return
                if expired.is_set() or time.monotonic() >= deadline:
                    return
                turn = self.llm.generate(
                    system=system,
                    messages=messages,
                    tools=[],
                )
                if getattr(turn, "tool_calls", ()):
                    self._report("Welcome LLM using fallback", {"reason": "tool_call"})
                    return
                result.append(clean_welcome_text(
                    getattr(turn, "text", None), kind=kind,
                    address_form=address_form))
                self._report("Welcome LLM completed", {
                    "valid_text": bool(result[0]), "expired": expired.is_set()})
            except Exception as exc:
                self._report("SALM Welcome Dialogue lỗi", {
                    "error": type(exc).__name__}, level="WARNING")
            finally:
                with self._lock:
                    self._pending = False
                completed.set()

        try:
            threading.Thread(
                target=classify, name="salm-welcome-llm", daemon=True).start()
        except RuntimeError:
            with self._lock:
                self._pending = False
            self._report("SALM Welcome Dialogue không khởi chạy được, dùng fallback.",
                         level="WARNING")
            return self._fallback(kind, self._address_form())
        if not completed.wait(self.timeout_seconds):
            expired.set()
            self._report("SALM Welcome Dialogue quá deadline, dùng câu fallback.",
                         level="WARNING")
            return self._fallback(kind, self._address_form())
        current_address = self._address_form()
        if current_address != address_form:
            return self._fallback(kind, current_address)
        return result[0] if result and result[0] else fallback

    def _fallback(self, kind, address_form):
        if self.proactive_text_provider is not None:
            try:
                candidate = self.proactive_text_provider(
                    kind, address_form=address_form)
                cleaned = clean_welcome_text(
                    candidate, kind=kind, address_form=address_form)
                if cleaned:
                    return cleaned
            except Exception as exc:
                self._report("SALM không đọc được greeting fallback persona", {
                    "error": type(exc).__name__}, level="WARNING")
        return welcome_fallback(kind, address_form)

    def _address_form(self):
        try:
            value = (self.address_form_provider()
                     if self.address_form_provider is not None else None)
        except Exception as exc:
            self._report("SALM không đọc được cách xưng hô", {
                "error": type(exc).__name__}, level="WARNING")
            value = None
        return safe_address_form(value)


@dataclass(frozen=True)
class ReturnEvent:
    at: datetime
    absence_seconds: float
    origin: str

    def to_record(self):
        return {
            "kind": "return_detected",
            "at": self.at.isoformat(),
            "absence_seconds": round(max(0.0, self.absence_seconds), 3),
            "origin": self.origin,
        }


class ReturnWelcomeTracker:
    """Chào một lần sau absence xác nhận; bỏ qua pause ngắn/idle mơ hồ."""

    def __init__(self, min_absence=WELCOME_BACK_MIN_SECONDS,
                 cooldown=WELCOME_BACK_COOLDOWN_SECONDS):
        self.min_absence = max(0.0, float(min_absence))
        self.cooldown = max(0.0, float(cooldown))
        self._absence_since = None
        self._origin = None
        self._last_welcome_at = None

    def observe(self, state, now, wall_time):
        now = float(now)
        if state.presence in (Presence.AWAY, Presence.SUSPENDED):
            if self._absence_since is None:
                # Với AWAY do idle 10 phút, reducer giữ since ở đầu idle gap. Nhờ đó
                # không phải chờ thêm 2 phút sau khi vừa đủ confidence AWAY.
                self._absence_since = min(now, float(state.since_monotonic))
                self._origin = state.presence.value
            elif state.presence == Presence.SUSPENDED:
                self._origin = Presence.SUSPENDED.value
            return None

        if self._absence_since is None or state.presence != Presence.PRESENT:
            # UNKNOWN ngay sau resume giữ phiên absence mở cho tới input thật đầu tiên.
            return None

        duration = max(0.0, now - self._absence_since)
        origin = self._origin or Presence.AWAY.value
        self._absence_since = None
        self._origin = None
        if duration < self.min_absence:
            return None
        if (self._last_welcome_at is not None
                and now - self._last_welcome_at < self.cooldown):
            return None
        self._last_welcome_at = now
        return ReturnEvent(wall_time, duration, origin)
