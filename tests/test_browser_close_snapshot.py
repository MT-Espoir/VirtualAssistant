"""R0.3 product approval + actual extension worker, without Chrome or providers."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from agent.agent import Agent
from agent.tools import ActionRefused, ToolRegistry
from features.browser.tools import _register_browser_tools
from services.browser_bridge import BrowserBridge
from test_r0_findings import ExtensionFixtureBridge, Records, ScriptLLM, isolated, node_fixture


TABS = [
    {'id': 11, 'title': 'r0 private title', 'url': 'https://r0.example.invalid/a?private=secret', 'windowId': 1},
    {'id': 22, 'title': 'r0 other', 'url': 'https://r0.example.invalid/b', 'windowId': 1},
]
PREVIEW = {'action': 'CLOSE_TAB_BY_KEYWORD', 'keyword': 'r0', 'dryRun': True}
COMMIT = {'action': 'CLOSE_TAB_BY_KEYWORD', 'keyword': 'r0', 'dryRun': False}


def extension(commit_step=None, tabs=None, **kwargs):
    step = {'command': dict(COMMIT), 'previewFrom': 0, **(commit_step or {})}
    return node_fixture(tabs=TABS if tabs is None else tabs, commands=[PREVIEW, step], **kwargs)


def setup_agent(bridge=None):
    bridge, registry, rows = bridge or ExtensionFixtureBridge(), ToolRegistry(), Records()
    _register_browser_tools(registry, bridge)
    agent = Agent(ScriptLLM([SimpleNamespace(name='browser_close_tab', arguments={'keyword': 'r0'}, id='close')]),
                  registry, outcomes=rows)
    return bridge, registry, rows, agent


@pytest.mark.parametrize('channel', ['voice', 'panel'])
def test_both_confirmation_channels_close_only_approved_ids(channel):
    bridge, _, rows, agent = setup_agent()
    agent.run('đóng tab r0')
    bridge.tabs.append(dict(TABS[1]))
    if channel == 'voice':
        reply = agent.run('có').text
    else:
        reply = agent.confirm_pending('yes')
    assert bridge.removed == [11] and [t['id'] for t in bridge.tabs] == [22]
    assert bridge.responses[-1]['closedIds'] == [11]
    assert 'Đã đóng 1 tab' in reply and rows.records[-1]['ket_qua'] == 'xong'
    assert agent.pending is None and agent.confirm_pending('yes') is None


@pytest.mark.parametrize('channel', ['voice', 'panel'])
@pytest.mark.parametrize('change', ['session', 'navigation', 'remove_error'])
def test_confirmed_failures_are_not_recorded_as_done(channel, change):
    bridge, _, rows, agent = setup_agent()
    agent.run('đóng tab r0')
    if change == 'session': bridge.connection_id = 'fixture-connection-b'
    if change == 'navigation': bridge.tabs[0]['url'] = 'https://other.example.invalid/'
    if change == 'remove_error': bridge.fail_ids = [11]
    reply = agent.run('có').text if channel == 'voice' else agent.confirm_pending('yes')
    assert not bridge.removed and 'Đã đóng 1 tab' not in reply
    assert rows.records[-1]['ket_qua'] == 'loi_tool'


@pytest.mark.parametrize('bad_response', [
    {}, None, {'type': 'ERROR', 'message': 'offline'},
    {'type': 'STATUS', 'dryRun': True, 'matched': [{'id': 11}]},
    {'type': 'STATUS', 'dryRun': True, 'tabIds': [], 'targets': [], 'previewToken': 'fake'},
    {'type': 'STATUS', 'dryRun': True, 'tabIds': [11, 11], 'targets': [{'id': 11}, {'id': 11}], 'previewToken': 'fake'},
    {'type': 'STATUS', 'dryRun': True, 'tabIds': [True], 'targets': [{'id': True}], 'previewToken': 'fake'},
])
def test_no_generic_approval_when_preview_is_missing_or_legacy(bad_response):
    class BadBridge:
        connection_id = 'same'
        def send_command(self, **kwargs): return bad_response
    _, _, rows, agent = setup_agent(BadBridge())
    reply = agent.run('đóng tab r0')
    assert agent.pending is None and 'chưa thực hiện' in reply.text.lower()
    assert rows.records[-1]['ket_qua'] == 'loi_tool'


def test_confirmed_flag_without_snapshot_cannot_requery_keyword():
    bridge, registry, _, _ = setup_agent()
    with pytest.raises(ActionRefused): registry.run('browser_close_tab', {'keyword': 'r0'}, confirmed=True)
    assert not bridge.commands and not bridge.removed


@pytest.mark.parametrize('mutation', ['keyword', 'reuse', 'expired', 'refused_after_preview'])
def test_local_ticket_checks_and_existing_refusal_gate(monkeypatch, mutation):
    bridge, registry, _, _ = setup_agent()
    gate = registry.gate('browser_close_tab', {'keyword': 'r0'})
    arguments = dict(gate['arguments'])
    if mutation == 'keyword': arguments['keyword'] = 'other'
    if mutation == 'expired':
        import features.browser.tools as browser_tools
        baseline = browser_tools.time.monotonic()
        monkeypatch.setattr(browser_tools.time, 'monotonic', lambda: baseline + 61)
    if mutation == 'refused_after_preview': registry.get('browser_close_tab').cam = lambda **_: 'blocked'
    if mutation == 'reuse': registry.run('browser_close_tab', arguments, confirmed=True)
    with pytest.raises(ActionRefused): registry.run('browser_close_tab', arguments, confirmed=True)
    assert len(bridge.removed) == (1 if mutation == 'reuse' else 0)


def test_snapshot_capability_not_in_model_schema():
    _, registry, _, _ = setup_agent()
    schema = registry.get('browser_close_tab').spec()['input_schema']
    assert set(schema['properties']) == {'keyword'}


@pytest.mark.parametrize('response', [
    {'type': 'STATUS', 'closedCount': 1},
    {'type': 'STATUS', 'outcome': 'verified', 'readBack': True, 'closedCount': 1, 'closedIds': [99]},
    {'type': 'STATUS', 'outcome': 'verified', 'readBack': True, 'closedCount': 2, 'closedIds': [11]},
])
def test_unbound_or_legacy_reply_never_completes_task(response):
    bridge, registry, _, _ = setup_agent()
    gate = registry.gate('browser_close_tab', {'keyword': 'r0'})
    bridge.send_command = lambda **_: response
    with pytest.raises(RuntimeError) as error:
        registry.run('browser_close_tab', gate['arguments'], confirmed=True)
    assert 'Đã đóng 1 tab' not in str(error.value)


def test_extension_preview_uses_minimal_target_metadata():
    result = extension()
    preview = result['responses'][0]
    assert set(preview) == {'type', 'request_id', 'action', 'dryRun', 'previewToken', 'tabIds', 'targets'}
    assert preview['targets'] == [{'id': 11, 'domain': 'r0.example.invalid'}, {'id': 22, 'domain': 'r0.example.invalid'}]
    assert 'private' not in json.dumps(preview) and 'secret' not in json.dumps(preview)
    assert result['responses'][-1]['outcome'] == 'verified'
    assert result['responses'][-1]['closedIds'] == [11, 22]


@pytest.mark.parametrize('patch', [
    {'url': 'https://other.example.invalid/'}, {'title': 'changed title'},
    {'pendingUrl': 'https://other.example.invalid/'}, {'windowId': 2}, {'incognito': True},
])
def test_preflight_target_drift_stops_every_remove(patch):
    changed = [dict(t) for t in TABS]
    changed[1].update(patch)
    result = extension({'tabs': changed})
    assert result['responses'][-1]['reason'] == 'target_changed'
    assert result['attemptedRemoveIds'] == []


@pytest.mark.parametrize('changeInfo', [{'status': 'loading'}, {'status': 'complete'}, {'url': TABS[1]['url']}])
def test_revision_change_invalidates_even_identical_page(changeInfo):
    result = extension({'events': [{'id': 22, 'changeInfo': changeInfo}]})
    assert result['responses'][-1]['reason'] == 'target_changed' and not result['attemptedRemoveIds']


@pytest.mark.parametrize('kind', ['attached', 'detached', 'replaced'])
def test_tab_lifecycle_event_invalidates_revision(kind):
    result = extension({'events': [{'id': 22, 'kind': kind, 'addedId': 33}]})
    assert result['responses'][-1]['reason'] == 'target_changed' and not result['attemptedRemoveIds']


def test_disappeared_approved_tab_stops_all_instead_of_closing_replacement():
    result = extension({'tabs': [dict(TABS[0]), {'id': 33, 'title': 'r0 replacement', 'url': TABS[1]['url']}]})
    assert result['responses'][-1]['reason'] == 'target_changed'
    assert not result['attemptedRemoveIds']


@pytest.mark.parametrize('ids', [[], [11], [22, 11], [11, 22, 33], [11, 11], ['11', '22']])
def test_extension_rejects_modified_approved_set(ids):
    result = extension({'command': {**COMMIT, 'tabIds': ids}})
    assert result['responses'][-1]['reason'] == 'approval_required'
    assert not result['attemptedRemoveIds']


@pytest.mark.parametrize('changes', [{'previewToken': 'forged'}, {'keyword': 'other'}])
def test_extension_rejects_forged_token_or_changed_keyword(changes):
    result = extension({'command': {**COMMIT, **changes}})
    assert result['responses'][-1]['reason'] == 'approval_required'
    assert not result['attemptedRemoveIds']


def test_legacy_keyword_commit_has_no_side_effect():
    result = node_fixture(tabs=TABS, commands=[COMMIT])
    assert result['responses'][0]['reason'] == 'approval_required'
    assert not result['attemptedRemoveIds']


@pytest.mark.parametrize('elapsed,success', [(59999, True), (60000, False), (60001, False)])
def test_extension_expiry_boundary(elapsed, success):
    result = extension({'advanceMs': elapsed})
    assert bool(result['successfulRemoveIds']) is success


@pytest.mark.parametrize('step', [{'reconnect': True}, {'reopen': True}])
def test_extension_session_change_requires_new_preview(step):
    result = extension(step)
    assert result['responses'][-1]['type'] == 'ERROR' and not result['attemptedRemoveIds']


def test_token_is_consumed_after_error_and_after_success():
    for fail in ([], [11, 22]):
        result = node_fixture(tabs=TABS, failRemoveIds=fail, commands=[PREVIEW,
            {'command': COMMIT, 'previewFrom': 0}, {'command': COMMIT, 'previewFrom': 0}])
        assert result['responses'][-1]['reason'] == 'approval_required'
        assert result['attemptedRemoveIds'] == [11, 22]


def test_concurrent_duplicate_commit_only_executes_once():
    result = extension({'concurrentCopies': 2})
    replies = result['responses'][-1]
    assert sum(r.get('outcome') == 'verified' for r in replies) == 1
    assert sum(r.get('reason') == 'approval_required' for r in replies) == 1
    assert result['attemptedRemoveIds'] == [11, 22]


def test_snapshot_eviction_is_bounded_and_fail_closed():
    result = node_fixture(tabs=TABS, commands=[PREVIEW] * 65 + [{'command': COMMIT, 'previewFrom': 0}])
    assert result['responses'][-1]['reason'] == 'approval_required' and not result['attemptedRemoveIds']


@pytest.mark.parametrize('fail_ids,expected', [([], 'verified'), ([22], 'partial'), ([11, 22], 'failed')])
def test_remove_failures_use_actual_read_back(fail_ids, expected):
    result = extension(failRemoveIds=fail_ids)
    reply = result['responses'][-1]
    assert reply['outcome'] == expected and reply['readBack'] is True
    assert reply['closedCount'] == 2 - len(fail_ids)
    assert reply['closedIds'] == [i for i in [11, 22] if i not in fail_ids]
    assert reply['remainingIds'] == fail_ids and reply['failedIds'] == fail_ids


def test_resolved_remove_without_absence_is_not_closed():
    result = extension(retainRemoveIds=[11, 22])
    reply = result['responses'][-1]
    assert reply['closedCount'] == 0 and reply['remainingIds'] == [11, 22]
    assert reply['outcome'] == 'failed'


@pytest.mark.parametrize('stage', ['preflight', 'readback'])
def test_query_failure_preserves_unknown_result(stage):
    result = extension({'failQueryCalls': [2 if stage == 'preflight' else 3]})
    reply = result['responses'][-1]
    if stage == 'preflight':
        assert reply['reason'] == 'preflight_unavailable' and not result['attemptedRemoveIds']
    else:
        assert reply['outcome'] == 'unknown' and reply['readBack'] is False
        assert reply['closedCount'] == 0 and reply['unknownIds'] == [11, 22]
        assert result['successfulRemoveIds'] == [11, 22]


def test_target_drift_after_preflight_before_remove_stops_action():
    result = extension({'changeOnGet': {'id': 11, 'patch': {'url': 'https://other.example.invalid/'}}})
    assert not result['attemptedRemoveIds'] and result['responses'][-1]['outcome'] == 'failed'


def test_target_drift_between_removes_stops_remaining_targets():
    result = extension({'changeAfterRemove': {'afterId': 11, 'id': 22, 'patch': {'title': 'new content'}}})
    reply = result['responses'][-1]
    assert result['attemptedRemoveIds'] == [11]
    assert reply['outcome'] == 'partial' and reply['closedIds'] == [11] and reply['remainingIds'] == [22]


@pytest.mark.parametrize('current', ['session-b', None])
def test_real_bridge_rechecks_session_before_sending(current):
    async def scenario():
        bridge = BrowserBridge()
        sent = []
        class Socket:
            async def send(self, payload): sent.append(payload)
        bridge.loop = asyncio.get_running_loop()
        bridge._client, bridge._connection_id = Socket(), current
        reply = await bridge._send_and_wait(dict(COMMIT), .1, expected_connection='session-a')
        assert reply['reason'] == 'connection_changed' and not sent
        assert not bridge._pending and not bridge._pending_sources
    asyncio.run(scenario())


def test_bound_bridge_response_ignores_other_socket():
    async def scenario():
        bridge = BrowserBridge()
        other = object()
        class Socket:
            async def send(self, raw):
                rid = json.loads(raw)['request_id']
                bridge._on_message(json.dumps({'type': 'STATUS', 'request_id': rid, 'sender': 'wrong'}), other)
                assert not bridge._pending[rid].done()
                bridge._on_message(json.dumps({'type': 'STATUS', 'request_id': rid, 'sender': 'right'}), self)
        bridge.loop = asyncio.get_running_loop()
        bridge._client, bridge._connection_id = Socket(), 'session-a'
        reply = await bridge._send_and_wait(dict(COMMIT), .1, expected_connection='session-a')
        assert reply['sender'] == 'right' and not bridge._pending and not bridge._pending_sources
    asyncio.run(scenario())
