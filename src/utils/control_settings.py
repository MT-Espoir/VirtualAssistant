"""Persistent user controls shared by the desktop and gateway processes."""

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from utils.atomic_json import write_json


ROOT = Path(__file__).resolve().parents[2]


class ControlSettings:
    def __init__(self, path=None):
        raw = path or os.getenv("ALICE_CONTROL_SETTINGS_PATH", "data/control-settings.json")
        self.path = Path(raw)
        if not self.path.is_absolute():
            self.path = ROOT / self.path
        self._lock = threading.RLock()
        self._stamp = None
        self._values = {}

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("values"), dict):
            raise ValueError("Cấu hình bảng điều khiển không hợp lệ")
        return data["values"]

    def values(self):
        with self._lock:
            try:
                stat = self.path.stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
            except FileNotFoundError:
                stamp = None
            if stamp != self._stamp:
                self._values = self._read()
                self._stamp = stamp
            return dict(self._values)

    def get(self, key, default=None):
        return self.values().get(key, default)

    @contextmanager
    def _writer(self):
        # Serialize read/merge/replace across desktop and gateway, not only threads.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a+b") as stream:
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def update(self, changes):
        with self._lock, self._writer():
            values = self._read()
            values.update(changes)
            write_json(str(self.path), {"version": 1, "values": values})
            self._stamp = None
            return self.values()


controls = ControlSettings()


def override(key, default):
    value = controls.get(key, default)
    # A damaged setting must never turn a boolean feature on accidentally.
    if isinstance(default, bool):
        return value if type(value) is bool else default
    return value
