"""Consumer presence nhỏ của SALM: nhận diện một lần quay lại đáng để chào.

Không phát UI/TTS và không suy diễn tâm lý. Tracker chỉ biến chuỗi presence thành một
ReturnEvent trung tính; app nộp lời chào qua ProactiveDispatcher.
"""

from dataclasses import dataclass
from datetime import datetime

from features.salm.models import Presence


WELCOME_BACK_MIN_SECONDS = 2 * 60.0
# Chỉ chống hai transition rung sát nhau; một lần rời máy thật kế tiếp vẫn được chào.
WELCOME_BACK_COOLDOWN_SECONDS = 5 * 60.0

STARTUP_GREETING_TEXT = (
    "Chào anh, tôi đã sẵn sàng rồi. Hôm nay mình cùng làm việc thật thoải mái nhé.")
WELCOME_BACK_GREETING_TEXT = (
    "Anh quay lại rồi à? Mừng anh trở lại. Mình tiếp tục nhé.")


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
