"""Small SQLite store owned by the always-on IoT gateway service."""

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


class IoTStore:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock, self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    home_id TEXT NOT NULL, room_id TEXT NOT NULL,
                    device_id TEXT NOT NULL, metric TEXT NOT NULL,
                    value REAL NOT NULL, unit TEXT NOT NULL,
                    received_at TEXT NOT NULL, quality TEXT NOT NULL,
                    sample INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_iot_measurements_room_time
                    ON measurements(room_id, metric, received_at);
                CREATE TABLE IF NOT EXISTS hourly (
                    home_id TEXT NOT NULL, room_id TEXT NOT NULL,
                    device_id TEXT NOT NULL, metric TEXT NOT NULL,
                    hour TEXT NOT NULL, total REAL NOT NULL,
                    count INTEGER NOT NULL, minimum REAL NOT NULL,
                    maximum REAL NOT NULL,
                    PRIMARY KEY(device_id, metric, hour)
                );
                CREATE INDEX IF NOT EXISTS idx_iot_hourly_room_time
                    ON hourly(room_id, metric, hour);
                CREATE TABLE IF NOT EXISTS device_state (
                    device_id TEXT PRIMARY KEY, availability TEXT NOT NULL,
                    last_seen_at TEXT, ac_state_json TEXT
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL, kind TEXT NOT NULL,
                    message TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS commands (
                    request_id TEXT PRIMARY KEY, room_id TEXT NOT NULL,
                    device_id TEXT NOT NULL, source TEXT NOT NULL,
                    power TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    response_json TEXT
                );
                CREATE TABLE IF NOT EXISTS automation_state (
                    room_id TEXT PRIMARY KEY, run_until TEXT,
                    cooldown_until TEXT, manual_lockout_until TEXT,
                    timer_source TEXT
                );
            """)

    def record_measurement(self, device, metric, value, unit, *, received_at=None,
                           quality="fresh", sample=None):
        when = received_at or utc_now()
        stamp = iso(when)
        hour = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00:00+00:00")
        with self._lock, self._db:
            self._db.execute("""
                INSERT INTO measurements(home_id,room_id,device_id,metric,value,unit,
                                         received_at,quality,sample)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (device.home_id, device.room_id, device.device_id, metric,
                  value, unit, stamp, quality, sample))
            if quality == "fresh":
                self._db.execute("""
                    INSERT INTO hourly(home_id,room_id,device_id,metric,hour,total,count,
                                       minimum,maximum)
                    VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(device_id,metric,hour) DO UPDATE SET
                      total=total+excluded.total,
                      count=count+1,
                      minimum=MIN(minimum,excluded.minimum),
                      maximum=MAX(maximum,excluded.maximum)
                """, (device.home_id, device.room_id, device.device_id, metric,
                      hour, value, 1, value, value))

    def latest(self, room_id):
        with self._lock:
            rows = self._db.execute("""
                SELECT m.* FROM measurements m JOIN (
                  SELECT metric, MAX(id) AS id FROM measurements
                  WHERE room_id=? GROUP BY metric
                ) recent ON m.id=recent.id ORDER BY m.metric
            """, (room_id,)).fetchall()
        return {row["metric"]: dict(row) for row in rows}

    def history(self, room_id, metric, hours=24):
        # Keep raw samples for seven days, but expose bounded hourly summaries.
        # A 5-second sensor would otherwise return over 120,000 rows per week.
        hours = min(max(int(hours), 1), 336)
        cutoff = iso(utc_now() - timedelta(hours=hours - 1))[:13] + ":00:00+00:00"
        with self._lock:
            rows = self._db.execute("""
                SELECT hour, device_id, total/count AS average, minimum, maximum,
                       count FROM hourly
                WHERE room_id=? AND metric=? AND hour>=?
                ORDER BY hour,device_id LIMIT 10000
            """, (room_id, metric, cutoff)).fetchall()
        return [dict(row) for row in rows]

    def set_device(self, device_id, availability, last_seen_at=None, ac_state=None):
        with self._lock, self._db:
            current = self._db.execute(
                "SELECT last_seen_at,ac_state_json FROM device_state WHERE device_id=?",
                (device_id,)).fetchone()
            seen = last_seen_at or (current["last_seen_at"] if current else None)
            state_json = (json.dumps(ac_state, separators=(",", ":")) if ac_state is not None
                          else (current["ac_state_json"] if current else None))
            self._db.execute("""
                INSERT INTO device_state(device_id,availability,last_seen_at,ac_state_json)
                VALUES(?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET
                  availability=excluded.availability,
                  last_seen_at=excluded.last_seen_at,
                  ac_state_json=excluded.ac_state_json
            """, (device_id, availability, seen, state_json))

    def devices(self):
        with self._lock:
            rows = self._db.execute("SELECT * FROM device_state").fetchall()
        result = {}
        for row in rows:
            state = dict(row)
            state_json = state.pop("ac_state_json")
            state["ac_state"] = json.loads(state_json) if state_json else None
            result[state["device_id"]] = state
        return result

    def add_alert(self, room_id, kind, message):
        with self._lock, self._db:
            cursor = self._db.execute(
                "INSERT INTO alerts(room_id,kind,message,created_at) VALUES(?,?,?,?)",
                (room_id, kind, message, iso(utc_now())))
            return cursor.lastrowid

    def alerts_since(self, last_id=0):
        with self._lock:
            rows = self._db.execute("""
                SELECT * FROM alerts WHERE id>? ORDER BY id LIMIT 100
            """, (max(int(last_id), 0),)).fetchall()
        return [dict(row) for row in rows]

    def add_command(self, request_id, room_id, device_id, source, power, status):
        stamp = iso(utc_now())
        with self._lock, self._db:
            self._db.execute("""
                INSERT INTO commands(request_id,room_id,device_id,source,power,status,
                                     created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
            """, (request_id, room_id, device_id, source, power, status, stamp, stamp))

    def update_command(self, request_id, status, response=None, expected_status=None):
        with self._lock, self._db:
            query = """UPDATE commands SET status=?,updated_at=?,response_json=?
                       WHERE request_id=?"""
            params = [status, iso(utc_now()), json.dumps(response) if response else None,
                      request_id]
            if expected_status is not None:
                query += " AND status=?"
                params.append(expected_status)
            cursor = self._db.execute(query, params)
            return cursor.rowcount > 0

    def acknowledge_command(self, request_id, status, response):
        allowed = {
            "received": ("pending", "queued_for_mqtt", "published_to_broker", "received"),
            "ir_sent": ("pending", "queued_for_mqtt", "published_to_broker", "received", "ir_sent"),
            "failed": ("pending", "queued_for_mqtt", "published_to_broker", "received", "failed"),
        }
        with self._lock, self._db:
            placeholders = ",".join("?" for _ in allowed[status])
            cursor = self._db.execute(
                "UPDATE commands SET status=?,updated_at=?,response_json=? "
                f"WHERE request_id=? AND status IN ({placeholders})",
                (status, iso(utc_now()), json.dumps(response), request_id,
                 *allowed[status]),
            )
            return cursor.rowcount > 0

    def command(self, request_id):
        with self._lock:
            row = self._db.execute("SELECT * FROM commands WHERE request_id=?",
                                   (request_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["response"] = (json.loads(result.pop("response_json"))
                              if result["response_json"] else None)
        return result

    def save_automation(self, room_id, run_until=None, cooldown_until=None,
                        manual_lockout_until=None, timer_source=None):
        with self._lock, self._db:
            self._db.execute("""
                INSERT INTO automation_state(room_id,run_until,cooldown_until,
                                             manual_lockout_until,timer_source)
                VALUES(?,?,?,?,?) ON CONFLICT(room_id) DO UPDATE SET
                  run_until=excluded.run_until,
                  cooldown_until=excluded.cooldown_until,
                  manual_lockout_until=excluded.manual_lockout_until,
                  timer_source=excluded.timer_source
            """, (room_id, run_until, cooldown_until, manual_lockout_until, timer_source))

    def automations(self):
        with self._lock:
            rows = self._db.execute("SELECT * FROM automation_state").fetchall()
        return {row["room_id"]: dict(row) for row in rows}

    def prune(self):
        now = utc_now()
        with self._lock, self._db:
            self._db.execute("DELETE FROM measurements WHERE received_at<?",
                             (iso(now - timedelta(days=7)),))
            self._db.execute("DELETE FROM hourly WHERE hour<?",
                             (iso(now - timedelta(days=14)),))
            self._db.execute("DELETE FROM alerts WHERE created_at<?",
                             (iso(now - timedelta(days=7)),))
            self._db.execute("DELETE FROM commands WHERE created_at<?",
                             (iso(now - timedelta(days=14)),))

    def close(self):
        with self._lock:
            self._db.close()
