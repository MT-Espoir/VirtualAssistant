"""R0 release data boundaries. Diagnostics contain metadata, never user content."""
import logging
import math
import re

CATEGORIES = {'system', 'tool', 'llm', 'voice', 'assistant', 'agent', 'activity', 'camera', 'log', 'ui'}
LEVELS = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL', 'SUCCESS'}
NUMERIC_FIELDS = {'duration_ms', 'characters', 'line_breaks', 'blank_line_boundaries', 'iteration',
                  'alternative_count', 'stt_confidence', 'idle_seconds', 'speech_start_seconds',
                  'trailing_silence_seconds', 'peak_rms', 'noise_floor', 'chunk_count', 'sample_rate',
                  'threshold', 'dropped', 'count', 'samples', 'elapsed_ms', 'tool_index',
                  'prompt_tokens', 'cached_tokens', 'cache_hit_percent'}
BOOLEAN_FIELDS = {'confirmed', 'automatic', 'tainted_context', 'proactive', 'ended_by_silence',
                  'hit_max_utterance', 'speaking', 'enabled', 'available'}
STRING_FIELDS = {
    'event_code': {'started', 'returned', 'failed', 'refused', 'awaiting_confirmation',
                   'stt_result', 'tts_input', 'tts_complete', 'llm_turn', 'state_change', 'log_record',
                   'wake_word_missing', 'repeat_required', 'llm_cache_usage'},
    'error_type': {'ValueError', 'RuntimeError', 'TimeoutError', 'OSError', 'PermissionError', 'KeyError'},
    'emotion': {'happy', 'neutral', 'sad', 'angry', 'surprised'},
    'mode': {'sync', 'async', 'runtime', 'offline', 'calibration'},
    'source': {'keyboard', 'microphone', 'synthetic', 'camera'},
    'stt_engine': {'google', 'whisper'},
    'state': {'connected', 'disconnected', 'waiting', 'thinking', 'listening', 'speaking', 'idle'},
    'logger': {'agent', 'features', 'services', 'llm', 'voice', 'utils', 'memory', 'persistence', 'app', 'other'},
}
# Model ids come from operator config, never from conversation content.
_MODEL_ID = re.compile(r'^[a-z0-9][a-z0-9.-]{0,63}$')


def diagnostic_data(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        if key in NUMERIC_FIELDS and type(item) in (int, float):
            try:
                if math.isfinite(item): result[key] = item
            except (ValueError, OverflowError):
                pass
        elif key in BOOLEAN_FIELDS and isinstance(item, bool):
            result[key] = item
        elif key in STRING_FIELDS and isinstance(item, str) and item in STRING_FIELDS[key]:
            result[key] = item
        elif key == 'model' and isinstance(item, str) and _MODEL_ID.match(item):
            result[key] = item
        elif key == 'capture' and isinstance(item, dict):
            result[key] = diagnostic_data(item)
        elif key == 'reason_codes' and isinstance(item, (list, tuple)):
            known = {'audio_cut_at_max_duration', 'dangling_final_word', 'repeated_tail_token',
                     'low_stt_confidence', 'alternatives_disagree'}
            if len(item) <= 5 and all(isinstance(code, str) and code in known for code in item):
                result[key] = list(item)
    return result


def diagnostic_event(category, message=None, data=None, level='INFO'):
    category = category if isinstance(category, str) and category in CATEGORIES else 'system'
    level = level if isinstance(level, str) and level in LEVELS else 'INFO'
    safe = diagnostic_data(data)
    return category, f"{category}: {safe['event_code']}" if 'event_code' in safe else f'{category} event', safe, level


def log_message(record):
    """Render only allowlisted metadata passed as ``extra={'diagnostic': {...}}``."""
    data = diagnostic_data(getattr(record, 'diagnostic', None))
    code = data.pop('event_code', None)
    if code is None:
        return 'diagnostic event (content omitted)'
    return ' '.join([code] + [f'{key}={value}' for key, value in data.items()])


def logger_group(name):
    group = str(name).split('.', 1)[0]
    return group if group in STRING_FIELDS['logger'] else 'other'


class MetadataLogFormatter(logging.Formatter):
    """Do not mutate records shared with functional consumers or other handlers."""
    def format(self, record):
        safe = logging.makeLogRecord(dict(record.__dict__))
        safe.name = logger_group(record.name)
        safe.msg, safe.args = log_message(record), ()
        safe.exc_info = safe.exc_text = safe.stack_info = None
        return super().format(safe)


class MetadataLogFilter(logging.Filter):
    """Protect product logger records before any current/future handler sees them."""
    def filter(self, record):
        record.msg, record.args = log_message(record), ()
        record.exc_info = record.exc_text = record.stack_info = None
        record.name = logger_group(record.name)
        return True


def runtime_learning_bindings():
    """Legacy raw transcript/inferred-learning sinks await consent + R1/R4 contracts."""
    return {'memory_path': None, 'auto_extract': False, 'auto_tune': False,
            'habits': None, 'outcomes': None}
