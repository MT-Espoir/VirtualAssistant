"""Test ngưỡng thời gian khi nghe (VAD) — chống bug 'bị cắt ngang khi chưa nói xong'.

Ngưỡng phải khai báo bằng GIÂY rồi quy đổi ra chunk theo rate: cùng một số chunk mang ý
nghĩa khác nhau ở mỗi sample rate (1024 chunk = 23ms @44.1kHz nhưng 64ms @16kHz), nên đặt
thẳng số chunk thì ngưỡng im lặng âm thầm ngắn lại và cắt ngang người nói.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytest.importorskip("pyaudio", reason="Thiếu pyaudio")
pytest.importorskip("numpy", reason="Thiếu numpy")

from voice.recorder import Recorder, chunks_for_seconds       # noqa: E402


# --------------------------- quy đổi giây -> chunk --------------------------- #

def test_conversion_at_16khz():
    # 1024 mẫu @16kHz = 64ms/chunk -> 1.5s ~ 23 chunk
    assert chunks_for_seconds(1.5, 16000, 1024) == 23


def test_conversion_at_44khz():
    # cùng 1.5s nhưng @44.1kHz = 23ms/chunk -> ~64 chunk (nhiều hơn hẳn)
    assert chunks_for_seconds(1.5, 44100, 1024) == 64


def test_conversion_scales_with_seconds():
    assert chunks_for_seconds(3.0, 16000, 1024) == 2 * chunks_for_seconds(1.5, 16000, 1024)


def test_conversion_never_zero():
    """Giá trị bé xíu vẫn phải ra >=1 chunk, nếu không vòng nghe sẽ thoát ngay."""
    assert chunks_for_seconds(0.0, 16000, 1024) == 1
    assert chunks_for_seconds(0.001, 16000, 1024) == 1


# --------------------------- listen_once dùng đúng ngưỡng --------------------------- #

def _recorder(**kw):
    """Recorder không đụng phần cứng: bỏ qua hiệu chỉnh nhiễu và mở stream."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Recorder, "calibrate_noise", lambda self, force=False: None)
        mp.setattr("pyaudio.PyAudio", MagicMock())
        return Recorder(rate=16000, chunk=1024, **kw)


def test_default_silence_is_long_enough_for_a_natural_pause():
    """Ngưỡng quá ngắn thì cắt ngang lúc người nói ngắt hơi. Mặc định phải >= 1.2s."""
    rec = _recorder()
    silence_chunks = chunks_for_seconds(rec.silence_duration, rec.rate, rec.chunk)
    assert silence_chunks * rec.chunk / rec.rate >= 1.2


def test_default_max_utterance_allows_a_long_sentence():
    rec = _recorder()
    max_chunks = chunks_for_seconds(rec.max_utterance_s, rec.rate, rec.chunk)
    assert max_chunks * rec.chunk / rec.rate >= 10


def test_silence_duration_is_configurable():
    assert _recorder(silence_duration=3.0).silence_duration == 3.0


def test_listen_once_uses_configured_thresholds():
    """Không truyền gì -> phải lấy ngưỡng đã cấu hình, không phải hằng số cũ."""
    rec = _recorder(silence_duration=2.0, max_utterance_s=20.0)
    seen = {}

    def fake_start():
        seen["max"] = None            # stream None -> listen_once thoát sớm
        rec.stream = None

    rec.start_recording = fake_start
    assert rec.listen_once() is None  # không có stream -> None, không nổ
    assert chunks_for_seconds(rec.silence_duration, rec.rate, rec.chunk) == 31
    assert chunks_for_seconds(rec.max_utterance_s, rec.rate, rec.chunk) == 312


def test_listen_once_accepts_max_seconds_override():
    """Barge-in truyền giây (không phải số chunk thô) — phải chấp nhận và không nổ."""
    rec = _recorder()
    rec.start_recording = lambda: setattr(rec, "stream", None)
    assert rec.listen_once(max_seconds=1.6) is None
