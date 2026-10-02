"""Durable admission control for camera welcome calls, independent of telemetry."""

import math
import sqlite3
import time
from pathlib import Path


class CameraCallBudget:
    def __init__(self, path, min_interval_seconds=900, max_per_hour=3,
                 max_per_day=12, clock=time.time):
        self.path = Path(path) if path else None
        # Configuration may tighten the initial rollout limits, never enlarge them.
        self.min_interval = max(900.0, float(min_interval_seconds))
        self.max_per_hour = max(0, min(3, int(max_per_hour)))
        self.max_per_day = max(0, min(12, int(max_per_day)))
        self.clock = clock

    def reserve(self, attempt_key):
        """Commit an attempt BEFORE the API call; errors/timeouts never refund it.

        BEGIN IMMEDIATE serializes admission across threads/processes. No camera
        samples, source identifiers, prompts or responses are persisted here.
        """
        if self.path is None:
            return False, {"reason": "budget_unavailable"}
        connection = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(self.path), timeout=0.25)
            connection.execute("PRAGMA synchronous=FULL")
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                now = float(self.clock())
                if not math.isfinite(now) or now <= 0:
                    return False, {"reason": "clock_invalid"}
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS camera_welcome_attempts ("
                    "attempt_key TEXT PRIMARY KEY, started_at REAL NOT NULL)")
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS camera_welcome_clock ("
                    "id INTEGER PRIMARY KEY CHECK(id=1), high_water REAL NOT NULL)")
                row = connection.execute(
                    "SELECT high_water FROM camera_welcome_clock WHERE id=1").fetchone()
                if row and (not math.isfinite(float(row[0])) or now < row[0]):
                    return False, {"reason": "clock_rollback"}
                connection.execute(
                    "INSERT INTO camera_welcome_clock VALUES (1, ?) "
                    "ON CONFLICT(id) DO UPDATE SET high_water=excluded.high_water", (now,))
                connection.execute(
                    "DELETE FROM camera_welcome_attempts WHERE started_at < ?",
                    (now - 86400,))
                duplicate = connection.execute(
                    "SELECT 1 FROM camera_welcome_attempts WHERE attempt_key=?",
                    (attempt_key,)).fetchone()
                if duplicate:
                    return False, {"reason": "duplicate_episode"}
                latest, hourly, daily = connection.execute(
                    "SELECT MAX(started_at), "
                    "COALESCE(SUM(started_at >= ?), 0), COUNT(*) "
                    "FROM camera_welcome_attempts", (now - 3600,)).fetchone()
                usage = {"calls_last_hour": hourly, "calls_last_24h": daily}
                if latest is not None and now - latest < self.min_interval:
                    return False, dict(usage, reason="min_interval",
                                       retry_after_seconds=math.ceil(
                                           self.min_interval - (now - latest)))
                if hourly >= self.max_per_hour:
                    return False, dict(usage, reason="hourly_limit")
                if daily >= self.max_per_day:
                    return False, dict(usage, reason="daily_limit")
                connection.execute(
                    "INSERT INTO camera_welcome_attempts VALUES (?, ?)",
                    (attempt_key, now))
            return True, {"reason": "reserved", "calls_last_hour": hourly + 1,
                          "calls_last_24h": daily + 1}
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            return False, {"reason": "budget_unavailable", "error": type(exc).__name__}
        finally:
            if connection is not None:
                connection.close()
