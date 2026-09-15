"""State tối thiểu cho User Care DND, chỉ áp dụng scope ``break_care``."""

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from features.salm.models import Presence
from utils.logger import get_logger

logger = get_logger(__name__)

_MODES = frozenset({"timed_dnd", "cycle_dnd", "session_dnd"})


@dataclass(frozen=True)
class CareDndState:
    scope: str
    mode: str
    started_at: str
    deadline: str = None
    cycle_id: int = None
    source_intent: str = "care_dnd"


@dataclass(frozen=True)
class CareDndRefresh:
    active: bool
    released: bool = False
    mode: str = None
    reason: str = None


class UserCareDnd:
    """Thread-safe DND. Chỉ timed DND được persist qua app restart."""

    def __init__(self, path=None, enabled=False):
        self.path = Path(path) if path else None
        self.enabled = bool(enabled)
        self._state = None
        self._lock = threading.RLock()
        if self.enabled:
            self._load()

    @property
    def state(self):
        with self._lock:
            return self._state

    def set_timed(self, started_at, deadline):
        state = CareDndState(
            scope="break_care", mode="timed_dnd",
            started_at=started_at.isoformat(), deadline=deadline.isoformat())
        return self._set(state, persist=True)

    def set_cycle(self, started_at, cycle_id):
        return self._set(CareDndState(
            scope="break_care", mode="cycle_dnd",
            started_at=started_at.isoformat(), cycle_id=int(cycle_id)), persist=False)

    def set_session(self, started_at):
        return self._set(CareDndState(
            scope="break_care", mode="session_dnd",
            started_at=started_at.isoformat()), persist=False)

    def clear(self):
        with self._lock:
            previous = self._state
            self._state = None
            self._remove_file()
            return previous is not None

    def refresh(self, at, cycle_id=None, presence=None):
        """Release theo deadline/cycle/suspend; không tự phát cue khi mở gate."""
        with self._lock:
            state = self._state
            if not self.enabled or state is None:
                return CareDndRefresh(False)
            release = None
            if state.mode == "timed_dnd":
                try:
                    if at >= datetime.fromisoformat(state.deadline):
                        release = "deadline_elapsed"
                except (TypeError, ValueError):
                    release = "invalid_deadline"
            elif state.mode == "cycle_dnd":
                if presence == Presence.SUSPENDED:
                    release = "suspended"
                elif cycle_id is not None and int(cycle_id) != state.cycle_id:
                    release = "work_cycle_reset"
            if release is None:
                return CareDndRefresh(True, mode=state.mode)
            self._state = None
            self._remove_file()
            return CareDndRefresh(False, True, state.mode, release)

    def end_session(self):
        """Cycle/session DND không sống qua app exit; timed DND được giữ lại."""
        with self._lock:
            if self._state is not None and self._state.mode != "timed_dnd":
                self._state = None

    def _set(self, state, persist):
        if not self.enabled or state.mode not in _MODES:
            return False
        with self._lock:
            previous = self._state
            self._state = state
            try:
                if persist:
                    self._write_file(state)
                else:
                    self._remove_file()
            except OSError:
                self._state = previous
                logger.warning("Không persist được User Care DND.", exc_info=True)
                return False
        return True

    def _load(self):
        if self.path is None or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = {"scope", "mode", "started_at", "deadline", "cycle_id",
                       "source_intent"}
            if not isinstance(raw, dict) or set(raw) - allowed:
                raise ValueError("schema")
            state = CareDndState(**raw)
            if (state.scope != "break_care" or state.mode != "timed_dnd"
                    or state.source_intent != "care_dnd" or not state.deadline):
                raise ValueError("state")
            started = datetime.fromisoformat(state.started_at)
            deadline = datetime.fromisoformat(state.deadline)
            if started.tzinfo is None or deadline.tzinfo is None:
                raise ValueError("timezone")
            self._state = state
        except Exception:
            logger.warning("Bỏ User Care DND persist không hợp lệ.")
            self._remove_file()

    def _write_file(self, state):
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        os.replace(temp, self.path)

    def _remove_file(self):
        if self.path is None:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("Không xóa được User Care DND state.", exc_info=True)
