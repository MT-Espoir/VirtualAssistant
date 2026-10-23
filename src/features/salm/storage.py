"""Kho SALM: SQLite primary, file legacy/fallback, retention tách theo độ chi tiết."""

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from features.salm.app_identity import sanitize_legacy_daily_metrics
from utils.logger import get_logger


TTL_DAYS = 14
DAILY_TTL_DAYS = 90
_FORBIDDEN_KEYS = {"url", "title", "window_title", "tab_id", "keys", "clipboard",
                   "command_line", "peak", "raw_peak"}
_DAILY_FIELDS = ("work_engagement", "screen_exposure", "unknown_duration",
                 "idle_gap", "confirmed_break")
_APP_FIELDS = ("running", "foreground", "interactive", "passive_viewing",
               "background_audio")

logger = get_logger(__name__)


def _assert_private(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"Trường riêng tư bị cấm trong SALM: {key}")
            _assert_private(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_private(child)


def _merge_metrics(base, current):
    """Add a runtime projection to the fixed snapshot loaded when storage starts."""
    base = base or {}
    current = current or {}
    merged = {
        field: round(float(base.get(field) or 0) + float(current.get(field) or 0), 3)
        for field in _DAILY_FIELDS
    }
    apps = {}
    for app_id in set(base.get("apps") or {}) | set(current.get("apps") or {}):
        old = (base.get("apps") or {}).get(app_id) or {}
        new = (current.get("apps") or {}).get(app_id) or {}
        apps[app_id] = {
            field: round(float(old.get(field) or 0) + float(new.get(field) or 0), 3)
            for field in _APP_FIELDS
        }
    merged["apps"] = dict(sorted(apps.items()))
    old_circadian = base.get("circadian") or {}
    new_circadian = current.get("circadian") or {}
    old_buckets = list(old_circadian.get("interactive_seconds_by_half_hour") or [])
    new_buckets = list(new_circadian.get("interactive_seconds_by_half_hour") or [])
    old_buckets = (old_buckets + [0.0] * 48)[:48]
    new_buckets = (new_buckets + [0.0] * 48)[:48]
    old_offset = old_circadian.get("timezone_offset_minutes")
    new_offset = new_circadian.get("timezone_offset_minutes")
    offsets_disagree = (old_offset is not None and new_offset is not None
                        and old_offset != new_offset)
    merged["circadian"] = {
        "schema_version": 1,
        "coverage_seconds": round(
            float(old_circadian.get("coverage_seconds") or 0)
            + float(new_circadian.get("coverage_seconds") or 0), 3),
        "interactive_seconds_by_half_hour": [
            round(float(old_buckets[index] or 0)
                  + float(new_buckets[index] or 0), 3)
            for index in range(48)
        ],
        "timezone_offset_minutes": (
            old_offset if new_offset is None else new_offset
            if old_offset is None or old_offset == new_offset else None),
        "timezone_changed": bool(
            old_circadian.get("timezone_changed")
            or new_circadian.get("timezone_changed") or offsets_disagree),
    }
    return merged


class SalmStorage:
    def __init__(self, directory, ttl_days=TTL_DAYS, daily_ttl_days=DAILY_TTL_DAYS,
                 database=None,
                 import_legacy=True, recording=True):
        self.recording = bool(recording)
        self.directory = Path(directory)
        self.ttl_days = max(1, int(ttl_days))
        self.daily_ttl_days = max(self.ttl_days, int(daily_ttl_days))
        self.database = database
        self._lock = threading.RLock()
        self._daily_base = {}
        if self.recording and self.database is not None and import_legacy:
            try:
                self.database.import_salm_directory(
                    self.directory, validator=_assert_private,
                    daily_transform=sanitize_legacy_daily_metrics)
            except Exception as exc:
                logger.warning("Không import được SALM legacy vào SQLite: %s", exc)

    def append(self, record):
        if not self.recording:
            return
        _assert_private(record)
        with self._lock:
            if self.database is not None:
                try:
                    self.database.record_salm_event(record)
                    return
                except Exception as exc:
                    logger.warning("SQLite SALM lỗi; fallback JSONL: %s", exc)
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
        if not self.recording:
            return
        with self._lock:
            for day, metrics in daily.items():
                payload = {"schema_version": 3, "day": day,
                           "metrics": metrics.to_dict()}
                _assert_private(payload)
                if self.database is not None:
                    try:
                        if day not in self._daily_base:
                            existing = self.database.salm_daily(day)
                            self._daily_base[day] = (
                                existing.get("metrics") if existing is not None else {})
                        combined = _merge_metrics(
                            self._daily_base[day], payload["metrics"])
                        self.database.replace_salm_daily(
                            day, combined, schema_version=payload["schema_version"])
                        continue
                    except Exception as exc:
                        logger.warning("SQLite SALM daily lỗi; fallback JSON: %s", exc)
                self.directory.mkdir(parents=True, exist_ok=True)
                path = self.directory / f"daily-{day}.json"
                temp = path.with_suffix(".json.tmp")
                temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
                os.replace(temp, path)

    def purge_expired(self, now=None):
        """Purge only when recording is enabled; restricted runtime preserves legacy."""
        if not self.recording:
            return
        now = now or datetime.now(timezone.utc)
        event_cutoff = now.date() - timedelta(days=self.ttl_days)
        daily_cutoff = now.date() - timedelta(days=self.daily_ttl_days)
        removed = []
        if self.directory.exists():
            patterns = (
                ("events-*.jsonl", "events-", ".jsonl", event_cutoff),
                ("daily-*.json", "daily-", ".json", daily_cutoff),
            )
            for pattern, prefix, suffix, cutoff in patterns:
                for path in self.directory.glob(pattern):
                    raw_day = path.name[len(prefix):-len(suffix)]
                    try:
                        day = datetime.strptime(raw_day, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if day < cutoff:
                        path.unlink()
                        removed.append(path)
        if self.database is not None:
            try:
                self.database.purge_salm_events_before(event_cutoff.isoformat())
                self.database.purge_salm_daily_before(daily_cutoff.isoformat())
            except Exception as exc:
                logger.warning("Không purge được SALM trong SQLite: %s", exc)
        return removed

    def clear_history(self):
        """Xoá raw/daily ở cả SQLite lẫn fallback files; lỗi phải nổi lên cho UI báo."""
        with self._lock:
            result = {"events": 0, "daily": 0, "files": 0}
            if self.database is not None:
                removed = self.database.clear_salm_activity()
                result.update(removed)
            if self.directory.exists():
                for pattern in ("events-*.jsonl", "daily-*.json"):
                    for path in self.directory.glob(pattern):
                        path.unlink()
                        result["files"] += 1
            self._daily_base.clear()
            return result
