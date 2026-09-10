"""
ReminderScheduler — lịch nhắc việc chạy nền trong tiến trình (desktop app).

Đặt/nhắc/hủy nhắc; lưu ra file JSON để sống qua restart. Một thread nền định kỳ
kiểm tra task tới hạn và gọi callback `notify(message)` (main.py nối vào loa/print).

Tách logic thuần (add/cancel/due/persist) khỏi thread để unit test dễ:
`due(now)` là hàm thuần theo mốc thời gian truyền vào.
"""

import json
import os
import threading
import uuid
from datetime import datetime

from utils.atomic_json import write_json
from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_STORE = os.path.join(os.path.dirname(__file__), "reminders.json")


class ReminderScheduler:
    def __init__(self, notify=None, store_path=None, poll_interval=5):
        # notify(message, kind): kind = "remind" (đọc nhắc) | "do" (thực thi lệnh theo lịch).
        self.notify = notify or (lambda msg, kind="remind": logger.info("🔔 Nhắc: %s", msg))
        self.store_path = store_path or _DEFAULT_STORE
        self.poll_interval = poll_interval
        self._tasks = {}                 # id -> {"id","message","fire_at"(iso)}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._load()

    # ------------------------- thao tác dữ liệu ------------------------- #
    def add(self, message: str, fire_at: datetime, kind: str = "remind") -> dict:
        task = {"id": uuid.uuid4().hex[:6], "message": message,
                "fire_at": fire_at.isoformat(), "kind": kind}
        with self._lock:
            self._tasks[task["id"]] = task
            self._save()
        logger.info("Đặt nhắc %s lúc %s: %s", task["id"], task["fire_at"], message)
        return task

    def list(self) -> list:
        with self._lock:
            return sorted(self._tasks.values(), key=lambda t: t["fire_at"])

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            removed = self._tasks.pop(task_id, None) is not None
            if removed:
                self._save()
        return removed

    def due(self, now: datetime) -> list:
        """Các task đã tới hạn (fire_at <= now). Hàm thuần, không đụng thread."""
        with self._lock:
            return [t for t in self._tasks.values()
                    if datetime.fromisoformat(t["fire_at"]) <= now]

    # ------------------------- vòng chạy nền ------------------------- #
    def _fire_due(self):
        for task in self.due(datetime.now()):
            try:
                self.notify(task["message"], task.get("kind", "remind"))
            except Exception as e:  # notify lỗi không được làm chết scheduler
                logger.error("Lỗi khi nhắc: %s", e)
            self.cancel(task["id"])

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        # _stop.wait trả True khi được stop, False khi hết timeout -> lặp
        while not self._stop.wait(self.poll_interval):
            try:
                self._fire_due()
            except Exception as e:
                logger.error("Lỗi vòng scheduler: %s", e)

    # ------------------------- lưu / nạp ------------------------- #
    def _load(self):
        if not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._tasks = {t["id"]: t for t in data}
        except (OSError, ValueError, KeyError) as e:
            logger.warning("Không đọc được file nhắc việc: %s", e)

    def _save(self):
        try:
            write_json(self.store_path, list(self._tasks.values()))
        except OSError as e:
            logger.error("Không lưu được file nhắc việc: %s", e)
