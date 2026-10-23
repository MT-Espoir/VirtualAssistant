"""R0.1: desired invariants against production code, without real actuators.

Strict xfail documents currently reproducible defects, not successful fixes.
XPASS after a fix requires reviewing/removing the corresponding marker.
"""
import asyncio
import json
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.agent import Agent
from agent.tools import NeedsConfirmation, Tool, ToolRegistry
from features.browser.tools import _register_browser_tools
from features.iot.tools import register as register_iot
from features.salm.late_night import LateNightPolicyStore
from features.salm.runtime import SalmRuntime
from llm.client import AssistantTurn, ToolCall
from services.browser_bridge import BrowserBridge
from utils.telemetry import use_session


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv('ALICE_TELEMETRY_DIR', raising=False)
    # Windows asyncio creates its own wake-up socketpair. Construct it before
    # denying service connections; no BrowserBridge server is started.
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(asyncio.events, 'new_event_loop', lambda: loop)
    def forbid_network(*args, **kwargs):
        raise AssertionError('R0 reproduction must not connect to real services')
    monkeypatch.setattr(socket.socket, 'connect', forbid_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbid_network)
    try:
        with use_session(None):
            yield
    finally:
        if not loop.is_closed(): loop.close()


class Records:
    database = None
    def __init__(self): self.records = []
    def record(self, value): self.records.append(value)
    def append(self, value): self.records.append(value)


class ScriptLLM:
    def __init__(self, calls):
        self.turns = iter([AssistantTurn(tool_calls=calls), AssistantTurn(text='Fixture response.')])
        self.results = []
    def generate(self, **kwargs):
        self.results.extend(result for msg in kwargs['messages'] for result in msg.tool_results)
        return next(self.turns)


def observe(record_property, finding, **values):
    record_property('finding', finding)
    record_property('observation', json.dumps(values, ensure_ascii=False, sort_keys=True))


def node_fixture(**payload):
    script = Path(__file__).with_name('r0_extension_fixture.cjs')
    result = subprocess.run(['node', str(script)], input=json.dumps(payload),
                            text=True, encoding='utf-8', capture_output=True, timeout=10, check=True)
    return json.loads(result.stdout)


class ExtensionFixtureBridge:
    def __init__(self, fail_ids=()):
        self.tabs = [{'id': 11, 'title': 'r0 fixture', 'url': 'https://r0.example.invalid/one'}]
        self.initial_tabs = [dict(t) for t in self.tabs]
        self.steps = []
        self.connection_id = 'fixture-connection-a'
        self.fail_ids, self.commands, self.removed, self.responses = list(fail_ids), [], [], []
    def send_command(self, **command):
        self.commands.append(dict(command))
        self.steps.append({'command': command, 'tabs': [dict(t) for t in self.tabs]})
        result = node_fixture(tabs=self.initial_tabs, failRemoveIds=self.fail_ids, commands=self.steps)
        self.tabs = result['remainingTabs']
        self.removed = result['successfulRemoveIds']
        self.responses.append(result['responses'][-1])
        return self.responses[-1]


def test_k8_confirmation_does_not_close_new_matching_tab(record_property):
    bridge, rows, registry = ExtensionFixtureBridge(), Records(), ToolRegistry()
    _register_browser_tools(registry, bridge)
    agent = Agent(ScriptLLM([ToolCall('close', 'browser_close_tab', {'keyword': 'r0'})]), registry, outcomes=rows)
    question = agent.run('đóng tab r0').text
    assert agent.pending and not bridge.removed  # The approval gate itself works.
    preview_ids = bridge.responses[0]['tabIds']
    assert preview_ids == [11]
    bridge.tabs.append({'id': 22, 'title': 'r0 new after preview', 'url': 'https://r0.example.invalid/two'})
    agent.run('có')
    observe(record_property, 'K8', confirmed_arguments=bridge.commands[-1],
            removed_ids=bridge.removed, preview_ids=preview_ids, question=question,
            outcome=rows.records[-1]['ket_qua'])
    assert bridge.removed == [11], 'Unpreviewed tab must remain open'


def test_k8_rejected_remove_is_not_counted_as_closed(record_property):
    bridge, registry = ExtensionFixtureBridge(fail_ids=[11]), ToolRegistry()
    _register_browser_tools(registry, bridge)
    gated = registry.gate('browser_close_tab', {'keyword': 'r0'})
    with pytest.raises(RuntimeError) as error:
        registry.run('browser_close_tab', gated['arguments'], confirmed=True)
    phrase = str(error.value)
    observe(record_property, 'K8', reply=phrase, successful_remove_ids=bridge.removed,
            remaining_ids=[tab['id'] for tab in bridge.tabs],
            reported_closed_count=bridge.responses[-1]['closedCount'])
    assert 'Đã đóng 1 tab' not in phrase


def test_k8_unconfirmed_close_still_blocked():
    bridge, registry = ExtensionFixtureBridge(), ToolRegistry()
    _register_browser_tools(registry, bridge)
    with pytest.raises(NeedsConfirmation):
        registry.run('browser_close_tab', {'keyword': 'r0'})
    assert not bridge.removed and all(command['dryRun'] for command in bridge.commands)


def test_k8_rejection_keeps_all_tabs():
    bridge, registry = ExtensionFixtureBridge(), ToolRegistry()
    _register_browser_tools(registry, bridge)
    agent = Agent(ScriptLLM([ToolCall('close', 'browser_close_tab', {'keyword': 'r0'})]), registry)
    agent.run('đóng tab r0')
    agent.run('không')
    assert not bridge.removed and [tab['id'] for tab in bridge.tabs] == [11]


def salm_runtime(policy, rows):
    # No collector, Windows probe or speech engine is started/queried.
    return SalmRuntime('', storage=rows, late_night_policy=policy,
                       power=SimpleNamespace(), windows_probe=SimpleNamespace(),
                       gsmtc=SimpleNamespace(), wasapi=SimpleNamespace())


@pytest.mark.parametrize('text,enabled', [
    ('không bật nhắc khuya lúc 23:30', False),
    ('đừng bật nhắc khuya lúc 23:30', False),
    ('không tắt nhắc khuya', True),
    ('đừng tắt nhắc khuya', True),
])
def test_k10_negation_preserves_policy(text, enabled, tmp_path, record_property):
    path = tmp_path / 'fixture-policy.json'
    policy, rows = LateNightPolicyStore(path), Records()
    if enabled: policy.configure(1410)
    before = policy.snapshot()
    reply = salm_runtime(policy, rows).try_late_night_command(text, now=10,
        at=datetime(2030, 1, 2, 20, tzinfo=timezone(timedelta(hours=7))))
    persisted = LateNightPolicyStore(path).snapshot()
    observe(record_property, 'K10', input=text, before=before, after=policy.snapshot(),
            persisted=persisted, reply=reply, records=rows.records)
    assert policy.snapshot() == before and persisted == before
    assert reply and not rows.records


@pytest.mark.parametrize('text,expected', [
    ('bật nhắc khuya lúc 23:30', True), ('tắt nhắc khuya', False),
])
def test_k10_positive_controls(text, expected, tmp_path):
    policy = LateNightPolicyStore(tmp_path / 'fixture-policy.json')
    salm_runtime(policy, Records()).try_late_night_command(text)
    assert policy.snapshot()['enabled'] is expected
    assert LateNightPolicyStore(policy.path).snapshot()['enabled'] is expected


def test_k10_unrelated_statement_does_not_write(tmp_path):
    path = tmp_path / 'fixture-policy.json'
    policy, rows = LateNightPolicyStore(path), Records()
    assert salm_runtime(policy, rows).try_late_night_command('hôm nay tôi làm việc khuya') is None
    assert not path.exists() and not rows.records


class ProfileSocket:
    def __init__(self, bridge, label, token='fixture-token'):
        self.bridge, self.label, self.token = bridge, label, token
        self.entered, self.queue = asyncio.Event(), asyncio.Queue()
        self.sent, self.closed = [], False
        self.request = SimpleNamespace(headers={'Origin': 'chrome-extension://fixture'})
    async def recv(self):
        return json.dumps({'type': 'HELLO', 'token': self.token, 'protocolVersion': 2,
                           'profileId': '00000000-0000-4000-8000-' + ('000000000001' if self.label == 'A' else '000000000002'),
                           'sessionId': '00000000-0000-4000-8000-' + ('000000000011' if self.label == 'A' else '000000000012')})
    async def send(self, raw):
        payload = json.loads(raw)
        self.sent.append(payload)
        if payload.get('request_id'):
            self.bridge._on_message(json.dumps({'type': 'STATUS', 'success': True,
                                               'request_id': payload['request_id']}), self)
    async def close(self):
        self.closed = True
        self.entered.set()
    def __aiter__(self): return self
    async def __anext__(self):
        self.entered.set()
        value = await self.queue.get()
        if value is None: raise StopAsyncIteration
        return value


def test_k11_two_clients_do_not_redirect_without_selection(record_property):
    async def scenario():
        bridge = BrowserBridge(token='fixture-token')
        bridge.loop = asyncio.get_running_loop()
        a, b = ProfileSocket(bridge, 'A'), ProfileSocket(bridge, 'B')
        tasks = []
        try:
            tasks.append(asyncio.create_task(bridge._handler(a)))
            await asyncio.wait_for(a.entered.wait(), 1)
            tasks.append(asyncio.create_task(bridge._handler(b)))
            await asyncio.wait_for(b.entered.wait(), 1)
            await bridge._send_and_wait({'action': 'CONTROL_MEDIA', 'mediaAction': 'PAUSE'}, .2)
            return {'connected': bridge.connected, 'recipients': [s.label for s in (a,b) if s.sent],
                    'first_socket_closed': a.closed, 'initial_target': 'A',
                    'current_target': 'A' if bridge._client is a else 'B'}
        finally:
            for s in (a,b): s.queue.put_nowait(None)
            await asyncio.gather(*tasks)
    result = asyncio.run(scenario())
    observe(record_property, 'K11', **result)
    assert result['recipients'] == ['A'], 'Initial target must not silently redirect to another client'


def test_k11_extension_hello_identifies_profile(record_property):
    result = node_fixture(mode='hello')
    observe(record_property, 'K11', **result)
    assert 'profile_id' in result['helloKeys'] or 'profileId' in result['helloKeys']
    assert 'sessionId' in result['helloKeys'] and 'protocolVersion' in result['helloKeys']


def test_k11_invalid_token_rejected():
    async def scenario():
        bridge = BrowserBridge(token='fixture-token')
        ws = ProfileSocket(bridge, 'invalid', token='fixture-wrong-token')
        await bridge._handler(ws)
        assert ws.closed and not bridge.connected and not ws.sent
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['disconnected', 'timeout'])
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='K1: bridge ERROR is a normal ToolResult and turn outcome xong')
def test_k1_bridge_error_is_not_success(mode, monkeypatch, record_property):
    bridge = BrowserBridge()
    if mode == 'timeout':
        bridge.loop, bridge._client = object(), object()
        def submit(coroutine, loop):
            coroutine.close()
            def timeout(*args): raise TimeoutError('fixture_timeout_after_send_unknown')
            return SimpleNamespace(result=timeout)
        monkeypatch.setattr(asyncio, 'run_coroutine_threadsafe', submit)
    registry, rows = ToolRegistry(), Records()
    _register_browser_tools(registry, bridge)
    llm = ScriptLLM([ToolCall('media', 'browser_media_control', {'action':'pause'})])
    Agent(llm, registry, outcomes=rows).run('tạm dừng video')
    observe(record_property, 'K1', scenario=mode, tool_is_error=llm.results[0].is_error,
            tool_content=llm.results[0].content, outcome=rows.records[-1]['ket_qua'])
    assert llm.results[0].is_error and rows.records[-1]['ket_qua'] != 'xong'


class IoTFixture:
    def __init__(self, mode): self.mode = mode
    def status(self): raise RuntimeError('fixture_gateway_unavailable')
    def command(self, *args):
        if self.mode == 'exception': raise RuntimeError('fixture_command_unavailable')
        return {'status': 'failed', 'reason': 'fixture_node_failure'}


@pytest.mark.parametrize('mode,name,args', [
    ('exception', 'get_room_environment', {}),
    ('exception', 'control_room_ac', {'action':'off', 'room_id':'fixture-room'}),
    ('payload', 'control_room_ac', {'action':'off', 'room_id':'fixture-room'}),
])
@pytest.mark.xfail(strict=True, raises=AssertionError, reason='K9: IoT failure JSON is normal ToolResult and turn outcome xong')
def test_k9_iot_error_is_not_success(mode, name, args, record_property):
    registry, rows = ToolRegistry(), Records()
    register_iot(registry, SimpleNamespace(iot=IoTFixture(mode)))
    llm = ScriptLLM([ToolCall('iot', name, args)])
    Agent(llm, registry, outcomes=rows).run('fixture IoT request')
    observe(record_property, 'K9', scenario=name + ':' + mode,
            tool_is_error=llm.results[0].is_error, tool_payload=json.loads(llm.results[0].content),
            outcome=rows.records[-1]['ket_qua'])
    assert llm.results[0].is_error and rows.records[-1]['ket_qua'] != 'xong'


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='K9: confirmed IoT failure still closes the turn as xong')
def test_k9_confirmed_error_does_not_finish_successfully(record_property):
    registry, rows = ToolRegistry(), Records()
    register_iot(registry, SimpleNamespace(iot=IoTFixture('exception')))
    call = ToolCall('iot', 'control_room_ac', {'action':'off', 'room_id':'fixture-room'})
    agent = Agent(ScriptLLM([call]), registry, outcomes=rows)
    agent._nhiem = 2  # Persistent action in an existing untrusted context requires approval.
    agent.run('fixture IoT request')
    assert agent.pending and not rows.records
    reply = agent.run('có').text
    observe(record_property, 'K9', scenario='confirmed_control_room_ac', reply=reply,
            outcome=rows.records[-1]['ket_qua'])
    assert rows.records[-1]['ket_qua'] != 'xong'


def test_actual_handler_exception_is_already_an_error():
    def raises(): raise RuntimeError('fixture_handler_exception')
    registry, rows = ToolRegistry(), Records()
    registry.register(Tool('fixture_raises', 'fixture', {}, raises))
    llm = ScriptLLM([ToolCall('raises', 'fixture_raises', {})])
    Agent(llm, registry, outcomes=rows).run('fixture exception')
    assert llm.results[0].is_error and rows.records[-1]['ket_qua'] == 'loi_tool'
