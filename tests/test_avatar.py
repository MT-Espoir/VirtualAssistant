"""
Test logic avatar (ui.avatar_face) + kênh sự kiện (utils.events).

Không import Tkinter / không cần màn hình — chỉ kiểm tra phần thuần.
"""

try:
    import pytest
except ImportError:
    pytest = None

from ui.avatar_face import face_spec, guess_emotion
from utils.events import AssistantBus


# --------------------------- face_spec --------------------------- #

def test_idle_neutral():
    spec = face_spec("idle", "neutral")
    assert spec == {"pose": "neutral", "label": "Sẵn sàng"}


def test_happy_pose():
    assert face_spec("idle", "happy")["pose"] == "happy"


def test_sad_pose():
    assert face_spec("idle", "sad")["pose"] == "sad"


def test_cry_pose():
    assert face_spec("idle", "cry")["pose"] == "cry"


def test_thinking_forces_confused_regardless_of_emotion():
    # state == thinking -> luôn "confused", bất kể emotion đang là gì
    assert face_spec("thinking", "neutral")["pose"] == "confused"
    assert face_spec("thinking", "happy")["pose"] == "confused"
    assert face_spec("thinking", "sad")["pose"] == "confused"
    assert face_spec("thinking", "cry")["pose"] == "confused"


def test_non_thinking_states_use_emotion_as_pose():
    for state in ("idle", "listening", "speaking"):
        assert face_spec(state, "happy")["pose"] == "happy"
        assert face_spec(state, "sad")["pose"] == "sad"


def test_listening_label():
    assert face_spec("listening")["label"] == "Đang nghe..."


def test_unknown_state_defaults_to_idle():
    assert face_spec("khong_biet", "happy") == {"pose": "happy", "label": "Sẵn sàng"}


def test_unknown_emotion_defaults_to_neutral():
    spec = face_spec("idle", "la_lam")
    assert spec["pose"] == "neutral"


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
