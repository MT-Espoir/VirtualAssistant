import threading
from datetime import datetime, timezone

from features.salm.models import ActivitySnapshot, DisplayState
from features.salm.policy import PolicyDecision
from features.salm.runtime import SalmRuntime


class _Power:
    def start(self): return True
    def stop(self): pass


class _Gsmtc:
    available = False
    def start(self): return False
    def stop(self): pass
    def apps(self): return frozenset()


class _WindowsFailsOnce:
    def __init__(self):
        self.calls = 0
        self.recovered = threading.Event()

    def collect(self, *_):
        self.calls += 1
        if self.calls == 1:
            raise OSError("synthetic collector failure")
        self.recovered.set()
        return ActivitySnapshot(monotonic=float(self.calls),
                                wall_time=datetime.now(timezone.utc),
                                idle_seconds=None, display=DisplayState.UNKNOWN)


class _Storage:
    def __init__(self): self.records = []
    def purge_expired(self): pass
    def append(self, record): self.records.append(record)
    def write_daily(self, _daily): pass
    def clear_history(self):
        self.records.clear()
        return {"events": 2, "daily": 1, "files": 0}


def test_runtime_survives_a_collector_failure():
    windows = _WindowsFailsOnce()
    runtime = SalmRuntime("unused", poll_seconds=0.25, storage=_Storage(),
                          power=_Power(), windows_probe=windows, gsmtc=_Gsmtc())
    runtime.start()
    try:
        assert windows.recovered.wait(2)
        assert runtime.alive
        assert windows.calls >= 2
    finally:
        runtime.stop()


def test_clear_activity_history_resets_in_memory_projection_too():
    storage = _Storage()
    runtime = SalmRuntime("unused", storage=storage, power=_Power(),
                          windows_probe=_WindowsFailsOnce(), gsmtc=_Gsmtc())
    runtime.engine.daily["2030-01-01"] = object()
    old_engine = runtime.engine

    result = runtime.clear_activity_history()

    assert result["daily"] == 1
    assert runtime.engine is not old_engine
    assert runtime.engine.daily == {}


class _Dispatcher:
    def __init__(self): self.items = []
    def submit(self, item):
        self.items.append(item)
        return True


def test_runtime_dispatches_tokenized_care_and_records_cancel_neutrally():
    storage = _Storage()
    dispatcher = _Dispatcher()
    care = []
    runtime = SalmRuntime(
        "unused", storage=storage, power=_Power(), windows_probe=_WindowsFailsOnce(),
        gsmtc=_Gsmtc(), dispatcher=dispatcher, silent_care=True,
        on_care=lambda action, token: care.append((action, token)))
    decision = PolicyDecision(
        "dispatch", "work_engagement:soft:3", "work_engagement", "soft",
        datetime.now(timezone.utc), ("natural_pause",))
    runtime._handle_policy_decision(
        decision, now=10, cycles={"work_engagement": 3})
    item = dispatcher.items[0]
    item.present()
    item.cancel()
    assert care == [("pulse", decision.candidate_id),
                    ("cancel", decision.candidate_id)]
    assert storage.records[-1]["outcome"] == "cue_cancelled"
    assert "url" not in storage.records[-1]
    diagnostic = runtime.diagnostic()
    assert diagnostic["last_policy_decision"]["candidate_id"] == decision.candidate_id
    assert "block_reasons" in diagnostic["gate"]
    assert "url" not in str(diagnostic)


class _WindowsReturn:
    def __init__(self):
        self.calls = 0

    def collect(self, *_):
        self.calls += 1
        away = self.calls == 1
        return ActivitySnapshot(
            monotonic=599.0 + self.calls,
            wall_time=datetime.now(timezone.utc),
            idle_seconds=600.0 if away else 0.0,
            foreground_app="code", display=DisplayState.ON,
            session_locked=False, meeting_open=False)


def test_runtime_submits_welcome_after_confirmed_return():
    storage = _Storage()
    returned = threading.Event()
    events = []

    def on_return(event):
        events.append(event)
        returned.set()

    runtime = SalmRuntime(
        "unused", poll_seconds=0.25, storage=storage, power=_Power(),
        windows_probe=_WindowsReturn(), gsmtc=_Gsmtc(), on_return=on_return)
    runtime.start()
    try:
        assert returned.wait(2)
        assert events[0].absence_seconds >= 600
        assert any(record["kind"] == "return_detected"
                   for record in storage.records)
    finally:
        runtime.stop()
