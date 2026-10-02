import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from features.salm.models import DailyMetrics
from features.salm.storage import SalmStorage


@pytest.fixture
def salm_dir():
    # Không dùng tmp_path: một số Windows sandbox từ chối ACL 0o700 mà pytest áp lên
    # basetemp. Thư mục vẫn tách biệt và luôn được dọn sau test.
    path = Path(__file__).parent / f"_salm_tmp_{uuid.uuid4().hex}"
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_storage_rejects_forbidden_data(salm_dir):
    storage = SalmStorage(salm_dir)
    with pytest.raises(ValueError):
        storage.append({"kind": "interval", "window_title": "secret"})
    with pytest.raises(ValueError):
        storage.write_daily({"2030-01-01": _BadMetrics()})


class _BadMetrics:
    def to_dict(self):
        return {"nested": {"url": "https://private.example"}}


def test_write_daily_is_valid_json(salm_dir):
    storage = SalmStorage(salm_dir)
    metrics = DailyMetrics(work_engagement=12.5)
    storage.write_daily({"2030-01-01": metrics})
    payload = json.loads((salm_dir / "daily-2030-01-01.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert payload["metrics"]["work_engagement"] == 12.5
    assert payload["metrics"]["idle_gap"] == 0
    assert len(payload["metrics"]["circadian"][
        "interactive_seconds_by_half_hour"]) == 48


def test_ttl_only_removes_expired_salm_files(salm_dir):
    old = salm_dir / "events-2030-01-01.jsonl"
    keep = salm_dir / "events-2030-01-10.jsonl"
    unrelated = salm_dir / "notes.txt"
    for path in (old, keep, unrelated):
        path.write_text("x", encoding="utf-8")
    removed = SalmStorage(salm_dir, ttl_days=14).purge_expired(
        datetime(2030, 1, 16, tzinfo=timezone.utc))
    assert removed == [old]
    assert not old.exists()
    assert keep.exists() and unrelated.exists()


def test_clear_history_removes_only_salm_history_files(salm_dir):
    event = salm_dir / "events-2030-01-01.jsonl"
    daily = salm_dir / "daily-2030-01-01.json"
    care_style = salm_dir / "care-style.json"
    for path in (event, daily, care_style):
        path.write_text("{}", encoding="utf-8")
    storage = SalmStorage(salm_dir, import_legacy=False)
    storage._daily_base["2030-01-01"] = {"work_engagement": 1}

    result = storage.clear_history()

    assert result == {"events": 0, "daily": 0, "files": 2}
    assert not event.exists() and not daily.exists()
    assert care_style.exists()
    assert storage._daily_base == {}
