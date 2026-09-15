"""Cổng an toàn và dispatcher duy nhất cho output chủ động.

Direct reply do người dùng khởi xướng không đi qua module này. Producer chủ động chỉ
nộp callback; dispatcher kiểm gate lúc nhận và ngay trước khi thực thi.
"""

import queue
import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Optional, Tuple

from features.salm.models import ActivityKind, Confidence, DisplayState, Presence
from utils.logger import get_logger

logger = get_logger(__name__)

MEETING_DND_EXIT_GRACE = 10.0
POST_DND_GRACE = 30.0


@dataclass(frozen=True)
class GateSnapshot:
    salm_enabled: bool = True
    work_mode: bool = False
    meeting_open: bool = False
    meeting_signal: Optional[bool] = None
    assistant_busy: bool = False
    presence: Presence = Presence.UNKNOWN
    display: DisplayState = DisplayState.UNKNOWN
    activity: ActivityKind = ActivityKind.NONE
    confidence: Confidence = Confidence.LOW
    session_locked: bool = False
    foreground_fullscreen: bool = False
    post_dnd_until: float = 0.0
    user_care_dnd: bool = False


class InterventionGate:
    def __init__(self, salm_enabled=True, meeting_exit_grace=MEETING_DND_EXIT_GRACE,
                 post_dnd_grace=POST_DND_GRACE):
        self.meeting_exit_grace = float(meeting_exit_grace)
        self.post_dnd_grace = float(post_dnd_grace)
        self._snapshot = GateSnapshot(salm_enabled=bool(salm_enabled))
        self._meeting_false_since = None
        self._lock = threading.RLock()
        self._listeners = []

    def subscribe(self, callback):
        with self._lock:
            self._listeners.append(callback)

    def snapshot(self):
        with self._lock:
            return self._snapshot

    def _commit(self, **changes):
        with self._lock:
            updated = replace(self._snapshot, **changes)
            if updated == self._snapshot:
                return updated
            self._snapshot = updated
            listeners = tuple(self._listeners)
        for callback in listeners:
            try:
                callback(updated)
            except Exception:
                logger.debug("InterventionGate listener lỗi", exc_info=True)
        return updated

    def set_salm_enabled(self, enabled):
        return self._commit(salm_enabled=bool(enabled))

    def set_work_mode(self, enabled):
        return self._commit(work_mode=bool(enabled))

    def set_assistant_state(self, state):
        return self._commit(assistant_busy=state in ("thinking", "speaking"))

    def set_user_care_dnd(self, enabled):
        """Chỉ chặn Break Care; các producer global/direct reply vẫn hoạt động."""
        return self._commit(user_care_dnd=bool(enabled))

    def update_activity(self, snapshot, state, now=None):
        now = time.monotonic() if now is None else float(now)
        meeting = snapshot.meeting_open
        current = self.snapshot()
        meeting_open = current.meeting_open
        post_until = current.post_dnd_until

        if meeting is True:
            meeting_open = True
            self._meeting_false_since = None
            post_until = 0.0
        elif meeting is False:
            if meeting_open:
                if self._meeting_false_since is None:
                    self._meeting_false_since = now
                elif now - self._meeting_false_since >= self.meeting_exit_grace:
                    meeting_open = False
                    self._meeting_false_since = None
                    post_until = now + self.post_dnd_grace
            else:
                self._meeting_false_since = None
        # UNKNOWN không được tự tắt một DND đang active do bridge vừa rớt.

        return self._commit(
            meeting_open=meeting_open,
            meeting_signal=meeting,
            presence=state.presence,
            display=state.display,
            activity=state.activity,
            confidence=state.confidence,
            session_locked=snapshot.session_locked is True,
            foreground_fullscreen=bool(snapshot.foreground_fullscreen),
            post_dnd_until=post_until,
        )

    def reasons(self, scope="global", now=None, snapshot=None):
        now = time.monotonic() if now is None else float(now)
        value = snapshot or self.snapshot()
        reasons = []
        if value.work_mode:
            reasons.append("work_mode")
        if value.meeting_open:
            reasons.append("meeting_open")
        if value.assistant_busy:
            reasons.append("assistant_busy")

        if scope == "break_care":
            if not value.salm_enabled:
                reasons.append("salm_disabled")
            if value.presence == Presence.AWAY:
                reasons.append("away")
            elif value.presence == Presence.SUSPENDED:
                reasons.append("suspended")
            elif value.presence == Presence.UNKNOWN:
                reasons.append("presence_unknown")
            if value.session_locked:
                reasons.append("locked")
            if value.display == DisplayState.OFF:
                reasons.append("display_off")
            elif value.display == DisplayState.UNKNOWN:
                reasons.append("display_unknown")
            if value.foreground_fullscreen:
                reasons.append("foreground_fullscreen")
            if value.activity == ActivityKind.PASSIVE_VIEWING:
                reasons.append("passive_viewing")
            if now < value.post_dnd_until:
                reasons.append("post_dnd_grace")
            if value.user_care_dnd:
                reasons.append("user_care_dnd")
        return tuple(reasons)


@dataclass(frozen=True)
class Intervention:
    kind: str
    present: Callable[[], None]
    cancel: Optional[Callable[[], None]] = None
    on_drop: Optional[Callable[[], None]] = None
    scope: str = "global"
    active_seconds: float = 0.0
    token: str = ""

    def __post_init__(self):
        if not self.token:
            object.__setattr__(self, "token", uuid.uuid4().hex)


class ProactiveDispatcher:
    def __init__(self, gate, poll_seconds=0.05):
        self.gate = gate
        self.poll_seconds = max(0.01, float(poll_seconds))
        self._queue = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self._active = None
        self._active_cancelled = False
        self._lock = threading.Lock()
        gate.subscribe(self._on_gate_changed)

    def start(self):
        if self._thread is not None:
            return False
        self._thread = threading.Thread(target=self._run, name="proactive-dispatcher",
                                        daemon=True)
        self._thread.start()
        return True

    def submit(self, intervention):
        if self._stop.is_set():
            self._drop(intervention)
            return False
        if self.gate.reasons(intervention.scope):
            return False
        self._queue.put(intervention)
        return True

    def stop(self):
        self._stop.set()
        self._cancel_active()
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                self._drop(item)
        self._queue.put(None)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def _on_gate_changed(self, snapshot):
        with self._lock:
            active = self._active
        if active is not None and self.gate.reasons(active.scope, snapshot=snapshot):
            self._cancel(active)
        retained = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                if self.gate.reasons(item.scope, snapshot=snapshot):
                    self._drop(item)
                else:
                    retained.append(item)
        for item in retained:
            self._queue.put(item)

    def _cancel(self, intervention):
        with self._lock:
            if self._active is intervention:
                if self._active_cancelled:
                    return
                self._active_cancelled = True
        if intervention.cancel:
            try:
                intervention.cancel()
            except Exception:
                logger.debug("Không cancel gọn được intervention %s", intervention.kind,
                             exc_info=True)

    @staticmethod
    def _drop(intervention):
        if intervention.on_drop:
            try:
                intervention.on_drop()
            except Exception:
                logger.debug("Không drop gọn được intervention %s", intervention.kind,
                             exc_info=True)

    def _cancel_active(self):
        with self._lock:
            active = self._active
        if active is not None:
            self._cancel(active)

    def _run(self):
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                break
            if self.gate.reasons(item.scope):
                self._drop(item)
                continue
            with self._lock:
                self._active = item
                self._active_cancelled = False
            try:
                # Kiểm lần hai sát biên output, sau khi item đã rời queue.
                if self.gate.reasons(item.scope):
                    self._drop(item)
                    continue
                item.present()
                deadline = time.monotonic() + max(0.0, item.active_seconds)
                while not self._stop.is_set() and time.monotonic() < deadline:
                    if self.gate.reasons(item.scope):
                        self._cancel(item)
                        break
                    self._stop.wait(min(self.poll_seconds,
                                        max(0.0, deadline - time.monotonic())))
            except Exception:
                logger.warning("Proactive intervention '%s' lỗi", item.kind, exc_info=True)
            finally:
                with self._lock:
                    if self._active is item:
                        self._active = None
                        self._active_cancelled = False
