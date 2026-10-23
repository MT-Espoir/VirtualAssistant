"""R0.2: commit/retain intent, persistence and actual input-loop routing."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from features.salm.late_night import LateNightPolicyStore, POLICY_KEY, match_late_night_command
from features.salm.runtime import SalmRuntime
from persistence import LocalDatabase

TZ = timezone(timedelta(hours=7))
AT = datetime(2030, 1, 2, 23, 45, tzinfo=TZ)


class Storage:
    database = None
    def __init__(self): self.records = []
    def append(self, value): self.records.append(value)


class OfflineDatabase:
    def user_preference(self, key): raise OSError('fixture_offline')
    def set_user_preference(self, *args, **kwargs): raise OSError('fixture_offline')
    def delete_user_preference(self, key): raise OSError('fixture_offline')


def runtime(policy, storage):
    # No Windows/media collectors, microphone or speech backend.
    return SalmRuntime('', storage=storage, late_night_policy=policy,
                       power=SimpleNamespace(), windows_probe=SimpleNamespace(),
                       gsmtc=SimpleNamespace(), wasapi=SimpleNamespace())


def store(tmp_path, backend):
    db_path, path = tmp_path/'fixture.db', tmp_path/'fixture-policy.json'
    database = LocalDatabase(db_path) if backend == 'sqlite' else OfflineDatabase() if backend == 'fallback' else None
    return LateNightPolicyStore(path, database), path, database, db_path


def reopen(path, backend, db_path):
    database = LocalDatabase(db_path) if backend == 'sqlite' else OfflineDatabase() if backend == 'fallback' else None
    return LateNightPolicyStore(path, database)


RETAIN = [
    'không bật nhắc khuya lúc 23:30', 'đừng bật nhắc khuya lúc 23:30',
    'không tắt nhắc khuya', 'đừng tắt nhắc khuya', 'chưa tắt nhắc khuya',
    'chưa muốn bật nhắc khuya lúc 23:30', 'không được bật nhắc khuya lúc 23:30',
    'đừng tự động tắt nhắc khuya', 'đừng đặt lại nhắc khuya',
    'không reset nhắc khuya', 'đừng hoãn nhắc khuya lại sau 30 phút',
    'không nhắc khuya lại sau 30 phút',
    'hôm qua tôi đã bật nhắc khuya lúc 23:30',
    'nếu tôi bật nhắc khuya lúc 23:30 thì sao',
    'nhắc khuya của tôi là 23:30', 'nhắc khuya thường bật lúc 23:30',
    'bật nhắc khuya lúc 23:30 và tắt nhắc khuya',
    'bật nhắc khuya lúc 23:30 ngày mai', 'bật nhắc khuya sau 30 phút',
    'bật nhắc khuya lúc 25:00', 'bật nhắc khuya lúc 23:79',
    'bật nhắc khuya lúc 09:00', 'khong bat nhac khuya luc 23:30',
    'Alice, đừng bật nhất khuya lúc 23:30 nhé',
]


@pytest.mark.parametrize('backend', ['json', 'sqlite', 'fallback'])
@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('text', RETAIN)
def test_no_change_is_consumed_without_writes_or_explicit_user_events(
        text, enabled, backend, tmp_path):
    policy, path, db, db_path = store(tmp_path, backend)
    if enabled: policy.configure(1410)
    before = policy.snapshot()
    before_file = path.read_bytes() if path.exists() else None
    before_row = db.user_preference(POLICY_KEY) if backend == 'sqlite' else None
    storage = Storage()
    salm = runtime(policy, storage)
    # Preserve runtime mute/snooze as well as durable policy.
    salm.late_night.mute_tonight(AT)
    salm.late_night.snooze(10, 15)
    transient = (salm.late_night._muted_day, salm.late_night._snooze_until)
    assert match_late_night_command(text)['action'] == 'no_change'
    reply = salm.try_late_night_command(text, now=10, at=AT)
    assert reply and policy.snapshot() == before
    assert reopen(path, backend, db_path).snapshot() == before
    assert (path.read_bytes() if path.exists() else None) == before_file
    if backend == 'sqlite': assert db.user_preference(POLICY_KEY) == before_row
    assert not storage.records
    assert (salm.late_night._muted_day, salm.late_night._snooze_until) == transient


@pytest.mark.parametrize('backend', ['json', 'sqlite', 'fallback'])
def test_clear_commands_persist_and_reset_in_the_real_store(backend, tmp_path):
    policy, path, db, db_path = store(tmp_path, backend)
    storage = Storage()
    salm = runtime(policy, storage)
    for text, cutoff in [('bật nhắc khuya lúc 23:30',1410),
                         ('bật nhất khuya sau 23 giờ 15',1395),
                         ('nhắc tôi khi dùng máy khuya sau 12 giờ đêm',0),
                         ('Alice, hãy bật nhắc khuya lúc 03:30 nhé',210)]:
        assert salm.try_late_night_command(text, now=10, at=AT)
        assert reopen(path, backend, db_path).snapshot()['cutoff_minute'] == cutoff
        assert policy.snapshot()['enabled'] is True
    assert salm.try_late_night_command('tắt nhắc khuya', now=10, at=AT)
    assert reopen(path, backend, db_path).snapshot()['enabled'] is False
    assert salm.try_late_night_command('đặt lại nhắc khuya', now=10, at=AT)
    assert reopen(path, backend, db_path).snapshot()['cutoff_minute'] is None
    assert not path.exists()
    if backend == 'sqlite': assert db.user_preference(POLICY_KEY) is None


@pytest.mark.parametrize('text,action', [
    ('đêm nay đừng nhắc khuya','mute_tonight'),
    ('đừng nhắc khuya đêm nay nhé','mute_tonight'),
    ('không nhắc khuya nữa','disable'), ('đừng nhắc khuya nữa','disable'),
    ('ngừng nhắc khuya','disable'), ('nhắc khuya lại sau 30 phút','snooze'),
    ('hoãn nhắc khuya sau 30 phút','snooze'),
])
def test_explicit_stop_and_snooze_keep_their_intended_effect(text, action):
    policy, storage = LateNightPolicyStore(), Storage()
    policy.configure(1410)
    salm = runtime(policy, storage)
    assert match_late_night_command(text)['action'] == action
    assert salm.try_late_night_command(text, now=10, at=AT)
    assert storage.records[-1]['action'] == action
    if action == 'disable': assert not policy.snapshot()['enabled']
    elif action == 'mute_tonight':
        assert policy.snapshot()['enabled'] and salm.late_night._muted_day is not None
    else:
        assert policy.snapshot()['enabled'] and salm.late_night._snooze_until == 1810


@pytest.mark.parametrize('text', ['không bật nhắc khuya lúc 23:30',
                                  'hôm qua tôi đã bật nhắc khuya lúc 23:30',
                                  'bật nhắc khuya lúc 25:00'])
def test_actual_assistant_loop_does_not_forward_rejected_command_to_agent(text, tmp_path):
    import app
    policy = LateNightPolicyStore(tmp_path/'policy.json')
    storage = Storage()
    salm = runtime(policy, storage)
    agent = MagicMock()
    agent.pending = agent.persona = None
    inputs = iter([text, None])
    app._assistant_loop(agent, MagicMock(), None, None,
                        salm_late_night_command=salm.try_late_night_command,
                        input_reader=lambda *_: next(inputs))
    agent.run.assert_not_called()
    assert not policy.snapshot()['enabled'] and not storage.records
