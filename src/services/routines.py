"""RoutineStore — quy trình (routine) có tên: gói nhiều BƯỚC (câu lệnh tiếng Việt) chạy
tuần tự. Local, bền vững, không thread (nhái mẫu store khác).

Bước lưu dạng CÂU LỆNH tự nhiên (vd "mở chrome", "đọc thời tiết"); việc CHẠY routine do
app.py lo (đưa từng bước qua _dispatch — tái dùng fast-path + agent). Tên khớp bỏ dấu.
"""

import json
import os
from datetime import datetime

from utils.atomic_json import write_json
from utils.logger import get_logger
from utils.text_norm import strip_accents

logger = get_logger(__name__)

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "routines.json")


def _key(name):
    return strip_accents((name or "").strip().lower())


class RoutineStore:
    def __init__(self, path=None):
        self.path = path or _DEFAULT_PATH
        self._routines = {}       # key(tên bỏ dấu) -> {"name","steps","created_at"}
        self._load()

    def create(self, name, steps):
        """Tạo/ghi đè routine. Trả routine (kèm 'replaced'), hoặc None nếu tên/steps rỗng."""
        name = (name or "").strip()
        steps = [s.strip() for s in (steps or []) if s and s.strip()]
        if not name or not steps:
            return None
        k = _key(name)
        replaced = k in self._routines
        self._routines[k] = {"name": name, "steps": steps,
                             "created_at": datetime.now().isoformat()}
        self._save()
        out = dict(self._routines[k]); out["replaced"] = replaced
        return out

    def get(self, name):
        return self._routines.get(_key(name))

    def list(self):
        return sorted(self._routines.values(), key=lambda r: r["name"])

    def delete(self, name):
        removed = self._routines.pop(_key(name), None) is not None
        if removed:
            self._save()
        return removed

    # ------------------------- lưu / nạp ------------------------- #
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._routines = {_key(r["name"]): r for r in data}
        except (OSError, ValueError, KeyError) as e:
            logger.warning("Không đọc được file routine: %s", e)

    def _save(self):
        try:
            write_json(self.path, list(self._routines.values()))
        except OSError as e:
            logger.error("Không lưu được file routine: %s", e)
