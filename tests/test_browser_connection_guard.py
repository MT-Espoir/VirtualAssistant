"""R0.4: arbitration/handshake/correlation using actual bridge, no real network."""
import asyncio
import json
from types import SimpleNamespace

import pytest

import services.browser_bridge as bridge_module
from services.browser_bridge import BrowserBridge
from test_r0_findings import isolated, node_fixture


PROFILE_A = '00000000-0000-4000-8000-000000000001'
PROFILE_B = '00000000-0000-4000-8000-000000000002'
SESSION_A = '00000000-0000-4000-8000-000000000011'
SESSION_B = '00000000-0000-4000-8000-000000000012'
SESSION_C = '00000000-0000-4000-8000-000000000013'
TOKEN = 'guard-fixture-authentication-only'


def hello(profile=PROFILE_A, session=SESSION_A, **changes):
    return {'type': 'HELLO', 'protocolVersion': 2, 'profileId': profile, 'sessionId': session,
            'token': TOKEN, **changes}


class Socket:
    def __init__(self, bridge, value=None, origin='chrome-extension://fixture', auto_reply=False, barrier=None):
        self.bridge = bridge
        self.raw = json.dumps(hello() if value is None else value) if not isinstance(value, (str, bytes)) else value
        self.request = SimpleNamespace(headers={'Origin': origin})
        self.entered, self.packet = asyncio.Event(), asyncio.Event()
        self.queue = asyncio.Queue()
        self.closed, self.sent, self.auto_reply, self.barrier = False, [], auto_reply, barrier
    async def recv(self):
        if self.barrier: await self.barrier.wait()
        return self.raw
    async def close(self):
        self.closed = True
        self.queue.put_nowait(None)
        self.entered.set()
    async def send(self, raw):
        command = json.loads(raw)
        self.sent.append(command)
        self.packet.set()
        if self.auto_reply and command.get('request_id'):
            self.bridge._on_message(json.dumps({'type': 'STATUS', 'request_id': command['request_id']}), self)
    def __aiter__(self): return self
    async def __anext__(self):
        self.entered.set()
        value = await self.queue.get()
        if value is None: raise StopAsyncIteration
        return value


async def start(bridge, ws):
    task = asyncio.create_task(bridge._handler(ws))
    await asyncio.wait_for(ws.entered.wait(), 1)
    return task


async def stop(ws, task):
    ws.queue.put_nowait(None)
    await asyncio.wait_for(task, 1)


INVALID_HELLOS = [
    ('legacy', {'type': 'HELLO', 'token': TOKEN}),
    ('wrong_type', hello(type='PING')),
    ('version_bool', hello(protocolVersion=True)),
    ('version_string', hello(protocolVersion='1')),
    ('version_future', hello(protocolVersion=3)),
    ('version_missing', {k: v for k, v in hello().items() if k != 'protocolVersion'}),
    ('profile_missing', {k: v for k, v in hello().items() if k != 'profileId'}),
    ('session_missing', {k: v for k, v in hello().items() if k != 'sessionId'}),
    ('profile_account', hello(profileId='user@example.invalid')),
    ('profile_path', hello(profileId='C:/Private/Profile')),
    ('profile_short', hello(profileId='A')),
    ('profile_null', hello(profileId=None)),
    ('session_v1', hello(sessionId='00000000-0000-1000-8000-000000000011')),
    ('session_short', hello(sessionId='old')),
    ('extra_url', hello(url='https://private.example.invalid/')),
    ('extra_title', hello(title='private page')),
    ('array', []), ('null', 'null'), ('number', 3), ('string', '"HELLO"'),
    ('malformed_json', '{'), ('binary', json.dumps(hello()).encode()),
    ('wrong_token', hello(token='wrong-token')), ('token_null', hello(token=None)),
    ('token_number', hello(token=123)), ('token_empty', hello(token='')),
    ('token_surrogate', hello(token='\ud800')),
    ('duplicate_key', json.dumps(hello())[:-1] + ',"profileId":"' + PROFILE_B + '"}'),
]


@pytest.mark.parametrize('label,value', INVALID_HELLOS, ids=[i[0] for i in INVALID_HELLOS])
def test_invalid_hello_never_becomes_command_target(label, value, caplog):
    async def scenario():
        bridge = BrowserBridge(token=TOKEN)
        ws = Socket(bridge, value)
        await bridge._handler(ws)
        assert ws.closed and not bridge.connected and not ws.sent
        assert bridge.selected_profile_id is None and bridge.connection_id is None
        assert bridge.connection_status['last_rejection'] in ('invalid_hello_schema', 'invalid_hello_frame', 'authentication_failed')
    asyncio.run(scenario())
    assert TOKEN not in caplog.text and 'private page' not in caplog.text
    assert 'user@example.invalid' not in caplog.text and 'C:/Private/Profile' not in caplog.text


@pytest.mark.parametrize('configured', ['', None, 123])
def test_missing_configured_secret_cannot_authenticate(configured):
    async def scenario():
        bridge = BrowserBridge(token=configured)
        ws = Socket(bridge)
        await bridge._handler(ws)
        assert ws.closed and not bridge.connected
        assert bridge.connection_status['last_rejection'] == 'authentication_failed'
    asyncio.run(scenario())


@pytest.mark.parametrize('extra_byte', [0, 1])
def test_hello_frame_size_boundary(extra_byte):
    async def scenario():
        raw = json.dumps(hello())
        raw += ' ' * (bridge_module._MAX_HELLO_BYTES + extra_byte - len(raw.encode()))
        bridge, task = BrowserBridge(token=TOKEN), None
        ws = Socket(bridge, raw)
        try:
            task = await start(bridge, ws)
            assert bridge.connected is (extra_byte == 0)
            assert ws.closed is (extra_byte == 1)
        finally:
            if task: await stop(ws, task)
    asyncio.run(scenario())


def test_handshake_deadline_closes_silent_client(monkeypatch):
    monkeypatch.setattr(bridge_module, '_HANDSHAKE_TIMEOUT_S', .01)
    async def scenario():
        bridge = BrowserBridge(token=TOKEN)
        ws = Socket(bridge, barrier=asyncio.Event())
        await bridge._handler(ws)
        assert ws.closed and not bridge.connected
        assert bridge.connection_status['last_rejection'] == 'invalid_hello_frame'
    asyncio.run(scenario())


@pytest.mark.parametrize('origin', ['https://evil.example.invalid', 'http://127.0.0.1:8765'])
def test_valid_token_does_not_override_website_origin(origin):
    async def scenario():
        bridge = BrowserBridge(token=TOKEN)
        ws = Socket(bridge, origin=origin)
        await bridge._handler(ws)
        assert ws.closed and not bridge.connected
        assert bridge.connection_status['last_rejection'] == 'origin_not_allowed'
    asyncio.run(scenario())


@pytest.mark.parametrize('challenger_profile', [PROFILE_A, PROFILE_B])
def test_active_owner_not_replaced_by_authenticated_challenger(challenger_profile):
    async def scenario():
        bridge = BrowserBridge(token=TOKEN)
        bridge.loop = asyncio.get_running_loop()
        a, b = Socket(bridge, auto_reply=True), Socket(bridge, hello(challenger_profile, SESSION_B), auto_reply=True)
        tasks = []
        try:
            tasks.append(await start(bridge, a)); original_connection = bridge.connection_id
            tasks.append(await start(bridge, b))
            await bridge._send_and_wait({'action': 'CONTROL_MEDIA', 'mediaAction': 'PAUSE'}, .1)
            assert b.closed and not b.sent and len(a.sent) == 1
            assert bridge.connection_id == original_connection and bridge._client is a
            assert bridge.profile_id == bridge.selected_profile_id == PROFILE_A
        finally:
            for ws, task in zip((a, b), tasks): await stop(ws, task)
    asyncio.run(scenario())


def test_simultaneous_handshakes_have_one_owner():
    async def scenario():
        bridge = BrowserBridge(token=TOKEN); barrier = asyncio.Event()
        bridge.loop = asyncio.get_running_loop()
        sockets = [Socket(bridge, hello(p, s), auto_reply=True, barrier=barrier)
                   for p, s in [(PROFILE_A, SESSION_A), (PROFILE_B, SESSION_B), (PROFILE_A, SESSION_C)]]
        tasks = [asyncio.create_task(bridge._handler(ws)) for ws in sockets]
        try:
            barrier.set()
            await asyncio.wait_for(asyncio.gather(*(ws.entered.wait() for ws in sockets)), 1)
            owners = [ws for ws in sockets if not ws.closed]
            assert len(owners) == 1 and bridge._client is owners[0]
            await bridge._send_and_wait({'action': 'GET_TABS'}, .1)
            assert [ws for ws in sockets if ws.sent] == owners
        finally:
            for ws in sockets: ws.queue.put_nowait(None)
            await asyncio.gather(*tasks)
    asyncio.run(scenario())


def test_offline_owner_does_not_allow_other_profile_takeover():
    async def scenario():
        bridge = BrowserBridge(token=TOKEN); bridge.loop = asyncio.get_running_loop()
        a = Socket(bridge); task = await start(bridge, a); await stop(a, task)
        assert not bridge.connected and bridge.selected_profile_id == PROFILE_A
        b = Socket(bridge, hello(PROFILE_B, SESSION_B)); await bridge._handler(b)
        result = bridge.send_command('CONTROL_MEDIA', mediaAction='PAUSE')
        assert b.closed and not b.sent and result['reason'] == 'selected_profile_disconnected'
        assert bridge.connection_status == {'state': 'awaiting_selected_profile', 'last_rejection': 'profile_not_selected'}
    asyncio.run(scenario())


def test_same_profile_reconnect_rotates_connection_and_resets_observation():
    async def scenario():
        bridge = BrowserBridge(token=TOKEN); bridge.loop = asyncio.get_running_loop()
        a = Socket(bridge); task = await start(bridge, a)
        old = bridge.connection_id
        bridge._on_message(json.dumps({'type': 'MEETING_STATE', 'meeting_tab_open': True}), a)
        await stop(a, task)
        assert bridge.meeting_open is None
        b = Socket(bridge, hello(PROFILE_A, SESSION_B), auto_reply=True); task = await start(bridge, b)
        try:
            assert bridge.connection_id != old and bridge.meeting_open is None
            bridge._on_message(json.dumps({'type': 'MEETING_STATE', 'meeting_tab_open': True}), a)
            assert bridge.meeting_open is None
            bridge._on_message(json.dumps({'type': 'MEETING_STATE', 'meeting_tab_open': False}), b)
            assert bridge.meeting_open is None  # R0.5: unsolicited page state is outside release.
            reply = await bridge._send_and_wait({'action': 'GET_TABS'}, .1, expected_connection=old)
            assert reply['reason'] == 'connection_changed' and not b.sent
            await bridge._send_and_wait({'action': 'GET_TABS'}, .1)
            assert len(b.sent) == 1
        finally: await stop(b, task)
    asyncio.run(scenario())


def test_replayed_session_rejected_after_disconnect():
    async def scenario():
        bridge = BrowserBridge(token=TOKEN)
        a = Socket(bridge); task = await start(bridge, a); await stop(a, task)
        b = Socket(bridge); await bridge._handler(b)
        assert b.closed and not bridge.connected and bridge.connection_status['last_rejection'] == 'session_replayed'
    asyncio.run(scenario())


def test_session_history_capacity_fails_closed(monkeypatch):
    monkeypatch.setattr(bridge_module, '_MAX_ACCEPTED_SESSIONS', 2)
    async def scenario():
        bridge = BrowserBridge(token=TOKEN)
        for session in (SESSION_A, SESSION_B):
            ws = Socket(bridge, hello(PROFILE_A, session)); task = await start(bridge, ws); await stop(ws, task)
        ws = Socket(bridge, hello(PROFILE_A, SESSION_C)); await bridge._handler(ws)
        assert ws.closed and not bridge.connected and len(bridge._seen_session_ids) == 2
        assert bridge.connection_status['last_rejection'] == 'session_history_full'
    asyncio.run(scenario())


def test_all_requests_bind_source_even_without_expected_connection():
    async def scenario():
        bridge = BrowserBridge(token=TOKEN); bridge.loop = asyncio.get_running_loop()
        owner = Socket(bridge); handler = await start(bridge, owner)
        request = asyncio.create_task(bridge._send_and_wait({'action': 'GET_TABS'}, .2))
        try:
            await asyncio.wait_for(owner.packet.wait(), 1)
            rid = owner.sent[-1]['request_id']; pending = bridge._pending[rid]
            assert len(rid) == 32 and bridge._pending_sources[rid] is owner
            for foreign in (None, object()):
                bridge._on_message(json.dumps({'type': 'STATUS', 'request_id': rid}), foreign)
                bridge._on_message(json.dumps({'type': 'MEETING_STATE', 'meeting_tab_open': True}), foreign)
                assert not pending.done() and bridge.meeting_open is None
            bridge._on_message(json.dumps({'type': 'STATUS', 'request_id': rid}), owner)
            assert (await request)['request_id'] == rid
            assert not bridge._pending and not bridge._pending_sources
        finally:
            if not request.done(): request.cancel()
            await stop(owner, handler)
    asyncio.run(scenario())


def test_disconnect_resolves_pending_as_unknown_and_never_retries():
    async def scenario():
        bridge = BrowserBridge(token=TOKEN); bridge.loop = asyncio.get_running_loop()
        owner = Socket(bridge); handler = await start(bridge, owner)
        request = asyncio.create_task(bridge._send_and_wait({'action': 'CONTROL_MEDIA', 'mediaAction': 'TOGGLE'}, 1))
        await asyncio.wait_for(owner.packet.wait(), 1)
        rid = owner.sent[-1]['request_id']
        await stop(owner, handler)
        result = await request
        assert result['outcome'] == 'unknown' and result['reason'] == 'connection_lost'
        next_owner = Socket(bridge, hello(PROFILE_A, SESSION_B)); handler = await start(bridge, next_owner)
        try:
            bridge._on_message(json.dumps({'type': 'STATUS', 'request_id': rid}), owner)
            bridge._on_message(json.dumps({'type': 'STATUS', 'request_id': rid}), next_owner)
            assert not next_owner.sent and len(owner.sent) == 1
            assert not bridge._pending and not bridge._pending_sources
        finally: await stop(next_owner, handler)
    asyncio.run(scenario())


@pytest.mark.parametrize('raw', ['null', '[]', '1', '"text"', '{',
    '{"request_id":[]}', '{"request_id":1}', '{"type":"MEETING_STATE","meeting_tab_open":"true"}',
    '{"type":"MEETING_STATE","meeting_tab_open":true,"meeting_tab_open":false}'])
def test_malformed_runtime_frame_cannot_change_state(raw):
    async def scenario():
        bridge = BrowserBridge(token=TOKEN); owner = Socket(bridge)
        task = await start(bridge, owner)
        try:
            bridge._on_message(raw, owner)
            assert bridge.meeting_open is None and bridge._client is owner
        finally: await stop(owner, task)
    asyncio.run(scenario())


@pytest.mark.parametrize('restart', [False, True])
def test_extension_identity_persists_while_session_rotates(restart):
    result = node_fixture(mode='identity', restartWorker=restart)
    assert result['connected'] and result['socketCount'] == 2
    assert result['first']['profileId'] == result['second']['profileId']
    assert result['first']['sessionId'] != result['second']['sessionId']
    assert result['first']['protocolVersion'] == result['second']['protocolVersion'] == 2
    assert set(result['storageData']) == {'aliceBridgeProfileId'}
    assert all(bridge_module._anonymous_id(value) for value in [result['first']['profileId'], result['first']['sessionId'], result['second']['sessionId']])
    assert [c['value'] for c in result['storageCalls'] if c['operation'] == 'access'] == [{'accessLevel': 'TRUSTED_CONTEXTS'}] * 2


def test_existing_extension_identity_is_reused_without_write():
    result = node_fixture(mode='identity', profileStorage={'aliceBridgeProfileId': PROFILE_A})
    assert result['first']['profileId'] == result['second']['profileId'] == PROFILE_A
    assert not any(c['operation'] == 'set' for c in result['storageCalls'])


@pytest.mark.parametrize('failure', ['access', 'get', 'set', 'readback'])
def test_extension_storage_failure_does_not_connect_with_temporary_id(failure):
    result = node_fixture(mode='identity', storageFailure=failure)
    assert not result['connected'] and result['first'] is None and result['socketCount'] == 0


@pytest.mark.parametrize('stored', ['', None, 'user@example.invalid', 123])
def test_invalid_stored_profile_id_is_not_silently_replaced(stored):
    result = node_fixture(mode='identity', profileStorage={'aliceBridgeProfileId': stored})
    assert not result['connected'] and result['storageData']['aliceBridgeProfileId'] == stored
    assert not any(c['operation'] == 'set' for c in result['storageCalls'])


def test_stale_extension_socket_callbacks_cannot_publish_or_execute():
    result = node_fixture(mode='identity', staleCallbacks=True)
    assert result['socketCount'] == 2 and result['staleMessagesAdded'] == 0


@pytest.mark.parametrize('explicit', [False, True])
def test_sync_dispatch_rechecks_captured_session_after_queue_race(monkeypatch, explicit):
    bridge = BrowserBridge(token=TOKEN)
    old, new = Socket(bridge), Socket(bridge)
    bridge.loop, bridge._client, bridge._connection_id = object(), old, 'connection-a'
    def submit(coroutine, unused_loop):
        bridge._client, bridge._connection_id = new, 'connection-b'
        return SimpleNamespace(result=lambda timeout: asyncio.run(coroutine))
    monkeypatch.setattr(asyncio, 'run_coroutine_threadsafe', submit)
    args = {'expected_connection': 'connection-a'} if explicit else {}
    reply = bridge.send_command('CONTROL_MEDIA', mediaAction='TOGGLE', **args)
    assert reply['reason'] == 'connection_changed' and not old.sent and not new.sent


def test_sync_transport_metadata_is_not_extension_payload(monkeypatch):
    bridge = BrowserBridge(token=TOKEN)
    owner = Socket(bridge, auto_reply=True)
    bridge.loop, bridge._client, bridge._connection_id = object(), owner, 'connection-a'
    def submit(coroutine, unused_loop):
        async def drive():
            bridge.loop = asyncio.get_running_loop()
            return await coroutine
        return SimpleNamespace(result=lambda timeout: asyncio.run(drive()))
    monkeypatch.setattr(asyncio, 'run_coroutine_threadsafe', submit)
    reply = bridge.send_command('GET_TABS')
    assert reply['type'] == 'STATUS' and len(owner.sent) == 1
    assert set(owner.sent[0]) == {'action', 'request_id'}
    assert not bridge._pending and not bridge._pending_sources


def test_sync_timeout_remains_unknown_with_one_packet(monkeypatch):
    bridge = BrowserBridge(token=TOKEN)
    owner = Socket(bridge)
    bridge.loop, bridge._client, bridge._connection_id = object(), owner, 'connection-a'
    def submit(coroutine, unused_loop):
        async def drive():
            bridge.loop = asyncio.get_running_loop()
            return await coroutine
        return SimpleNamespace(result=lambda timeout: asyncio.run(drive()))
    monkeypatch.setattr(asyncio, 'run_coroutine_threadsafe', submit)
    result = bridge.send_command('CONTROL_MEDIA', timeout=.01, mediaAction='TOGGLE')
    assert result['outcome'] == 'unknown' and len(owner.sent) == 1
    assert not bridge._pending and not bridge._pending_sources


def test_stalled_send_expires_and_cleans_pending_before_external_cancel():
    async def scenario():
        bridge = BrowserBridge(token=TOKEN); bridge.loop = asyncio.get_running_loop()
        owner = Socket(bridge); handler = await start(bridge, owner)
        async def stalled_send(raw):
            owner.packet.set()
            await asyncio.Event().wait()
        owner.send = stalled_send
        request = asyncio.create_task(bridge._send_and_wait({'action': 'GET_TABS'}, .01))
        try:
            done, pending = await asyncio.wait({request}, timeout=.2)
            assert done == {request} and not pending
            with pytest.raises(TimeoutError): await request
            assert not bridge._pending and not bridge._pending_sources
        finally:
            if not request.done():
                request.cancel()
                await asyncio.gather(request, return_exceptions=True)
            await stop(owner, handler)
    asyncio.run(scenario())


def test_sync_wait_failure_cancels_submitted_future(monkeypatch):
    bridge = BrowserBridge(token=TOKEN)
    bridge.loop, bridge._client, bridge._connection_id = object(), object(), 'connection-a'
    observed = {'cancelled': False}
    def submit(coroutine, unused_loop):
        def result(timeout): raise TimeoutError('fixture_caller_deadline')
        def cancel():
            observed['cancelled'] = True
            coroutine.close()
        return SimpleNamespace(result=result, cancel=cancel)
    monkeypatch.setattr(asyncio, 'run_coroutine_threadsafe', submit)
    reply = bridge.send_command('GET_TABS')
    assert reply['outcome'] == 'unknown' and observed['cancelled']
