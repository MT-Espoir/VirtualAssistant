"""TaskStore — việc cần làm (to-do) local, bền vững.

Nhái mẫu ReminderScheduler nhưng KHÔNG có thread/lock (chỉ thao tác từ luồng agent).
Khác reminder (có THỜI ĐIỂM, tự nhắc): task là việc cần làm KHÔNG gắn giờ, người dùng
tự đánh dấu xong. Khớp việc theo id HOẶC chuỗi con trong text (bỏ dấu) để tiện ra lệnh
bằng giọng. Logic thuần (find) tách khỏi I/O để test.
"""

import json
import os
import uuid
from datetime import datetime

from utils.atomic_json import write_json
from utils.logger import get_logger
from utils.text_norm import strip_accents

logger = get_logger(__name__)

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "tasks.json")


class TaskStore:
    def __init__(self, path=None):
        self.path = path or _DEFAULT_PATH
        self._tasks = {}          # id -> {"id","text","done","created_at","due"}
        self._load()

    # ------------------------- thao tác dữ liệu ------------------------- #
    def add(self, text, due=None):
        """Thêm việc. Trả task, hoặc None nếu text rỗng."""
        text = (text or "").strip()
        if not text:
            return None
        task = {"id": uuid.uuid4().hex[:6], "text": text, "done": False,
                "created_at": datetime.now().isoformat(), "due": due or None}
        self._tasks[task["id"]] = task
        self._save()
        return task

    def list(self, include_done=False):
        """Việc theo thứ tự tạo. Mặc định CHỈ việc chưa xong."""
        items = sorted(self._tasks.values(), key=lambda t: t["created_at"])
        return items if include_done else [t for t in items if not t["done"]]

    def find(self, keyword):
        """Mọi task khớp keyword: theo id, hoặc chuỗi con (bỏ dấu) trong text. Hàm THUẦN."""
        raw = (keyword or "").strip()
        key = strip_accents(raw.lower())
        if not key:
            return []
        return [t for t in self._tasks.values()
                if t["id"] == raw or key in strip_accents(t["text"].lower())]

    def get(self, task_id):
        return self._tasks.get(task_id)

    def complete(self, task_id):
        """Đánh dấu xong theo id chính xác. Trả task, hoặc None nếu không có."""
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task["done"] = True
        self._save()
        return task

    def remove(self, task_id):
        """Xoá theo id chính xác. Trả task đã xoá, hoặc None."""
        task = self._tasks.pop(task_id, None)
        if task is not None:
            self._save()
        return task

    # ------------------------- lưu / nạp ------------------------- #
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._tasks = {t["id"]: t for t in data}
        except (OSError, ValueError, KeyError) as e:
            logger.warning("Không đọc được file việc cần làm: %s", e)

    def _save(self):
        try:
            write_json(self.path, list(self._tasks.values()))
        except OSError as e:
            logger.error("Không lưu được file việc cần làm: %s", e)
