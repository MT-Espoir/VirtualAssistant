"""Kho dữ liệu cục bộ SALM với schema hẹp và TTL cuốn chiếu 14 ngày."""

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


TTL_DAYS = 14
_FORBIDDEN_KEYS = {"url", "title", "window_title", "tab_id", "keys", "clipboard",
                   "command_line", "peak", "raw_peak"}


def _assert_private(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"Trường riêng tư bị cấm trong SALM: {key}")
            _assert_private(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_private(child)


class SalmStorage:
    def __init__(self, directory, ttl_days=TTL_DAYS):
        self.directory = Path(directory)
        self.ttl_days = max(1, int(ttl_days))
        self._lock = threading.RLock()

    def append(self, record):
        _assert_private(record)
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            raw_at = record.get("at") or record.get("end") or record.get("start")
            try:
                day = (datetime.fromisoformat(raw_at).date()
                       if raw_at else datetime.now().date())
            except (TypeError, ValueError):
                day = datetime.now().date()
            path = self.directory / f"events-{day.isoformat()}.jsonl"
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False,
                                        separators=(",", ":")) + "\n")

    def write_daily(self, daily):
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            for day, metrics in daily.items():
                payload = {"schema_version": 1, "day": day,
                           "metrics": metrics.to_dict()}
                _assert_private(payload)
                path = self.directory / f"daily-{day}.json"
                temp = path.with_suffix(".json.tmp")
                temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
                os.replace(temp, path)

    def purge_expired(self, now=None):
        """Chỉ xóa file SALM đúng pattern trong chính data dir; không đệ quy."""
        if not self.directory.exists():
            return []
        now = now or datetime.now(timezone.utc)
        cutoff = now.date() - timedelta(days=self.ttl_days)
        removed = []
        for pattern, prefix, suffix in (("events-*.jsonl", "events-", ".jsonl"),
                                        ("daily-*.json", "daily-", ".json")):
            for path in self.directory.glob(pattern):
                raw_day = path.name[len(prefix):-len(suffix)]
                try:
                    day = datetime.strptime(raw_day, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if day < cutoff:
                    path.unlink()
                    removed.append(path)
        return removed
