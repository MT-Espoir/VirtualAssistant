"""Preference SALM-2 được học tường minh, có biên và có thể xoá hoàn toàn.

Kho này cố ý không nhận raw utterance, activity, app hay threshold sức khoẻ. Cách gọi
thực tế vẫn thuộc ``UserProfile``; SALM chỉ giữ tần suất dùng cách gọi đó.
"""

import json
import os
import threading
from pathlib import Path

from utils.atomic_json import write_json
from utils.logger import get_logger
from utils.text_norm import norm

logger = get_logger(__name__)

DEFAULT_CARE_STYLE = {
    "length": "balanced",
    "directness": "balanced",
    "variation": "balanced",
    "address_frequency": "balanced",
}
CARE_STYLE_VALUES = {
    "length": frozenset(("concise", "balanced")),
    "directness": frozenset(("gentle", "balanced", "direct")),
    "variation": frozenset(("low", "balanced", "high")),
    "address_frequency": frozenset(("sparse", "balanced", "frequent")),
}

_SCOPE = ("nhac nghi", "loi nhac nghi", "break care", "salm")
_SHOW = ("xem", "hien", "cai dat", "tuy chinh")
_RESET = ("dat lai", "mac dinh", "reset", "xoa tuy chinh")


def _has_any(text, phrases):
    return any(phrase in text for phrase in phrases)


def match_care_style_command(text):
    """Parse lệnh có phạm vi SALM rõ ràng; câu chung chung luôn trả ``None``.

    Cho phép đổi nhiều trường trong một câu. Mâu thuẫn trong cùng một trường fail
    closed để Agent hỏi lại thay vì tự chọn một ý.
    """
    value = " ".join(norm(text or "").split())
    if not value or not _has_any(value, _SCOPE):
        return None
    if _has_any(value, _RESET):
        return {"action": "reset", "changes": {}}

    rules = {
        "length": {
            "concise": ("ngan hon", "gon hon", "ngan gon hon", "suc tich hon"),
            "balanced": ("chi tiet hon", "dai hon", "do dai can bang"),
        },
        "directness": {
            "gentle": ("nhe nhang hon", "mem hon", "diu hon"),
            "balanced": ("muc truc tiep can bang", "truc tiep vua phai"),
            "direct": ("truc tiep hon", "noi thang hon"),
        },
        "variation": {
            "low": ("it thay doi", "it bien tau", "on dinh hon"),
            "balanced": ("do da dang can bang", "bien tau vua phai"),
            "high": ("da dang hon", "doi cach noi nhieu hon", "bot lap"),
        },
        "address_frequency": {
            "sparse": ("it goi toi", "dung goi toi moi cau", "it xung ho"),
            "balanced": ("xung ho vua phai", "tan suat xung ho can bang"),
            "frequent": ("goi toi thuong xuyen hon", "xung ho thuong xuyen hon"),
        },
    }
    changes = {}
    for field, options in rules.items():
        hits = [choice for choice, phrases in options.items()
                if _has_any(value, phrases)]
        if len(hits) > 1:
            return None
        if hits:
            changes[field] = hits[0]
    if changes:
        return {"action": "update", "changes": changes}
    if _has_any(value, _SHOW):
        return {"action": "show", "changes": {}}
    return None


class CareStyleStore:
    """Kho enum nhỏ, thread-safe, ghi nguyên tử và fail closed khi file sai schema."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self._lock = threading.RLock()
        self._values = dict(DEFAULT_CARE_STYLE)
        self._load()

    def snapshot(self):
        with self._lock:
            return dict(self._values)

    def update(self, changes):
        clean = self._validated(changes, partial=True)
        if clean is None or not clean:
            return False
        with self._lock:
            self._values.update(clean)
            self._save()
        return True

    def reset(self):
        with self._lock:
            self._values = dict(DEFAULT_CARE_STYLE)
            if self.path and self.path.exists():
                try:
                    os.remove(self.path)
                except OSError:
                    logger.warning("SALM không xoá được care style", exc_info=True)
                    self._save()
        return self.snapshot()

    def _validated(self, data, partial=False):
        if not isinstance(data, dict):
            return None
        allowed = set(CARE_STYLE_VALUES)
        if any(key not in allowed for key in data):
            return None
        if not partial and set(data) != allowed:
            return None
        clean = {}
        for key, value in data.items():
            if value not in CARE_STYLE_VALUES[key]:
                return None
            clean[key] = value
        return clean

    def _load(self):
        if not self.path or not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                clean = self._validated(json.load(handle))
            if clean is None:
                raise ValueError("schema care style không hợp lệ")
            self._values = clean
        except (OSError, ValueError, json.JSONDecodeError):
            logger.warning("SALM bỏ qua care style hỏng; dùng mặc định", exc_info=True)
            self._values = dict(DEFAULT_CARE_STYLE)

    def _save(self):
        if self.path:
            write_json(str(self.path), dict(self._values))


def style_confirmation(changes, reset=False):
    if reset:
        return "Em đã đưa phong cách nhắc nghỉ về mặc định."
    labels = {
        ("length", "concise"): "ngắn gọn hơn",
        ("length", "balanced"): "độ dài cân bằng",
        ("directness", "gentle"): "nhẹ nhàng hơn",
        ("directness", "balanced"): "trực tiếp vừa phải",
        ("directness", "direct"): "trực tiếp hơn",
        ("variation", "low"): "ổn định hơn",
        ("variation", "balanced"): "biến tấu vừa phải",
        ("variation", "high"): "đa dạng hơn",
        ("address_frequency", "sparse"): "ít gọi cách xưng hô hơn",
        ("address_frequency", "balanced"): "xưng hô vừa phải",
        ("address_frequency", "frequent"): "gọi cách xưng hô thường xuyên hơn",
    }
    parts = [labels[(field, value)] for field, value in changes.items()]
    return "Em đã chỉnh lời nhắc nghỉ " + ", ".join(parts) + "."
