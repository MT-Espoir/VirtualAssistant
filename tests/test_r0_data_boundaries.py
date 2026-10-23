"""R0.5 negative data-flow tests: actual product sinks, synthetic content only."""
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.tools import Tool, ToolRegistry
from features.salm.storage import SalmStorage
from services.browser_bridge import BrowserBridge, PROTOCOL_VERSION
from utils.debug import DebugBusLogHandler
from utils.events import AssistantBus
from utils.privacy import MetadataLogFormatter
from test_r0_findings import isolated, node_fixture

PRIVATE = 'R05_PRIVATE_TRANSCRIPT_EMAIL_URL_TOKEN'


@pytest.mark.parametrize('key', ['text', 'transcript', 'result', 'output', 'arguments', 'prompt',
    'body', 'title', 'url', 'path', 'exception', 'unknown', PRIVATE])
def test_bus_drops_unlabelled_content_and_unknown_keys(key):
    bus = AssistantBus()
    bus.emit_debug('voice', PRIVATE, {key: PRIVATE, 'duration_ms': 12.5, 'characters': 40})
    event = bus.drain_debug()[0]
    assert PRIVATE not in json.dumps(event)
    assert event['data'] == {'duration_ms': 12.5, 'characters': 40}
    bus.emit(text=PRIVATE)
    assert bus.drain()[0].text == PRIVATE  # Functional UI remains a conversation surface.


@pytest.mark.parametrize('value', [PRIVATE, {'nested': PRIVATE}, [PRIVATE], float('nan'), float('inf'), 10**999])
def test_allowed_field_names_do_not_grant_arbitrary_content(value):
    bus = AssistantBus(); bus.emit_debug(PRIVATE, PRIVATE, {'duration_ms': value, 'emotion': PRIVATE}, level=PRIVATE)
    event = bus.drain_debug()[0]
    assert event['category'] == 'system' and event['level'] == 'INFO'
    assert event['data'] == {} and PRIVATE not in str(event)


def test_registry_sanitizes_before_custom_debug_sink_and_keeps_tool_result():
    events = []; registry = ToolRegistry()
    registry.register(Tool('fixture', '', {}, lambda **_: PRIVATE))
    registry.set_debug_sink(lambda *args, **kwargs: events.append((args, kwargs)))
    assert registry.run('fixture', {'input': PRIVATE}) == PRIVATE
    assert PRIVATE not in str(events)
    assert events[-1][0][2]['event_code'] == 'returned'


def test_log_file_and_panel_do_not_receive_message_args_or_traceback(tmp_path, monkeypatch):
    from utils import logger as module
    path = tmp_path/'diagnostic.log'; monkeypatch.setattr(module.config, 'LOG_FILE', str(path))
    bus = AssistantBus(); panel = DebugBusLogHandler(bus); file = module._file_handler()
    try:
        try: raise ValueError(PRIVATE)
        except ValueError:
            import sys
            record = logging.LogRecord('voice.speech_recognizer', logging.ERROR, __file__, 1,
                                       PRIVATE+' %s', (PRIVATE,), sys.exc_info())
        file.emit(record); panel.emit(record)
        assert record.getMessage().count(PRIVATE) == 2  # Sanitizer does not mutate business record.
    finally: file.close()
    assert PRIVATE not in path.read_text(encoding='utf-8') and PRIVATE not in str(bus.drain_debug())


def test_logger_formatter_does_not_append_exception_or_stack():
    record = logging.LogRecord('app', logging.INFO, __file__, 1, PRIVATE, (), None)
    record.exc_text = PRIVATE; record.stack_info = PRIVATE
    assert PRIVATE not in MetadataLogFormatter('%(message)s').format(record)


def test_product_logger_blocks_content_before_custom_handler(tmp_path):
    from utils.logger import get_logger
    logger = get_logger('voice.privacy_fixture')
    path = tmp_path/'custom.log'; handler = logging.FileHandler(path, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)
    try: logger.error(PRIVATE+' %s', PRIVATE)
    finally:
        logger.removeHandler(handler); handler.close()
    assert PRIVATE not in path.read_text(encoding='utf-8')


def test_worker_tab_list_is_metadata_only():
    result = node_fixture(tabs=[{'id': 11, 'title': PRIVATE, 'url': f'https://example.invalid/x?token={PRIVATE}'}],
                          commands=[{'action': 'GET_TABS'}])
    payload = result['responses'][0]
    assert payload['tabs'] == [{'id': 11, 'domain': 'example.invalid'}]
    assert PRIVATE not in json.dumps(payload)


@pytest.mark.parametrize('action', ['SEARCH_READ', 'MAPS_READ', 'READ_PAGE', PRIVATE])
def test_content_actions_blocked_even_with_self_claimed_permission(action):
    bridge = BrowserBridge(); reply = bridge.send_command(action, consent=True, query=PRIVATE)
    assert reply['reason'] == 'data_scope_not_authorized' and PRIVATE not in str(reply)
    result = node_fixture(commands=[{'action': action, 'consent': True, 'query': PRIVATE}])
    assert result['responses'][0]['reason'] == 'data_scope_not_authorized'
    assert PRIVATE not in str(result['responses'])


def test_protocol_v2_required_for_metadata_worker():
    from test_browser_connection_guard import Socket, hello
    import asyncio
    async def scenario():
        bridge = BrowserBridge(token='guard-fixture-authentication-only')
        socket = Socket(bridge, hello(protocolVersion=1))
        await bridge._handler(socket)
        assert socket.closed and not bridge.connected
    asyncio.run(scenario())
    assert PROTOCOL_VERSION == 2


def test_meeting_page_state_is_not_collected_on_connect():
    result = node_fixture(mode='identity')
    assert set(result['first']) == {'profileId', 'sessionId', 'protocolVersion'}
    # Static permission envelope; functional frame tests use the actual worker.
    manifest = json.loads(Path('chrome_extension/manifest.json').read_text())
    assert all('google.com' not in host and 'duckduckgo' not in host for host in manifest['host_permissions'])


def test_salm_restricted_store_neither_imports_writes_nor_purges_legacy(tmp_path):
    old = tmp_path/'events-2000-01-01.jsonl'; old.write_text(PRIVATE, encoding='utf-8')
    database = Mock()
    storage = SalmStorage(tmp_path, database=database, recording=False)
    storage.append({'text': PRIVATE}); storage.write_daily({'fixture': PRIVATE}); storage.purge_expired()
    assert old.read_text() == PRIVATE and list(tmp_path.iterdir()) == [old]
    assert database.mock_calls == []


def test_actual_runtime_agent_factory_blocks_legacy_learning_sinks(tmp_path):
    import app
    from llm.client import AssistantTurn
    legacy = tmp_path/'memory.json'; legacy.write_text(PRIVATE)
    class LLM:
        def generate(self, **_): return AssistantTurn(text='Fixture response.')
    sink = Mock()
    agent = app._build_release_agent(llm=LLM(), registry=ToolRegistry(), memory_path=str(legacy),
                                    outcomes=sink, habits=sink, auto_extract=True, auto_tune=True)
    for _ in range(12): agent.run(PRIVATE)
    assert agent.stm.path is None and not agent.auto_extract and not agent.auto_tune
    assert agent.outcomes is None and agent.habits is None
    assert sink.mock_calls == [] and legacy.read_text() == PRIVATE


def test_recorder_releases_its_pcm_reference_after_consumption():
    from voice.recorder import Recorder
    recorder = Recorder.__new__(Recorder); recorder.frames = [b'fixture-pcm']
    assert recorder.get_audio_data() == b'fixture-pcm' and recorder.frames == []
    recorder.audio = SimpleNamespace(terminate=lambda: None)


@pytest.mark.parametrize('engine', ['vieneu', 'piper'])
def test_local_tts_failure_does_not_send_text_to_cloud(monkeypatch, engine):
    import voice.speech_synthesizer as module
    synth = module.SpeechSynthesizer.__new__(module.SpeechSynthesizer)
    synth.engine_type, synth._giong_rieng, synth._speak_gen = engine, None, 0
    cloud = Mock(side_effect=AssertionError('cloud must not be used'))
    monkeypatch.setattr(module, 'gTTS', cloud)
    assert synth._gtts_synth(PRIVATE, 0) is None
    cloud.assert_not_called()


def test_failed_local_tts_removes_owned_temporary_wav(tmp_path, monkeypatch):
    import voice.speech_synthesizer as module
    synth = module.SpeechSynthesizer.__new__(module.SpeechSynthesizer)
    def failure(text, path):
        Path(path).write_bytes(b'fixture-audio')
        raise RuntimeError(PRIVATE)
    synth._giong_rieng = SimpleNamespace(san_sang=True, synth_wav=failure)
    original = module.tempfile.NamedTemporaryFile
    monkeypatch.setattr(module.tempfile, 'NamedTemporaryFile', lambda **kwargs: original(dir=tmp_path, **kwargs))
    with pytest.raises(RuntimeError): synth._giong_rieng_synth(PRIVATE)
    assert list(tmp_path.iterdir()) == []


def test_launcher_does_not_redirect_conversation_into_log_file():
    lines = Path('launch_assistant.vbs').read_text(encoding='utf-8').splitlines()
    command = next(line for line in lines if line.startswith('cmd = "cmd /c '))
    assert '> NUL 2>&1' in command and 'logFile' not in command


def test_log_metadata_keeps_allowlisted_numbers_and_drops_content():
    record = logging.LogRecord('llm.gemini', logging.INFO, __file__, 1, PRIVATE, (), None)
    record.diagnostic = {'event_code': 'llm_cache_usage', 'model': 'gemini-3.1-flash-lite',
                         'prompt_tokens': 10, 'cached_tokens': 5, 'text': PRIVATE}
    assert MetadataLogFormatter('%(message)s').format(record) == (
        'llm_cache_usage model=gemini-3.1-flash-lite prompt_tokens=10 cached_tokens=5')
    record.diagnostic = {'event_code': PRIVATE, 'model': PRIVATE}
    assert MetadataLogFormatter('%(message)s').format(record) == 'diagnostic event (content omitted)'
