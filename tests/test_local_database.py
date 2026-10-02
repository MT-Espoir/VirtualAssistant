import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from features.salm.models import DailyMetrics
from features.salm.storage import SalmStorage
from memory.habits import HabitLog
from memory.outcomes import OutcomeLog
from memory.profile import UserProfile
from persistence import LocalDatabase


class _BrokenDatabase:
    def import_salm_directory(self, *args, **kwargs):
        raise OSError("database unavailable")

    def import_outcome_files(self, *args, **kwargs):
        raise OSError("database unavailable")

    def record_salm_event(self, *args, **kwargs):
        raise OSError("database unavailable")

    def salm_daily(self, *args, **kwargs):
        raise OSError("database unavailable")

    def record_outcome(self, *args, **kwargs):
        raise OSError("database unavailable")

    def outcomes(self):
        raise OSError("database unavailable")


def test_database_bootstraps_versioned_schema_with_integrity(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")

    assert database.schema_version() == 4
    assert database.integrity_check() == "ok"
    assert database.counts() == {
        "salm_events": 0,
        "salm_daily": 0,
        "interaction_outcomes": 0,
        "memory_facts": 0,
        "memory_evidence": 0,
        "user_preferences": 0,
        "habit_observations": 0,
        "salm_app_preferences": 0,
    }


def test_schema_v2_backfills_expiry_for_existing_inferred_profile_facts(tmp_path):
    path = tmp_path / "alice.db"
    database = LocalDatabase(path)
    database.add_profile_note("hay chạy bộ", inferred=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE memory_facts SET expires_at=NULL WHERE namespace='profile.auto_fact'")
        connection.execute("DELETE FROM schema_migrations WHERE version=2")
        connection.execute("PRAGMA user_version=1")

    migrated = LocalDatabase(path)
    exported = json.loads(
        migrated.export_user_memory(tmp_path / "memory.json").read_text(encoding="utf-8"))

    assert migrated.schema_version() == 4
    assert exported["facts"][0]["expires_at"] is not None


def test_salm_storage_uses_database_without_creating_new_json_files(tmp_path):
    legacy_dir = tmp_path / "salm"
    database = LocalDatabase(tmp_path / "alice.db")
    storage = SalmStorage(legacy_dir, database=database)

    storage.append({"kind": "interval", "at": "2030-01-02T10:00:00+00:00",
                    "activity": "active_interactive"})
    storage.write_daily({"2030-01-02": DailyMetrics(work_engagement=12.5)})

    assert database.salm_events()[0]["activity"] == "active_interactive"
    assert database.salm_daily("2030-01-02")["metrics"]["work_engagement"] == 12.5
    assert not legacy_dir.exists()


def test_legacy_salm_import_is_idempotent_and_rejects_forbidden_records(tmp_path):
    legacy_dir = tmp_path / "salm"
    legacy_dir.mkdir()
    events = legacy_dir / "events-2030-01-02.jsonl"
    events.write_text(
        json.dumps({"kind": "interval", "at": "2030-01-02T10:00:00+00:00"})
        + "\n" + json.dumps({"kind": "interval", "window_title": "secret"}) + "\n",
        encoding="utf-8")
    (legacy_dir / "daily-2030-01-02.json").write_text(json.dumps({
        "schema_version": 1, "day": "2030-01-02",
        "metrics": {"work_engagement": 5, "apps": {
            "svchost": {"running": 100, "foreground": 0, "interactive": 0,
                        "passive_viewing": 0, "background_audio": 0},
            "code": {"running": 100, "foreground": 5, "interactive": 5,
                     "passive_viewing": 0, "background_audio": 0},
        }},
    }), encoding="utf-8")
    database = LocalDatabase(tmp_path / "alice.db")

    SalmStorage(legacy_dir, database=database)
    SalmStorage(legacy_dir, database=database)

    assert len(database.salm_events()) == 1
    imported = database.salm_daily("2030-01-02")["metrics"]
    assert imported["work_engagement"] == 5
    assert set(imported["apps"]) == {"code"}


def test_outcome_log_imports_legacy_then_writes_and_clears_database(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    path.write_text(json.dumps({
        "khi": "2030-01-01T10:00:00", "phien": "old",
        "cau": "cũ", "dap": "đã đọc", "ket_qua": "xong",
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    database = LocalDatabase(tmp_path / "alice.db")
    outcomes = OutcomeLog(str(path), database=database)

    outcomes.record({"cau": "mới", "dap": "xong", "ket_qua": "xong"})
    records = outcomes.doc()

    assert [record["cau"] for record in records] == ["cũ", "mới"]
    assert len(records[1]["phien"]) == 8
    assert path.read_text(encoding="utf-8").count("\n") == 1

    outcomes.clear()
    assert outcomes.doc() == []
    assert not path.exists()


def test_concurrent_writers_are_serialized_by_wal_and_busy_timeout(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    errors = []

    def write(worker):
        try:
            for index in range(25):
                database.record_outcome({
                    "khi": datetime.now(timezone.utc).isoformat(),
                    "phien": f"{worker}", "cau": f"{worker}-{index}",
                    "ket_qua": "xong",
                })
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(worker,)) for worker in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert database.counts()["interaction_outcomes"] == 100


def test_backup_is_consistent_and_readable(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    database.record_outcome({"cau": "backup me", "ket_qua": "xong"})

    backup = database.backup(tmp_path / "backups" / "alice.db")
    restored = LocalDatabase(backup)

    assert restored.integrity_check() == "ok"
    assert restored.outcomes()[0]["cau"] == "backup me"


def test_salm_retention_deletes_only_rows_before_cutoff(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    storage = SalmStorage(tmp_path / "salm", ttl_days=14, daily_ttl_days=90,
                          database=database)
    storage.append({"kind": "interval", "at": "2029-10-01T10:00:00+00:00"})
    storage.append({"kind": "interval", "at": "2030-01-01T10:00:00+00:00"})
    storage.append({"kind": "interval", "at": "2030-01-10T10:00:00+00:00"})
    storage.write_daily({
        "2029-10-01": DailyMetrics(),
        "2030-01-01": DailyMetrics(),
        "2030-01-10": DailyMetrics(),
    })

    storage.purge_expired(datetime(2030, 1, 16, tzinfo=timezone.utc))

    assert len(database.salm_events()) == 1
    assert database.salm_daily("2029-10-01") is None
    assert database.salm_daily("2030-01-01") is not None
    assert database.salm_daily("2030-01-10") is not None


def test_salm_daily_range_is_inclusive_chronological_and_carries_update_time(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    for day, value in (("2030-01-01", 1), ("2030-01-03", 3), ("2030-01-02", 2)):
        database.replace_salm_daily(day, {"work_engagement": value})

    rows = database.salm_daily_range("2030-01-02", "2030-01-03")

    assert [row["day"] for row in rows] == ["2030-01-02", "2030-01-03"]
    assert [row["metrics"]["work_engagement"] for row in rows] == [2, 3]
    assert all(row["updated_at"] for row in rows)
    assert database.salm_daily_range("2030-01-03", "2030-01-02") == []


def test_schema_v4_app_preferences_enforce_enums_and_user_override(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")

    suggested = database.upsert_salm_app_preference(
        "code", "work", source="suggested")
    chosen = database.upsert_salm_app_preference(
        "code", "personal", source="user")
    ignored = database.upsert_salm_app_preference(
        "code", "work", source="suggested")

    assert suggested["category"] == "work"
    assert chosen["category"] == "personal"
    assert ignored["category"] == "personal" and ignored["source"] == "user"
    import pytest
    with pytest.raises(ValueError):
        database.upsert_salm_app_preference("code", "stress", source="user")
    with pytest.raises(ValueError):
        database.upsert_salm_app_preference("code", "work", source="model")

    with sqlite3.connect(database.path) as connection, pytest.raises(
            sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO salm_app_preferences VALUES(?, ?, ?, ?, ?)",
            ("bad", "stress", 0, "user", "2030-01-01T00:00:00+00:00"))


def test_schema_v4_migrates_existing_v3_without_touching_activity(tmp_path):
    path = tmp_path / "alice.db"
    database = LocalDatabase(path)
    database.replace_salm_daily("2030-01-01", {"work_engagement": 7})
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE salm_app_preferences")
        connection.execute("DELETE FROM schema_migrations WHERE version=4")
        connection.execute("PRAGMA user_version=3")

    migrated = LocalDatabase(path)

    assert migrated.schema_version() == 4
    assert migrated.salm_daily("2030-01-01")["metrics"]["work_engagement"] == 7
    assert migrated.list_salm_app_preferences() == []


def test_clear_salm_activity_preserves_app_preferences_and_other_memory(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    database.record_salm_event({"kind": "interval", "at": "2030-01-01T10:00:00"})
    database.replace_salm_daily("2030-01-01", {"work_engagement": 3})
    database.upsert_salm_app_preference("code", "work", source="user")
    database.add_profile_note("ghi nhớ tôi")

    removed = database.clear_salm_activity()

    assert removed == {"events": 1, "daily": 1}
    assert database.salm_events() == []
    assert database.salm_daily("2030-01-01") is None
    assert database.salm_app_preference("code")["category"] == "work"
    assert database.load_user_profile()["notes"] == ["ghi nhớ tôi"]


def test_daily_projection_continues_across_runtime_restarts(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    first = SalmStorage(tmp_path / "salm", database=database)
    first.write_daily({"2030-01-10": DailyMetrics(work_engagement=10)})

    second = SalmStorage(tmp_path / "salm", database=database)
    second.write_daily({"2030-01-10": DailyMetrics(work_engagement=4)})
    second.write_daily({"2030-01-10": DailyMetrics(work_engagement=7)})

    # Base 10 + current runtime projection 7; the intermediate flush of 4 is not added twice.
    assert database.salm_daily("2030-01-10")["metrics"]["work_engagement"] == 17


def test_database_failure_falls_back_to_legacy_files(tmp_path):
    salm_dir = tmp_path / "salm"
    storage = SalmStorage(salm_dir, database=_BrokenDatabase())
    storage.append({"kind": "interval", "at": "2030-01-10T10:00:00+00:00"})
    storage.write_daily({"2030-01-10": DailyMetrics(work_engagement=3)})

    outcome_path = tmp_path / "outcomes.jsonl"
    outcomes = OutcomeLog(str(outcome_path), database=_BrokenDatabase())
    outcomes.record({"cau": "fallback", "ket_qua": "xong"})

    habit_path = tmp_path / "habits.json"
    habits = HabitLog(habit_path, database=_BrokenDatabase())
    for _ in range(3):
        habits.record("Chrome", "mở {}")

    assert (salm_dir / "events-2030-01-10.jsonl").is_file()
    assert (salm_dir / "daily-2030-01-10.json").is_file()
    assert outcomes.doc()[0]["cau"] == "fallback"
    assert "hay mở Chrome (3 lần)" in HabitLog(habit_path).summary()


def test_profile_imports_legacy_json_once_with_provenance(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps({
        "name": "Lan", "address_form": "chị",
        "preferences": {"default_location": "Đà Lạt"},
        "notes": ["thích cà phê"], "auto_facts": ["hay chạy bộ"],
        "events": [],
    }, ensure_ascii=False), encoding="utf-8")
    database = LocalDatabase(tmp_path / "alice.db")

    first = UserProfile(profile_path, database=database)
    second = UserProfile(profile_path, database=database)

    assert first.data == second.data
    assert first.data["name"] == "Lan"
    assert first.get_address_form() == "chị"
    assert first.get_default_location() == "Đà Lạt"
    assert database.counts()["memory_facts"] == 3
    assert database.counts()["memory_evidence"] == 3
    assert database.counts()["user_preferences"] == 2


def test_profile_database_roundtrip_does_not_create_new_json(tmp_path):
    profile_path = tmp_path / "profile.json"
    database = LocalDatabase(tmp_path / "alice.db")
    profile = UserProfile(profile_path, database=database)

    profile.remember(name="Minh", address_form="bạn", location="Huế",
                     note="thích trà")
    profile.add_auto_fact("thường đọc sách", evidence={"quote": "tôi thường đọc sách"})
    restored = UserProfile(profile_path, database=database)

    assert restored.data["name"] == "Minh"
    assert restored.data["notes"] == ["thích trà"]
    assert restored.data["auto_facts"] == ["thường đọc sách"]
    assert restored.get_default_location() == "Huế"
    assert not profile_path.exists()


def test_explicit_user_correction_cannot_be_overwritten_by_inference(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    database.upsert_memory_fact(
        fact_id="profile:name", namespace="profile.identity", fact_key="name",
        value="Tên suy luận", source_domain="inferred", confidence=0.4)
    database.set_profile_name("Tên đúng")
    database.upsert_memory_fact(
        fact_id="profile:name", namespace="profile.identity", fact_key="name",
        value="Tên suy luận mới", source_domain="inferred", confidence=0.9)
    database.set_user_preference("address_form", "chị", source="explicit_user")
    database.set_user_preference("address_form", "bạn", source="inferred")

    profile = database.load_user_profile()
    assert profile["name"] == "Tên đúng"
    assert profile["address_form"] == "chị"


def test_structured_user_preference_can_be_read_and_deleted(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    database.set_user_preference(
        "salm.test", {"enabled": True}, consent_scope="test")

    row = database.user_preference("salm.test")
    assert row["value"] == {"enabled": True}
    assert row["source"] == "explicit_user"
    assert row["consent_scope"] == "test"
    assert database.delete_user_preference("salm.test") == 1
    assert database.user_preference("salm.test") is None


def test_profile_export_and_delete_include_metadata_and_cascade_evidence(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    profile = UserProfile(tmp_path / "profile.json", database=database)
    profile.remember(name="Lan", note="thích cà phê")
    profile.add_auto_fact("hay chạy bộ", evidence={"quote": "tôi hay chạy bộ"})
    database.record_habit_observation("chrome", "mở Chrome")

    export_path = profile.export_data(tmp_path / "exports" / "memory.json")
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["profile"]["name"] == "Lan"
    assert {row["status"] for row in exported["facts"]} == {"candidate", "confirmed"}
    assert all(row["source_domain"] for row in exported["evidence"])
    inferred = next(row for row in exported["facts"]
                    if row["namespace"] == "profile.auto_fact")
    explicit = next(row for row in exported["facts"]
                    if row["namespace"] == "profile.note")
    assert inferred["expires_at"] is not None
    assert explicit["expires_at"] is None

    deleted = profile.clear()
    assert deleted["facts"] == 3
    assert deleted["habits"] == 1
    assert database.counts()["memory_facts"] == 0
    assert database.counts()["memory_evidence"] == 0
    assert database.counts()["user_preferences"] == 0
    assert profile.data["name"] is None


def test_candidate_is_not_projected_without_evidence_confidence_and_expiry(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    database.upsert_memory_fact(
        fact_id="candidate:tea", namespace="profile.auto_fact", value="thích trà",
        source_domain="consolidation", status="candidate", confidence=0.7)
    assert database.load_user_profile()["auto_facts"] == []

    database.upsert_memory_fact(
        fact_id="candidate:tea", namespace="profile.auto_fact", value="thích trà",
        source_domain="consolidation", status="candidate", confidence=0.7,
        expires_at="2999-01-01T00:00:00+00:00", source_id="stm:abc",
        evidence={"quote": "tôi thích uống trà"})
    assert database.load_user_profile()["auto_facts"] == ["thích trà"]


def test_habits_migrate_idempotently_then_use_sqlite_as_primary(tmp_path):
    path = tmp_path / "habits.json"
    legacy = {"items": {"chrome": {
        "label": "mở Chrome", "count": 3,
        "last": datetime.now().isoformat(timespec="seconds"),
    }}}
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    original = path.read_bytes()
    database = LocalDatabase(tmp_path / "alice.db")

    first = HabitLog(path, database=database)
    second = HabitLog(path, database=database)
    assert "hay mở Chrome (3 lần)" in second.summary()

    first.record("Chrome", "mở {}")
    assert "hay mở Chrome (4 lần)" in first.summary()
    assert database.counts()["habit_observations"] == 4
    assert path.read_bytes() == original


def test_habit_observation_retention_resets_old_count(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    old = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
    for index in range(5):
        database.record_habit_observation(
            "song", "nghe 'A'", observed_at=old, source_id=f"old:{index}")
    habits = HabitLog(tmp_path / "habits.json", database=database)
    habits.record("song", "nghe '{}'")

    assert habits.summary() == ""
    assert database.counts()["habit_observations"] == 1


def test_memory_export_contains_habit_observations(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    habits = HabitLog(tmp_path / "habits.json", database=database)
    habits.record("Chrome", "mở {}")

    exported = json.loads(database.export_user_memory(
        tmp_path / "memory.json").read_text(encoding="utf-8"))

    assert exported["habit_observations"][0]["habit_key"] == "chrome"
    assert exported["habit_observations"][0]["source_domain"] == "tool"
