"""
Test logic avatar (ui.avatar_face) + kênh sự kiện (core.events).

Không import Tkinter / không cần màn hình — chỉ kiểm tra phần thuần.
"""

try:
    import pytest
except ImportError:
    pytest = None

from ui.avatar_face import face_spec, guess_emotion
from core.events import AssistantBus


# --------------------------- face_spec --------------------------- #

def test_idle_neutral():
    spec = face_spec("idle", "neutral")
    assert spec["label"] == "Sẵn sàng" and spec["mouth"] == "neutral"
    assert spec["bg"].startswith("#")


def test_happy_smiles():
    spec = face_spec("idle", "happy")
    assert spec["mouth"] == "smile" and spec["eyes"] == "happy"


def test_sad_frowns():
    assert face_spec("idle", "sad")["mouth"] == "frown"


def test_speaking_opens_mouth_over_emotion():
    # đang nói -> miệng mở dù cảm xúc gì
    assert face_spec("speaking", "happy")["mouth"] == "open"
    assert face_spec("speaking", "sad")["mouth"] == "open"


def test_thinking_eyes():
    assert face_spec("thinking", "neutral")["eyes"] == "think"


def test_listening_label():
    assert face_spec("listening")["label"] == "Đang nghe..."


def test_unknown_defaults_to_idle_neutral():
    spec = face_spec("khong_biet", "la_lam")
    assert spec["label"] == "Sẵn sàng" and spec["mouth"] == "neutral"


# --------------------------- guess_emotion --------------------------- #

def test_guess_sad_on_error():
    assert guess_emotion("Xin lỗi, có lỗi khi xử lý") == "sad"
    assert guess_emotion("Không thể mở ứng dụng") == "sad"


def test_guess_happy_default():
    assert guess_emotion("Đã mở Chrome cho bạn") == "happy"


# --------------------------- AssistantBus --------------------------- #

def test_bus_emit_and_drain_order():
    bus = AssistantBus()
    bus.emit(state="thinking")
    bus.emit(state="speaking", emotion="happy", text="xong")
    events = bus.drain()
    assert [e.state for e in events] == ["thinking", "speaking"]
    assert events[1].emotion == "happy" and events[1].text == "xong"
    assert bus.drain() == []   # đã rút hết


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
