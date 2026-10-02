"""Versioned SQLite storage for high-volume local assistant data.

The database is deliberately local-first. Raw observations, derived projections and
long-lived knowledge have separate tables and retention rules instead of one generic
"memory" blob.
"""

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


SCHEMA_VERSION = 4

_MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legacy_imports (
    source_path TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    rows_imported INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS salm_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uid TEXT NOT NULL UNIQUE,
    day TEXT NOT NULL,
    occurred_at TEXT,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_salm_events_day ON salm_events(day);
CREATE INDEX IF NOT EXISTS idx_salm_events_kind_time
    ON salm_events(kind, occurred_at);

CREATE TABLE IF NOT EXISTS salm_daily (
    day TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interaction_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_uid TEXT NOT NULL UNIQUE,
    occurred_at TEXT,
    session_id TEXT,
    result TEXT,
    user_text TEXT NOT NULL DEFAULT '',
    assistant_text TEXT NOT NULL DEFAULT '',
    tools_json TEXT NOT NULL DEFAULT '[]',
    groups_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outcomes_session_time
    ON interaction_outcomes(session_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_outcomes_result_time
    ON interaction_outcomes(result, occurred_at);

CREATE TABLE IF NOT EXISTS memory_facts (
    fact_id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    fact_key TEXT,
    value_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN
        ('candidate', 'confirmed', 'contradicted', 'deleted')),
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    sensitivity TEXT NOT NULL CHECK(sensitivity IN
        ('normal', 'private', 'highly_sensitive')),
    consent_scope TEXT,
    observed_at TEXT NOT NULL,
    last_confirmed_at TEXT,
    valid_from TEXT,
    expires_at TEXT,
    user_corrected INTEGER NOT NULL DEFAULT 0 CHECK(user_corrected IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_facts_lookup
    ON memory_facts(namespace, fact_key, status);

CREATE TABLE IF NOT EXISTS memory_evidence (
    evidence_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL REFERENCES memory_facts(fact_id) ON DELETE CASCADE,
    source_domain TEXT NOT NULL,
    source_id TEXT,
    observed_at TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    evidence_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_memory_evidence_fact
    ON memory_evidence(fact_id, observed_at);

CREATE TABLE IF NOT EXISTS user_preferences (
    preference_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    sensitivity TEXT NOT NULL DEFAULT 'private',
    consent_scope TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS habit_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_key TEXT NOT NULL,
    label TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    source_id TEXT,
    UNIQUE(habit_key, observed_at, source_domain, source_id)
);
CREATE INDEX IF NOT EXISTS idx_habit_observations_key_time
    ON habit_observations(habit_key, observed_at);
"""

_MIGRATION_2 = """
UPDATE memory_facts
SET expires_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', observed_at, '+180 days'),
    updated_at = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
WHERE namespace = 'profile.auto_fact' AND expires_at IS NULL;
"""

_MIGRATION_3 = """
CREATE INDEX IF NOT EXISTS idx_habit_observations_time
    ON habit_observations(observed_at);
"""

_MIGRATION_4 = """
CREATE TABLE IF NOT EXISTS salm_app_preferences (
    app_id TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK(category IN
        ('work', 'communication', 'media', 'personal', 'unknown')),
    excluded INTEGER NOT NULL DEFAULT 0 CHECK(excluded IN (0, 1)),
    source TEXT NOT NULL CHECK(source IN ('suggested', 'user')),
    updated_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _uid(prefix, value):
    digest = hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _profile_fact_id(namespace, value=None):
    """Stable IDs make legacy imports and repeated saves naturally idempotent."""
    if namespace == "profile.identity":
        return "profile:name"
    return _uid(namespace.replace(".", "-"), value)


def _event_expiry(event):
    raw = event.get("when") or event.get("created_at")
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (moment + timedelta(days=7)).isoformat(timespec="seconds")


def _inferred_fact_expiry(observed_at=None):
    try:
        moment = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00")) \
            if observed_at else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        moment = datetime.now(timezone.utc)
    return (moment + timedelta(days=180)).isoformat(timespec="seconds")


class LocalDatabase:
    """Small connection-per-operation SQLite repository safe across app threads."""

    def __init__(self, path, busy_timeout_ms=5000):
        self.path = Path(path)
        self.busy_timeout_ms = max(100, int(busy_timeout_ms))
        self._migration_lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(
            str(self.path), timeout=self.busy_timeout_ms / 1000,
            isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write(self):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def _migrate(self):
        with self._migration_lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if current > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Database schema {current} mới hơn code {SCHEMA_VERSION}")
                if current < 1:
                    for statement in _MIGRATION_1.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute(
                        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                        "VALUES(1, ?)", (_now(),))
                    connection.execute("PRAGMA user_version = 1")
                if current < 2:
                    for statement in _MIGRATION_2.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute(
                        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                        "VALUES(2, ?)", (_now(),))
                    connection.execute("PRAGMA user_version = 2")
                if current < 3:
                    for statement in _MIGRATION_3.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute(
                        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                        "VALUES(3, ?)", (_now(),))
                    connection.execute("PRAGMA user_version = 3")
                if current < 4:
                    for statement in _MIGRATION_4.split(";"):
                        if statement.strip():
                            connection.execute(statement)
                    connection.execute(
                        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
                        "VALUES(4, ?)", (_now(),))
                    connection.execute("PRAGMA user_version = 4")
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def schema_version(self):
        with self._connection() as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def integrity_check(self):
        with self._connection() as connection:
            return connection.execute("PRAGMA quick_check").fetchone()[0]

    def record_salm_event(self, record, *, source="runtime", event_uid=None):
        raw_at = record.get("at") or record.get("end") or record.get("start")
        try:
            day = datetime.fromisoformat(raw_at).date().isoformat() if raw_at else \
                datetime.now().date().isoformat()
        except (TypeError, ValueError):
            day = datetime.now().date().isoformat()
        event_uid = event_uid or f"runtime:{uuid.uuid4().hex}"
        with self._write() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO salm_events("
                "event_uid, day, occurred_at, kind, payload_json, source, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (event_uid, day, raw_at, str(record.get("kind") or "unknown"),
                 _canonical(record), source, _now()))

    def replace_salm_daily(self, day, metrics, schema_version=1):
        with self._write() as connection:
            connection.execute(
                "INSERT INTO salm_daily(day, schema_version, metrics_json, updated_at) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(day) DO UPDATE SET "
                "schema_version=excluded.schema_version, "
                "metrics_json=excluded.metrics_json, updated_at=excluded.updated_at",
                (str(day), int(schema_version), _canonical(metrics), _now()))

    def salm_events(self):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM salm_events ORDER BY id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def salm_daily(self, day):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT schema_version, metrics_json, updated_at "
                "FROM salm_daily WHERE day=?",
                (str(day),)).fetchone()
        if row is None:
            return None
        return {"schema_version": int(row[0]), "day": str(day),
                "metrics": json.loads(row[1]), "updated_at": row[2]}

    def salm_daily_range(self, start_day, end_day):
        """Daily SALM projections in an inclusive, chronological date range."""
        start_day, end_day = str(start_day), str(end_day)
        if start_day > end_day:
            return []
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT day, schema_version, metrics_json, updated_at "
                "FROM salm_daily WHERE day >= ? AND day <= ? ORDER BY day",
                (start_day, end_day)).fetchall()
        return [{"day": row[0], "schema_version": int(row[1]),
                 "metrics": json.loads(row[2]), "updated_at": row[3]}
                for row in rows]

    def purge_salm_events_before(self, cutoff_day):
        with self._write() as connection:
            return connection.execute(
                "DELETE FROM salm_events WHERE day < ?", (str(cutoff_day),)).rowcount

    def purge_salm_daily_before(self, cutoff_day):
        with self._write() as connection:
            return connection.execute(
                "DELETE FROM salm_daily WHERE day < ?", (str(cutoff_day),)).rowcount

    def purge_salm_before(self, cutoff_day):
        """Backward-compatible purge using one cutoff for both SALM projections."""
        return {"events": self.purge_salm_events_before(cutoff_day),
                "daily": self.purge_salm_daily_before(cutoff_day)}

    def upsert_salm_app_preference(self, app_id, category, *, excluded=False,
                                   source="user"):
        """Ghi preference app; suggestion không bao giờ được đè lựa chọn của user."""
        app_id = str(app_id or "").strip().casefold()
        category = str(category or "").strip().lower()
        source = str(source or "").strip().lower()
        if not app_id or len(app_id) > 200 or any(ord(ch) < 32 for ch in app_id):
            raise ValueError("app_id không hợp lệ")
        if category not in {"work", "communication", "media", "personal", "unknown"}:
            raise ValueError("category không hợp lệ")
        if source not in {"suggested", "user"}:
            raise ValueError("source không hợp lệ")
        with self._write() as connection:
            connection.execute(
                "INSERT INTO salm_app_preferences("
                "app_id, category, excluded, source, updated_at) VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(app_id) DO UPDATE SET "
                "category=excluded.category, excluded=excluded.excluded, "
                "source=excluded.source, updated_at=excluded.updated_at "
                "WHERE salm_app_preferences.source <> 'user' OR excluded.source='user'",
                (app_id, category, int(bool(excluded)), source, _now()))
        return self.salm_app_preference(app_id)

    def salm_app_preference(self, app_id):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT app_id, category, excluded, source, updated_at "
                "FROM salm_app_preferences WHERE app_id=?",
                (str(app_id or "").strip().casefold(),)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["excluded"] = bool(value["excluded"])
        return value

    def list_salm_app_preferences(self):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT app_id, category, excluded, source, updated_at "
                "FROM salm_app_preferences ORDER BY app_id").fetchall()
        values = []
        for row in rows:
            value = dict(row)
            value["excluded"] = bool(value["excluded"])
            values.append(value)
        return values

    def delete_salm_app_preference(self, app_id):
        with self._write() as connection:
            return max(0, connection.execute(
                "DELETE FROM salm_app_preferences WHERE app_id=?",
                (str(app_id or "").strip().casefold(),)).rowcount)

    def clear_salm_activity(self):
        """Xoá activity history nhưng giữ persona, memory và app preferences."""
        with self._write() as connection:
            events = max(0, connection.execute("DELETE FROM salm_events").rowcount)
            daily = max(0, connection.execute("DELETE FROM salm_daily").rowcount)
        return {"events": events, "daily": daily}

    def record_outcome(self, record, *, source="runtime", record_uid=None):
        record_uid = record_uid or f"runtime:{uuid.uuid4().hex}"
        with self._write() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO interaction_outcomes("
                "record_uid, occurred_at, session_id, result, user_text, "
                "assistant_text, tools_json, groups_json, payload_json, source, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record_uid, record.get("khi"), record.get("phien"),
                 record.get("ket_qua"), record.get("cau") or "",
                 record.get("dap") or "", _canonical(record.get("tool") or []),
                 _canonical(record.get("nhom") or []), _canonical(record),
                 source, _now()))

    def outcomes(self):
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM interaction_outcomes ORDER BY id").fetchall()
        return [json.loads(row[0]) for row in rows]

    def clear_outcomes(self):
        with self._write() as connection:
            connection.execute("DELETE FROM interaction_outcomes")

    @staticmethod
    def _upsert_fact(connection, *, fact_id, namespace, value, source_domain,
                     fact_key=None, status="candidate", confidence=0.5,
                     sensitivity="private", consent_scope="personalization",
                     observed_at=None, last_confirmed_at=None, valid_from=None,
                     expires_at=None, user_corrected=False, source_id=None,
                     evidence=None, overwrite=True):
        """Write a fact and its provenance in one transaction.

        A user-corrected row cannot be replaced by a later inferred observation. This
        is the central precedence rule for the memory layer, not a convention left to
        individual callers.
        """
        now = _now()
        observed_at = observed_at or now
        values = (
            str(fact_id), str(namespace), fact_key, _canonical(value), str(status),
            float(confidence), str(sensitivity), consent_scope, observed_at,
            last_confirmed_at, valid_from, expires_at, int(bool(user_corrected)),
            now, now,
        )
        if overwrite:
            cursor = connection.execute(
                "INSERT INTO memory_facts("
                "fact_id, namespace, fact_key, value_json, status, confidence, "
                "sensitivity, consent_scope, observed_at, last_confirmed_at, "
                "valid_from, expires_at, user_corrected, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(fact_id) DO UPDATE SET "
                "namespace=excluded.namespace, fact_key=excluded.fact_key, "
                "value_json=excluded.value_json, status=excluded.status, "
                "confidence=excluded.confidence, sensitivity=excluded.sensitivity, "
                "consent_scope=excluded.consent_scope, observed_at=excluded.observed_at, "
                "last_confirmed_at=excluded.last_confirmed_at, "
                "valid_from=excluded.valid_from, expires_at=excluded.expires_at, "
                "user_corrected=excluded.user_corrected, updated_at=excluded.updated_at "
                "WHERE excluded.user_corrected >= memory_facts.user_corrected",
                values)
        else:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO memory_facts("
                "fact_id, namespace, fact_key, value_json, status, confidence, "
                "sensitivity, consent_scope, observed_at, last_confirmed_at, "
                "valid_from, expires_at, user_corrected, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)

        # Candidate suy luận không có bằng chứng thì vẫn có thể được lưu để audit, nhưng
        # KHÔNG có evidence row nên projection đọc sẽ không dùng nó. Confirmed/user facts
        # luôn có provenance tối thiểu ngay cả khi caller không truyền payload riêng.
        evidence_payload = evidence
        if evidence_payload is None and (status == "confirmed" or user_corrected):
            evidence_payload = {"value": value}
        if evidence_payload is not None:
            evidence_id = _uid("evidence", {
                "fact_id": fact_id, "source_domain": source_domain,
                "source_id": source_id, "evidence": evidence_payload,
            })
            connection.execute(
                "INSERT INTO memory_evidence("
                "evidence_id, fact_id, source_domain, source_id, observed_at, weight, "
                "evidence_json) SELECT ?, ?, ?, ?, ?, ?, ? "
                "WHERE EXISTS(SELECT 1 FROM memory_facts WHERE fact_id=?) "
                "ON CONFLICT(evidence_id) DO UPDATE SET "
                "observed_at=excluded.observed_at, weight=excluded.weight, "
                "evidence_json=excluded.evidence_json",
                (evidence_id, fact_id, source_domain, source_id, observed_at,
                 float(confidence), _canonical(evidence_payload), fact_id))
        return max(0, cursor.rowcount)

    def upsert_memory_fact(self, *, fact_id, namespace, value,
                           source_domain="inferred", fact_key=None,
                           status="candidate", confidence=0.5,
                           sensitivity="private", consent_scope="personalization",
                           observed_at=None, last_confirmed_at=None, valid_from=None,
                           expires_at=None, user_corrected=False, source_id=None,
                           evidence=None):
        with self._write() as connection:
            return self._upsert_fact(
                connection, fact_id=fact_id, namespace=namespace, value=value,
                source_domain=source_domain, fact_key=fact_key, status=status,
                confidence=confidence, sensitivity=sensitivity,
                consent_scope=consent_scope, observed_at=observed_at,
                last_confirmed_at=last_confirmed_at, valid_from=valid_from,
                expires_at=expires_at, user_corrected=user_corrected,
                source_id=source_id, evidence=evidence)

    @staticmethod
    def _set_preference(connection, key, value, *, source, confidence=1.0,
                        sensitivity="private", consent_scope="personalization",
                        overwrite=True):
        existing = connection.execute(
            "SELECT source FROM user_preferences WHERE preference_key=?",
            (str(key),)).fetchone()
        if existing is not None and source == "inferred" and existing[0] != "inferred":
            return 0
        if not overwrite and existing is not None:
            return 0
        cursor = connection.execute(
            "INSERT INTO user_preferences("
            "preference_key, value_json, source, confidence, sensitivity, "
            "consent_scope, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(preference_key) DO UPDATE SET "
            "value_json=excluded.value_json, source=excluded.source, "
            "confidence=excluded.confidence, sensitivity=excluded.sensitivity, "
            "consent_scope=excluded.consent_scope, updated_at=excluded.updated_at",
            (str(key), _canonical(value), str(source), float(confidence),
             str(sensitivity), consent_scope, _now()))
        return max(0, cursor.rowcount)

    def set_user_preference(self, key, value, *, source="explicit_user",
                            confidence=1.0, sensitivity="private",
                            consent_scope="personalization"):
        with self._write() as connection:
            return self._set_preference(
                connection, key, value, source=source, confidence=confidence,
                sensitivity=sensitivity, consent_scope=consent_scope)

    def user_preference(self, key):
        """Read one structured preference without projecting it into the LLM profile."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT preference_key, value_json, source, confidence, sensitivity, "
                "consent_scope, updated_at FROM user_preferences "
                "WHERE preference_key=?", (str(key),)).fetchone()
        if row is None:
            return None
        value = dict(row)
        try:
            value["value"] = json.loads(value.pop("value_json"))
        except (TypeError, ValueError):
            return None
        return value

    def delete_user_preference(self, key):
        with self._write() as connection:
            return max(0, connection.execute(
                "DELETE FROM user_preferences WHERE preference_key=?",
                (str(key),)).rowcount)

    def set_profile_name(self, name, *, source="explicit_user"):
        name = str(name or "").strip()
        if not name:
            return 0
        return self.upsert_memory_fact(
            fact_id="profile:name", namespace="profile.identity", fact_key="name",
            value=name, source_domain=source, status="confirmed", confidence=1.0,
            last_confirmed_at=_now(), user_corrected=source == "explicit_user")

    def add_profile_note(self, note, *, inferred=False, evidence=None,
                         confidence=None, source_id=None):
        note = str(note or "").strip()
        if not note:
            return 0
        namespace = "profile.auto_fact" if inferred else "profile.note"
        confidence = (0.6 if inferred else 1.0) if confidence is None else confidence
        return self.upsert_memory_fact(
            fact_id=_profile_fact_id(namespace, note), namespace=namespace,
            value=note, source_domain="inferred" if inferred else "explicit_user",
            status="candidate" if inferred else "confirmed",
            confidence=confidence,
            last_confirmed_at=None if inferred else _now(),
            expires_at=_inferred_fact_expiry() if inferred else None,
            user_corrected=not inferred, source_id=source_id, evidence=evidence)

    def add_profile_event(self, event, *, inferred=False, evidence=None,
                          confidence=None, source_id=None):
        if not isinstance(event, dict) or not str(event.get("text") or "").strip():
            return 0
        clean = {
            "text": str(event["text"]).strip(),
            "when": event.get("when"),
            "created_at": event.get("created_at") or _now(),
        }
        confidence = (0.8 if inferred else 1.0) if confidence is None else confidence
        return self.upsert_memory_fact(
            fact_id=_profile_fact_id("profile.event", clean),
            namespace="profile.event", value=clean,
            source_domain="inferred" if inferred else "explicit_user",
            status="candidate" if inferred else "confirmed",
            confidence=confidence,
            observed_at=clean["created_at"], valid_from=clean.get("when"),
            expires_at=_event_expiry(clean), user_corrected=not inferred,
            source_id=source_id, evidence=evidence)

    def delete_profile_item(self, source, value):
        namespaces = {
            "notes": "profile.note", "auto_facts": "profile.auto_fact",
            "events": "profile.event",
        }
        namespace = namespaces.get(source)
        if namespace is None:
            return 0
        fact_id = _profile_fact_id(namespace, value)
        with self._write() as connection:
            return max(0, connection.execute(
                "DELETE FROM memory_facts WHERE fact_id=?", (fact_id,)).rowcount)

    def prune_expired_memory(self, now=None):
        cutoff = now or _now()
        if isinstance(cutoff, datetime):
            cutoff = cutoff.isoformat(timespec="seconds")
        with self._write() as connection:
            return max(0, connection.execute(
                "DELETE FROM memory_facts WHERE expires_at IS NOT NULL AND expires_at < ?",
                (str(cutoff),)).rowcount)

    def load_user_profile(self):
        profile = {"name": None, "address_form": None,
                   "preferences": {"default_location": None}, "notes": [],
                   "auto_facts": [], "events": []}
        now = _now()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT namespace, fact_key, value_json FROM memory_facts "
                "WHERE (status='confirmed' OR (status='candidate' "
                "AND confidence > 0 AND expires_at IS NOT NULL "
                "AND EXISTS(SELECT 1 FROM memory_evidence e "
                "WHERE e.fact_id=memory_facts.fact_id))) "
                "AND (expires_at IS NULL OR expires_at >= ?) ORDER BY rowid", (now,)
            ).fetchall()
            preferences = connection.execute(
                "SELECT preference_key, value_json FROM user_preferences "
                "WHERE preference_key IN ('address_form', 'default_location')"
            ).fetchall()
        for row in rows:
            try:
                value = json.loads(row[2])
            except (TypeError, ValueError):
                continue
            if row[0] == "profile.identity" and row[1] == "name":
                profile["name"] = value
            elif row[0] == "profile.note" and isinstance(value, str):
                profile["notes"].append(value)
            elif row[0] == "profile.auto_fact" and isinstance(value, str):
                profile["auto_facts"].append(value)
            elif row[0] == "profile.event" and isinstance(value, dict):
                profile["events"].append(value)
        for row in preferences:
            try:
                value = json.loads(row[1])
            except (TypeError, ValueError):
                continue
            if row[0] == "address_form":
                profile["address_form"] = value
            elif row[0] == "default_location":
                profile["preferences"]["default_location"] = value
        return profile

    def import_profile_file(self, path):
        path = Path(path)
        if not path.is_file():
            return 0
        raw = path.read_bytes()
        fingerprint = hashlib.sha256(raw + b"|profile-transform-v1").hexdigest()
        source_path = str(path.resolve())
        if self._already_imported(source_path, fingerprint):
            return 0
        try:
            profile = json.loads(raw.decode("utf-8"))
            if not isinstance(profile, dict):
                return 0
        except (UnicodeError, ValueError):
            return 0

        imported = 0
        with self._write() as connection:
            name = str(profile.get("name") or "").strip()
            if name:
                imported += self._upsert_fact(
                    connection, fact_id="profile:name", namespace="profile.identity",
                    fact_key="name", value=name, source_domain="legacy_profile",
                    status="confirmed", confidence=1.0, last_confirmed_at=_now(),
                    user_corrected=True, overwrite=False)
            for key, value in (
                    ("address_form", profile.get("address_form")),
                    ("default_location",
                     (profile.get("preferences") or {}).get("default_location"))):
                value = str(value or "").strip()
                if value:
                    imported += self._set_preference(
                        connection, key, value, source="legacy_profile",
                        overwrite=False)
            for note in profile.get("notes") or []:
                note = str(note or "").strip()
                if note:
                    imported += self._upsert_fact(
                        connection, fact_id=_profile_fact_id("profile.note", note),
                        namespace="profile.note", value=note,
                        source_domain="legacy_profile", status="confirmed",
                        confidence=1.0, last_confirmed_at=_now(),
                        user_corrected=True, overwrite=False)
            for fact in profile.get("auto_facts") or []:
                fact = str(fact or "").strip()
                if fact:
                    imported += self._upsert_fact(
                        connection, fact_id=_profile_fact_id("profile.auto_fact", fact),
                        namespace="profile.auto_fact", value=fact,
                        source_domain="legacy_profile", status="candidate",
                        confidence=0.6, expires_at=_inferred_fact_expiry(),
                        user_corrected=False, evidence={"legacy_snapshot": True},
                        overwrite=False)
            for event in profile.get("events") or []:
                if not isinstance(event, dict) or not str(event.get("text") or "").strip():
                    continue
                clean = {"text": str(event["text"]).strip(),
                         "when": event.get("when"),
                         "created_at": event.get("created_at") or _now()}
                imported += self._upsert_fact(
                    connection, fact_id=_profile_fact_id("profile.event", clean),
                    namespace="profile.event", value=clean,
                    source_domain="legacy_profile", status="candidate", confidence=0.8,
                    observed_at=clean["created_at"], valid_from=clean.get("when"),
                    expires_at=_event_expiry(clean), user_corrected=False,
                    evidence={"legacy_snapshot": True}, overwrite=False)
            self._mark_imported(connection, source_path, fingerprint, imported)
        return imported

    def export_user_memory(self, destination):
        """Export the normalized memory layer, including provenance metadata."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            facts = [dict(row) for row in connection.execute(
                "SELECT * FROM memory_facts ORDER BY created_at, fact_id").fetchall()]
            evidence = [dict(row) for row in connection.execute(
                "SELECT * FROM memory_evidence ORDER BY observed_at, evidence_id").fetchall()]
            preferences = [dict(row) for row in connection.execute(
                "SELECT * FROM user_preferences ORDER BY preference_key").fetchall()]
            habits = [dict(row) for row in connection.execute(
                "SELECT habit_key, label, observed_at, source_domain, source_id "
                "FROM habit_observations ORDER BY observed_at, id").fetchall()]
        payload = {"schema_version": SCHEMA_VERSION, "exported_at": _now(),
                   "profile": self.load_user_profile(), "facts": facts,
                   "evidence": evidence, "preferences": preferences,
                   "habit_observations": habits}
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        os.replace(temporary, destination)
        return destination

    def delete_user_memory(self):
        """Delete long-lived personal memory; observational SALM/outcome data stays."""
        with self._write() as connection:
            facts = connection.execute("DELETE FROM memory_facts").rowcount
            preferences = connection.execute("DELETE FROM user_preferences").rowcount
            habits = connection.execute("DELETE FROM habit_observations").rowcount
        return {"facts": max(0, facts), "preferences": max(0, preferences),
                "habits": max(0, habits)}

    def record_habit_observation(self, habit_key, label, *, observed_at=None,
                                 source_domain="tool", source_id=None):
        habit_key = str(habit_key or "").strip()
        label = str(label or "").strip()
        if not habit_key or not label:
            return 0
        observed_at = observed_at or _now()
        source_id = source_id or f"runtime:{uuid.uuid4().hex}"
        with self._write() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO habit_observations("
                "habit_key, label, observed_at, source_domain, source_id) "
                "VALUES(?, ?, ?, ?, ?)",
                (habit_key, label, str(observed_at), str(source_domain), str(source_id)))
        return max(0, cursor.rowcount)

    def habit_observations(self, *, fade_days=60, now=None):
        moment = now or datetime.now(timezone.utc)
        if not isinstance(moment, datetime):
            try:
                moment = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                moment = datetime.now(timezone.utc)
        cutoff = (moment - timedelta(days=max(1, int(fade_days)))).isoformat(
            timespec="seconds")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT habit_key, label, observed_at, source_domain, source_id "
                "FROM habit_observations WHERE observed_at >= ? "
                "ORDER BY observed_at, id", (cutoff,)).fetchall()
        return [dict(row) for row in rows]

    def prune_habit_observations(self, *, fade_days=60, max_entries=40, now=None):
        moment = now or datetime.now(timezone.utc)
        if not isinstance(moment, datetime):
            try:
                moment = datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                moment = datetime.now(timezone.utc)
        cutoff = (moment - timedelta(days=max(1, int(fade_days)))).isoformat(
            timespec="seconds")
        with self._write() as connection:
            deleted = max(0, connection.execute(
                "DELETE FROM habit_observations WHERE observed_at < ?", (cutoff,)
            ).rowcount)
            ranked = connection.execute(
                "SELECT habit_key, COUNT(*) AS uses, MAX(observed_at) AS last_seen "
                "FROM habit_observations GROUP BY habit_key "
                "ORDER BY uses DESC, last_seen DESC, habit_key LIMIT -1 OFFSET ?",
                (max(1, int(max_entries)),)).fetchall()
            for row in ranked:
                deleted += max(0, connection.execute(
                    "DELETE FROM habit_observations WHERE habit_key=?", (row[0],)
                ).rowcount)
        return deleted

    def clear_habit_observations(self):
        with self._write() as connection:
            return max(0, connection.execute(
                "DELETE FROM habit_observations").rowcount)

    def import_habits_file(self, path):
        path = Path(path)
        if not path.is_file():
            return 0
        raw = path.read_bytes()
        fingerprint = hashlib.sha256(raw + b"|habits-transform-v1").hexdigest()
        source_path = str(path.resolve())
        if self._already_imported(source_path, fingerprint):
            return 0
        try:
            payload = json.loads(raw.decode("utf-8"))
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, dict):
                return 0
        except (UnicodeError, ValueError):
            return 0

        imported = 0
        with self._write() as connection:
            for key, item in items.items():
                if not isinstance(item, dict):
                    continue
                habit_key = str(key or "").strip()
                label = str(item.get("label") or "").strip()
                observed_at = str(item.get("last") or _now())
                try:
                    count = min(10_000, max(0, int(item.get("count") or 0)))
                except (TypeError, ValueError):
                    count = 0
                if not habit_key or not label:
                    continue
                key_uid = _uid("legacy-habit", habit_key)
                for index in range(count):
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO habit_observations("
                        "habit_key, label, observed_at, source_domain, source_id) "
                        "VALUES(?, ?, ?, 'legacy_habits', ?)",
                        (habit_key, label, observed_at, f"{key_uid}:{index}"))
                    imported += max(0, cursor.rowcount)
            self._mark_imported(connection, source_path, fingerprint, imported)
        return imported

    def _already_imported(self, source_path, fingerprint):
        with self._connection() as connection:
            row = connection.execute(
                "SELECT content_sha256 FROM legacy_imports WHERE source_path=?",
                (str(source_path),)).fetchone()
        return row is not None and row[0] == fingerprint

    def _mark_imported(self, connection, source_path, fingerprint, count):
        connection.execute(
            "INSERT INTO legacy_imports(source_path, content_sha256, imported_at, "
            "rows_imported) VALUES(?, ?, ?, ?) ON CONFLICT(source_path) DO UPDATE SET "
            "content_sha256=excluded.content_sha256, imported_at=excluded.imported_at, "
            "rows_imported=excluded.rows_imported",
            (str(source_path), fingerprint, _now(), int(count)))

    def import_salm_directory(self, directory, validator=None, daily_transform=None):
        directory = Path(directory)
        if not directory.is_dir():
            return 0
        imported = 0
        for path in sorted(directory.glob("events-*.jsonl")):
            imported += self._import_salm_events(path, validator)
        for path in sorted(directory.glob("daily-*.json")):
            imported += self._import_salm_daily(path, validator, daily_transform)
        return imported

    def _import_salm_events(self, path, validator):
        raw = path.read_bytes()
        fingerprint = hashlib.sha256(raw).hexdigest()
        source_path = str(path.resolve())
        if self._already_imported(source_path, fingerprint):
            return 0
        records = []
        for line in raw.decode("utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                if validator is not None:
                    validator(record)
                records.append(record)
            except (ValueError, TypeError):
                continue
        count = 0
        with self._write() as connection:
            for record in records:
                raw_at = record.get("at") or record.get("end") or record.get("start")
                try:
                    day = datetime.fromisoformat(raw_at).date().isoformat() if raw_at else \
                        datetime.now().date().isoformat()
                except (TypeError, ValueError):
                    day = datetime.now().date().isoformat()
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO salm_events("
                    "event_uid, day, occurred_at, kind, payload_json, source, created_at) "
                    "VALUES(?, ?, ?, ?, ?, 'legacy_jsonl', ?)",
                    (_uid("legacy-salm", record), day, raw_at,
                     str(record.get("kind") or "unknown"), _canonical(record), _now()))
                count += max(0, cursor.rowcount)
            self._mark_imported(connection, source_path, fingerprint, count)
        return count

    def _import_salm_daily(self, path, validator, daily_transform):
        raw = path.read_bytes()
        # Transform version is part of the fingerprint so policy fixes re-project old data.
        fingerprint = hashlib.sha256(raw + b"|salm-daily-transform-v2").hexdigest()
        source_path = str(path.resolve())
        if self._already_imported(source_path, fingerprint):
            return 0
        try:
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or not payload.get("day"):
                return 0
            if validator is not None:
                validator(payload)
        except (ValueError, TypeError, UnicodeError):
            return 0
        with self._write() as connection:
            schema_version = int(payload.get("schema_version") or 1)
            metrics = payload.get("metrics") or {}
            if daily_transform is not None:
                metrics = daily_transform(metrics, schema_version)
            connection.execute(
                "INSERT INTO salm_daily(day, schema_version, metrics_json, updated_at) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(day) DO UPDATE SET "
                "schema_version=excluded.schema_version, "
                "metrics_json=excluded.metrics_json, updated_at=excluded.updated_at",
                (str(payload["day"]), schema_version,
                 _canonical(metrics), _now()))
            self._mark_imported(connection, source_path, fingerprint, 1)
        return 1

    def import_outcome_files(self, paths):
        imported = 0
        for path in paths:
            path = Path(path)
            if not path.is_file():
                continue
            raw = path.read_bytes()
            fingerprint = hashlib.sha256(raw).hexdigest()
            source_path = str(path.resolve())
            if self._already_imported(source_path, fingerprint):
                continue
            records = []
            for line in raw.decode("utf-8", errors="replace").splitlines():
                try:
                    record = json.loads(line)
                    if isinstance(record, dict):
                        records.append(record)
                except ValueError:
                    continue
            count = 0
            with self._write() as connection:
                for record in records:
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO interaction_outcomes("
                        "record_uid, occurred_at, session_id, result, user_text, "
                        "assistant_text, tools_json, groups_json, payload_json, source, "
                        "created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'legacy_jsonl', ?)",
                        (_uid("legacy-outcome", record), record.get("khi"),
                         record.get("phien"), record.get("ket_qua"),
                         record.get("cau") or "", record.get("dap") or "",
                         _canonical(record.get("tool") or []),
                         _canonical(record.get("nhom") or []),
                         _canonical(record), _now()))
                    count += max(0, cursor.rowcount)
                self._mark_imported(connection, source_path, fingerprint, count)
            imported += count
        return imported

    def backup(self, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as source, sqlite3.connect(str(destination)) as target:
            source.backup(target)
        return destination

    def counts(self):
        tables = ("salm_events", "salm_daily", "interaction_outcomes",
                  "memory_facts", "memory_evidence", "user_preferences",
                  "habit_observations", "salm_app_preferences")
        with self._connection() as connection:
            return {table: int(connection.execute(
                f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}
