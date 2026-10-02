from datetime import datetime, timedelta, timezone

from features.salm.late_night import (
    LateNightEvaluator,
    LateNightLanguage,
    LateNightPolicyStore,
    LateNightSignal,
    care_day_for,
    clean_late_night_language,
    match_late_night_command,
)
from features.salm.models import (
    ActivityKind,
    ActivitySnapshot,
    Confidence,
    DerivedState,
    DisplayState,
    MediaKind,
    Presence,
)
from features.salm.policy import BreakPolicy
from features.salm.runtime import SalmRuntime
from persistence import LocalDatabase


TZ = timezone(timedelta(hours=7))


def _snapshot(monotonic, hour=23, minute=30):
    return ActivitySnapshot(
        monotonic=float(monotonic),
        wall_time=datetime(2030, 1, 2, hour, minute, tzinfo=TZ),
        idle_seconds=0,
        foreground_app="code",
        display=DisplayState.ON,
    )


def _active_state():
    return DerivedState(
        presence=Presence.PRESENT,
        display=DisplayState.ON,
        activity=ActivityKind.ACTIVE_INTERACTIVE,
        media=MediaKind.NONE,
        primary_app="code",
        confidence=Confidence.HIGH,
        evidence=("recent_input",),
        since_monotonic=0,
        since_wall=datetime(2030, 1, 2, 23, 0, tzinfo=TZ),
    )


class _Gate:
    def __init__(self, reasons=()):
        self.value = tuple(reasons)

    def reasons(self, _scope, now=None):
        return self.value


def test_explicit_policy_defaults_off_and_roundtrips_in_sqlite(tmp_path):
    database = LocalDatabase(tmp_path / "assistant.db")
    policy = LateNightPolicyStore(database=database)
    assert policy.snapshot() == {
        "enabled": False, "cutoff_minute": None, "source": "explicit_user"}

    policy.configure(23 * 60 + 15)
    restored = LateNightPolicyStore(database=database)
    assert restored.snapshot() == {
        "enabled": True, "cutoff_minute": 1395, "source": "explicit_user"}
    row = database.user_preference("salm.late_night_policy")
    assert row["source"] == "explicit_user"
    assert row["consent_scope"] == "late_night_care"

    restored.reset()
    assert database.user_preference("salm.late_night_policy") is None


class _BrokenPreferenceDatabase:
    def user_preference(self, _key):
        raise OSError("offline")

    def set_user_preference(self, *_args, **_kwargs):
        raise OSError("offline")

    def delete_user_preference(self, _key):
        raise OSError("offline")


def test_policy_falls_back_to_local_file_when_database_is_unavailable(tmp_path):
    path = tmp_path / "late-night-policy.json"
    policy = LateNightPolicyStore(path, database=_BrokenPreferenceDatabase())
    policy.configure(23 * 60)

    restored = LateNightPolicyStore(path, database=_BrokenPreferenceDatabase())
    assert restored.snapshot()["cutoff_minute"] == 23 * 60
    restored.reset()
    assert not path.exists()


def test_command_matcher_is_scoped_and_parses_vietnamese_times():
    assert match_late_night_command("bật nhắc khuya lúc 23h30") == {
        "action": "enable", "cutoff_minute": 1410}
    assert match_late_night_command(
        "nhắc tôi khi dùng máy khuya sau 12 giờ đêm") == {
            "action": "enable", "cutoff_minute": 0}
    assert match_late_night_command("đêm nay đừng nhắc khuya") == {
        "action": "mute_tonight"}
    assert match_late_night_command("nhắc khuya lại sau 30 phút") == {
        "action": "snooze", "minutes": 30}
    assert match_late_night_command("hôm nay tôi làm việc khuya") is None


def test_command_matcher_recovers_observed_nhac_to_nhat_stt_error():
    assert match_late_night_command(
        "bật nhất khuya sau 23 giờ 30") == {
            "action": "enable", "cutoff_minute": 1410}
    # Alias chỉ có hiệu lực trong cụm domain, không biến từ "nhất" chung thành lệnh.
    assert match_late_night_command("đây là lựa chọn tốt nhất khuya nay") is None
    assert match_late_night_command(
        "bật nhắc Khuê sau 23 giờ 30") == {
            "action": "enable", "cutoff_minute": 1410}


def test_care_day_rolls_over_at_four_am():
    before = datetime(2030, 1, 2, 3, 59, tzinfo=TZ)
    after = datetime(2030, 1, 2, 4, 0, tzinfo=TZ)
    assert care_day_for(before) == "2030-01-01"
    assert care_day_for(after) == "2030-01-02"


def test_evaluator_requires_sustained_activity_and_dispatches_once_per_care_day():
    policy = LateNightPolicyStore()
    policy.configure(23 * 60)
    evaluator = LateNightEvaluator(
        policy, min_active_seconds=10, active_gap_grace=20)
    gate = _Gate()

    assert evaluator.evaluate(_snapshot(100), _active_state(), gate) is None
    signal = evaluator.evaluate(_snapshot(110), _active_state(), gate)
    assert signal.action == "dispatch"
    assert signal.baseline_status == "insufficient_data"
    assert signal.reason_codes == (
        "explicit_cutoff_crossed", "sustained_interaction")
    assert evaluator.evaluate(_snapshot(130), _active_state(), gate) is None


def test_evaluator_defers_transient_gate_but_consumes_hard_block():
    policy = LateNightPolicyStore()
    policy.configure(23 * 60)
    evaluator = LateNightEvaluator(policy, min_active_seconds=0)
    transient = _Gate(("assistant_busy",))

    assert evaluator.evaluate(_snapshot(10), _active_state(), transient) is None
    signal = evaluator.evaluate(_snapshot(11), _active_state(), _Gate())
    assert signal.action == "dispatch"

    evaluator.reset_runtime()
    dropped = evaluator.evaluate(
        _snapshot(20), _active_state(), _Gate(("user_care_dnd",)))
    assert dropped.action == "drop"
    assert "user_care_dnd" in dropped.reason_codes
    assert evaluator.evaluate(_snapshot(21), _active_state(), _Gate()) is None


def test_evaluator_respects_shared_cooldown_mute_and_snooze():
    policy = LateNightPolicyStore()
    policy.configure(23 * 60)
    evaluator = LateNightEvaluator(policy, min_active_seconds=0)
    snapshot = _snapshot(100)

    assert evaluator.evaluate(
        snapshot, _active_state(), _Gate(), shared_cooldown=True) is None
    evaluator.snooze(100, 1)
    assert evaluator.evaluate(_snapshot(159), _active_state(), _Gate()) is None
    assert evaluator.evaluate(_snapshot(160), _active_state(), _Gate()).action == "dispatch"

    evaluator.reset_runtime()
    evaluator.mute_tonight(snapshot.wall_time)
    assert evaluator.evaluate(snapshot, _active_state(), _Gate()) is None


def test_language_validator_rejects_inference_and_keeps_neutral_fallback():
    assert clean_late_night_language(
        "Bạn làm việc chăm chỉ quá, chắc đang stress rồi.") is None
    safe = "Bạn ơi, đã khá khuya rồi. Mình cân nhắc nghỉ ngơi nhé?"
    assert clean_late_night_language(safe) == safe
    assert "khá khuya" in LateNightLanguage().generate(None)


class _Storage:
    database = None

    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)

    def purge_expired(self):
        pass

    def write_daily(self, _daily):
        pass

    def clear_history(self):
        return {"events": 0, "daily": 0, "files": 0}


class _Dispatcher:
    def __init__(self):
        self.items = []

    def submit(self, item):
        self.items.append(item)
        return True


class _Language:
    def generate(self, _signal):
        return "Bạn ơi, đã khá khuya rồi. Mình cân nhắc nghỉ ngơi nhé?"


def test_runtime_command_updates_policy_and_records_only_structured_values():
    storage = _Storage()
    policy = LateNightPolicyStore()
    runtime = SalmRuntime("", storage=storage, late_night_policy=policy)

    reply = runtime.try_late_night_command(
        "bật nhắc khuya lúc 23:30", now=10,
        at=datetime(2030, 1, 2, 20, 0, tzinfo=TZ))

    assert reply == "Đã bật nhắc khuya sau 23:30."
    assert policy.snapshot()["cutoff_minute"] == 1410
    assert storage.records[-1]["kind"] == "late_night_policy_change"
    assert storage.records[-1]["cutoff_minute"] == 1410
    assert "text" not in storage.records[-1]


def test_runtime_does_not_snooze_a_disabled_policy():
    runtime = SalmRuntime(
        "", storage=_Storage(), late_night_policy=LateNightPolicyStore())
    assert runtime.try_late_night_command(
        "nhắc khuya lại sau 30 phút") == "Nhắc khuya hiện đang tắt."


def test_runtime_submits_late_night_signal_through_dispatcher():
    storage = _Storage()
    dispatcher = _Dispatcher()
    actions = []
    runtime = SalmRuntime(
        "", storage=storage, dispatcher=dispatcher, gate=_Gate(),
        late_night_language=_Language(),
        on_late_night=lambda action, signal, text: actions.append(
            (action, signal.candidate_id, text)))
    signal = LateNightSignal(
        action="dispatch", candidate_id="late_night:2030-01-02",
        care_day="2030-01-02", at=_snapshot(100).wall_time,
        reason_codes=("explicit_cutoff_crossed", "sustained_interaction"))

    assert runtime._handle_late_night_signal(signal)
    assert storage.records[-1]["kind"] == "late_night_signal"
    dispatcher.items[0].present()
    assert actions[0][0] == "present"
    assert "khá khuya" in actions[0][2]


def test_break_policy_exposes_shared_care_cooldown():
    policy = BreakPolicy()
    assert not policy.cue_cooldown_active(100)
    policy.register_external_cue(100)
    assert policy.cue_cooldown_active(101)
    assert not policy.cue_cooldown_active(1301)
