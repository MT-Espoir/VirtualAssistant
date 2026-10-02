"""SALM-1 gentle check-in: câu thoại tất định và cửa sổ nhận snooze.

Module không biết TTS, UI hay LLM. Nó chỉ chọn template từ reason tối thiểu và giữ một
cửa sổ phản hồi ngắn, thread-safe, để app nhận lệnh hoãn bằng giọng nối.
"""

import threading
from dataclasses import dataclass, replace

from utils.text_norm import norm


_WORK_CHECKIN_TEMPLATE = (
    "Mạch việc đang chạy rất mượt. Mình thả lỏng vai và tay một chút rồi xử lý tiếp nhé?"
)
_SCREEN_SOFT_CHECKIN_TEMPLATE = (
    "Mắt mình theo màn hình một lúc rồi. {address_form} nhìn xa và chớp mắt chậm vài nhịp nhé?"
)
_SCREEN_HARD_CHECKIN_TEMPLATE = (
    "Mình rời màn hình và đi lại một chút nhé {address_form}. "
    "Phần còn lại đợi mình quay lại cũng được."
)
WORK_CHECKIN_TEXT = _WORK_CHECKIN_TEMPLATE
SCREEN_SOFT_CHECKIN_TEXT = _SCREEN_SOFT_CHECKIN_TEMPLATE.format(address_form="Anh")
SCREEN_HARD_CHECKIN_TEXT = _SCREEN_HARD_CHECKIN_TEMPLATE.format(address_form="anh")
SNOOZE_REPLY_TEXT = (
    "Được rồi, thêm 10 phút để chốt nốt đoạn này nhé. Đừng mải mê quá đấy!"
)
CHECKIN_RESPONSE_SECONDS = 10.0

_SNOOZE_EXACT = {
    "hoan",
    "hoan lai",
    "10 phut nua",
    "muoi phut nua",
    "lat nua",
    "lat nua nhe",
    "chua nghi",
}
_SNOOZE_PHRASES = (
    "de anh chot not",
    "de toi chot not",
    "cho anh chot not",
    "cho toi chot not",
    "chot not da",
)
_RESUME_EXACT = {
    "nhac nghi lai di",
    "bat lai nhac nghi",
    "tiep tuc nhac nghi",
    "nhac toi nghi lai",
}


def checkin_text(clock, level, address_form="anh"):
    """Chọn câu đã duyệt; không đưa timeline/app name vào lời nói."""
    # Validation đầy đủ nằm ở composition/language lane; ở đây chỉ chống format injection.
    if not isinstance(address_form, str) or not address_form.strip():
        address_form = "anh"
    address_form = " ".join(address_form.split())
    if clock == "screen_exposure":
        template = (_SCREEN_HARD_CHECKIN_TEMPLATE if level == "hard"
                    else _SCREEN_SOFT_CHECKIN_TEMPLATE)
        spoken_address = (address_form if level == "hard" else
                          address_form[0].upper() + address_form[1:])
        return template.format(address_form=spoken_address)
    return _WORK_CHECKIN_TEMPLATE


def match_snooze(text):
    """Nhận một ý hoãn rõ ràng; không tham để tránh cướp yêu cầu bình thường."""
    value = norm(text)
    return bool(value and (value in _SNOOZE_EXACT
                           or any(phrase in value for phrase in _SNOOZE_PHRASES)))


def match_resume_care(text):
    """Đường thoát DND tất định, cố ý hẹp để không cướp lệnh bình thường."""
    return norm(text) in _RESUME_EXACT


@dataclass(frozen=True)
class CheckInSession:
    candidate_id: str
    clock: str
    level: str
    cycle_id: int
    deadline: float
    work_cycle_id: int = None
    clarifications: int = 0


class CheckInResponseWindow:
    """Giữ tối đa một check-in đang chờ phản hồi; không tạo backlog."""

    def __init__(self, window_seconds=CHECKIN_RESPONSE_SECONDS):
        self.window_seconds = max(0.0, float(window_seconds))
        self._session = None
        self._lock = threading.Lock()

    def arm(self, decision, cycle_id, now, work_cycle_id=None):
        session = CheckInSession(
            candidate_id=decision.candidate_id,
            clock=decision.clock,
            level=decision.level,
            cycle_id=int(cycle_id),
            deadline=float(now) + self.window_seconds,
            work_cycle_id=(int(cycle_id) if work_cycle_id is None
                           else int(work_cycle_id)),
        )
        with self._lock:
            self._session = session
        return session

    def take_snooze(self, text, now):
        """Trả session đúng một lần nếu lệnh rõ và còn trong cửa sổ."""
        with self._lock:
            session = self._session
            if session is None:
                return None
            if float(now) > session.deadline:
                self._session = None
                return None
            if not match_snooze(text):
                return None
            self._session = None
            return session

    def close(self, candidate_id=None):
        with self._lock:
            if (self._session is not None
                    and (candidate_id is None
                         or self._session.candidate_id == candidate_id)):
                self._session = None

    def extend_for_clarification(self, candidate_id, now, seconds=20.0):
        """Cho đúng một lượt làm rõ; không tạo vòng hỏi vô hạn."""
        with self._lock:
            session = self._session
            if session is None or session.candidate_id != candidate_id:
                return False
            if session.clarifications >= 1:
                self._session = None
                return False
            self._session = replace(
                session, deadline=float(now) + max(0.0, float(seconds)),
                clarifications=session.clarifications + 1)
            return True

    def active(self, now):
        with self._lock:
            session = self._session
            if session is not None and float(now) > session.deadline:
                self._session = None
                return None
            return session
