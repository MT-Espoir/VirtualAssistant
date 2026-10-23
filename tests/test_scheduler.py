"""
Test ReminderScheduler + bộ tool lập lịch.

Không chạy thread nền: gọi trực tiếp due()/_fire_due() với mốc thời gian tất định,
dùng file tạm cho lưu trữ. Tool lập lịch test qua registry_with(actions=scheduler).
"""

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

from services.scheduler import ReminderScheduler
from agent.tools import ActionRefused

from conftest import registry_with
from features.schedule.tools import _parse_fire_time


def _temp_store():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)  # để scheduler tự tạo mới
    return path


# --------------------------- Scheduler --------------------------- #

def test_add_and_list():
    sched = ReminderScheduler(store_path=_temp_store())
    sched.add("uống nước", datetime(2030, 1, 1, 8, 0))
    tasks = sched.list()
    assert len(tasks) == 1 and tasks[0]["message"] == "uống nước"


def test_due_only_returns_past():
    sched = ReminderScheduler(store_path=_temp_store())
    now = datetime(2030, 1, 1, 12, 0)
    sched.add("đã tới hạn", now - timedelta(minutes=1))
    sched.add("chưa tới", now + timedelta(minutes=10))
    due = sched.due(now)
    assert len(due) == 1 and due[0]["message"] == "đã tới hạn"


def test_cancel():
    sched = ReminderScheduler(store_path=_temp_store())
    t = sched.add("họp", datetime(2030, 1, 1, 9, 0))
    assert sched.cancel(t["id"]) is True
    assert sched.list() == []
    assert sched.cancel("khong-co") is False


def test_persistence_reload():
    path = _temp_store()
    s1 = ReminderScheduler(store_path=path)
    s1.add("nhắc bền vững", datetime(2030, 1, 1, 7, 0))
    s2 = ReminderScheduler(store_path=path)   # nạp lại từ file
    assert len(s2.list()) == 1 and s2.list()[0]["message"] == "nhắc bền vững"
    os.unlink(path)


def test_fire_due_calls_notify_and_removes():
    notified = []
    sched = ReminderScheduler(notify=lambda m, k: notified.append((m, k)), store_path=_temp_store())
    sched.add("việc quá hạn", datetime.now() - timedelta(seconds=1))
    sched._fire_due()
    assert notified == [("việc quá hạn", "remind")]   # kind mặc định remind
    assert sched.list() == []   # đã nhắc thì xóa


def test_fire_due_passes_kind_do():
    notified = []
    sched = ReminderScheduler(notify=lambda m, k: notified.append((m, k)), store_path=_temp_store())
    sched.add("mở youtube", datetime.now() - timedelta(seconds=1), kind="do")
    sched._fire_due()
    assert notified == [("mở youtube", "do")]          # hành động theo lịch -> kind 'do'


def _failing_notify(calls):
    def notify(message, kind):
        calls.append((message, kind))
        raise RuntimeError("speaker unavailable")
    return notify


def test_loi_nhac_loi_duoc_hen_lai_roi_bo_sau_so_lan_toi_da():
    """F03: notify lỗi không được xóa ngay lời nhắc; thử lại có giới hạn."""
    from services.scheduler import MAX_ATTEMPTS, RETRY_DELAY
    calls = []
    path = _temp_store()
    sched = ReminderScheduler(notify=_failing_notify(calls), store_path=path)
    now = datetime(2030, 1, 1, 12, 0)
    sched.add("uống thuốc", now - timedelta(seconds=1))
    sched._fire_due(now)
    [task] = ReminderScheduler(store_path=path).list()      # bền qua restart
    assert task["attempts"] == 1
    assert datetime.fromisoformat(task["fire_at"]) == now + RETRY_DELAY
    for attempt in range(2, MAX_ATTEMPTS + 1):
        now += RETRY_DELAY
        sched._fire_due(now)
    assert len(calls) == MAX_ATTEMPTS and sched.list() == []
    os.unlink(path)


def test_lenh_do_loi_khong_tu_chay_lai():
    """Lệnh theo lịch có thể đã chạy dở: không tự thực thi lại."""
    calls = []
    sched = ReminderScheduler(notify=_failing_notify(calls), store_path=_temp_store())
    now = datetime(2030, 1, 1, 12, 0)
    sched.add("tắt máy lạnh", now - timedelta(seconds=1), kind="do")
    sched._fire_due(now)
    sched._fire_due(now + timedelta(hours=1))
    assert calls == [("tắt máy lạnh", "do")] and sched.list() == []


def test_gio_co_mui_gio_so_duoc_voi_gio_naive():
    """F03: trước đây task aware làm due(naive) ném TypeError cho cả lượt quét."""
    from datetime import timezone
    sched = ReminderScheduler(store_path=_temp_store())
    now = datetime(2030, 1, 1, 12, 0)
    aware_past = (now - timedelta(minutes=5)).astimezone(timezone.utc)
    sched.add("aware", aware_past)
    sched.add("naive", now + timedelta(minutes=5))
    assert [t["message"] for t in sched.due(now)] == ["aware"]
    assert [t["message"] for t in sched.due(now.astimezone(timezone.utc))] == ["aware"]


def test_nap_file_cu_co_gio_aware_va_bo_muc_hong():
    import json
    from datetime import timezone
    path = _temp_store()
    now = datetime(2030, 1, 1, 12, 0)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"id": "a1", "message": "cũ", "kind": "remind",
                    "fire_at": (now - timedelta(minutes=1)).astimezone(timezone.utc).isoformat()},
                   {"id": "b2", "message": "hỏng", "kind": "remind", "fire_at": "không phải giờ"}], f)
    sched = ReminderScheduler(store_path=path)
    assert [t["message"] for t in sched.due(now)] == ["cũ"]
    os.unlink(path)


def test_ghi_dia_loi_thi_add_bao_loi(monkeypatch):
    import services.scheduler as module
    sched = ReminderScheduler(store_path=_temp_store())

    def disk_full(*_):
        raise OSError("disk full")
    monkeypatch.setattr(module, "write_json", disk_full)
    with pytest.raises(OSError):
        sched.add("họp", datetime(2030, 1, 1, 9, 0))
    assert sched.list() == []


# --------------------------- _parse_fire_time --------------------------- #

def test_parse_delay_minutes():
    now = datetime(2030, 1, 1, 10, 0)
    assert _parse_fire_time(delay_minutes=15, now=now) == now + timedelta(minutes=15)


def test_parse_at_hhmm_future():
    now = datetime(2030, 1, 1, 10, 0)
    assert _parse_fire_time(at="15:30", now=now) == datetime(2030, 1, 1, 15, 30)


def test_parse_at_hhmm_past_rolls_to_tomorrow():
    now = datetime(2030, 1, 1, 16, 0)
    assert _parse_fire_time(at="09:00", now=now) == datetime(2030, 1, 2, 9, 0)


def test_parse_none_when_no_input():
    assert _parse_fire_time() is None


# --- Chịu lỗi với tham số lộn xộn do model 3B sinh (nguyên nhân bug lịch nhắc) ---

def test_parse_delay_minutes_as_string_with_unit():
    now = datetime(2030, 1, 1, 10, 0)
    for v in ("5", "5 phút", "sau 5 phut", 5):
        assert _parse_fire_time(delay_minutes=v, now=now) == now + timedelta(minutes=5)


def test_parse_relative_leaked_into_at():
    now = datetime(2030, 1, 1, 10, 0)
    assert _parse_fire_time(at="5 phút", now=now) == now + timedelta(minutes=5)
    assert _parse_fire_time(at="2 tiếng", now=now) == now + timedelta(hours=2)
    assert _parse_fire_time(at="30 giây", now=now) == now + timedelta(seconds=30)


def test_parse_at_with_h_separator():
    now = datetime(2030, 1, 1, 10, 0)
    assert _parse_fire_time(at="15h30", now=now) == datetime(2030, 1, 1, 15, 30)


# --------------------------- Tool lập lịch --------------------------- #

def test_schedule_tools_registered_only_with_scheduler():
    names_without = {s["name"] for s in registry_with(actions=MagicMock()).specs()}
    assert "schedule_reminder" not in names_without

    sched = ReminderScheduler(store_path=_temp_store())
    names_with = {s["name"] for s in registry_with(actions=MagicMock(), scheduler=sched).specs()}
    assert {"schedule_reminder", "list_reminders", "cancel_reminder"} <= names_with


def test_schedule_reminder_tool_adds_task():
    sched = ReminderScheduler(store_path=_temp_store())
    reg = registry_with(actions=MagicMock(), scheduler=sched)
    out = reg.run("schedule_reminder", {"message": "gọi mẹ", "delay_minutes": 30})
    assert "Đã đặt nhắc" in out
    assert len(sched.list()) == 1 and sched.list()[0]["message"] == "gọi mẹ"


def test_schedule_action_tool_adds_do_task():
    sched = ReminderScheduler(store_path=_temp_store())
    reg = registry_with(actions=MagicMock(), scheduler=sched)
    # `schedule_action` giờ là destructive (hẹn chạy lệnh lúc người dùng vắng mặt) -> phải nói
    # rõ đã được duyệt. Test này kiểm HANDLER; cổng có test riêng ở test_confirm_gate.py.
    out = reg.run("schedule_action", {"command": "mở youtube", "at": "22:30"},
                  confirmed=True)
    assert "tự làm" in out.lower()
    t = sched.list()[0]
    assert t["message"] == "mở youtube" and t["kind"] == "do"


def test_schedule_action_refuses_late_night_care_collision_even_if_confirmed():
    sched = ReminderScheduler(store_path=_temp_store())
    reg = registry_with(actions=MagicMock(), scheduler=sched)

    with pytest.raises(ActionRefused):
        reg.run("schedule_action", {
            "command": "cảnh báo thức khuya sau 23h30", "at": "23:30"},
            confirmed=True)

    assert sched.list() == []


def test_cancel_reminder_tool():
    sched = ReminderScheduler(store_path=_temp_store())
    reg = registry_with(actions=MagicMock(), scheduler=sched)
    task = sched.add("việc", datetime(2030, 1, 1, 9, 0))
    out = reg.run("cancel_reminder", {"task_id": task["id"]})
    assert "Đã hủy" in out and sched.list() == []


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print("PASS", _name)
            except Exception as _e:  # noqa: BLE001
                failures += 1
                print("FAIL", _name, "->", repr(_e))
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    raise SystemExit(1 if failures else 0)
