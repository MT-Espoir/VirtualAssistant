"""
Test logic avatar (ui.avatar_face) + kênh sự kiện (utils.events).

Không import Tkinter / không cần màn hình — chỉ kiểm tra phần thuần.
"""

try:
    import pytest
except ImportError:
    pytest = None

from ui.avatar_face import BLINK_BASE, BLINK_FRAME, blink_frame, frame_spec, guess_emotion
from utils.events import AssistantBus


# --------------------------- frame_spec --------------------------- #

def test_idle_neutral():
    assert frame_spec("idle", "neutral") == {"frame": "default", "label": "Sẵn sàng"}


def test_happy_dung_chung_khung_voi_neutral():
    # Chưa có ảnh riêng cho "vui" -> vẫn là khung của trạng thái, không rơi vào khung lạ.
    assert frame_spec("idle", "happy")["frame"] == "default"


def test_sad_va_cry_dung_khung_sad():
    assert frame_spec("idle", "sad")["frame"] == "sad"
    assert frame_spec("idle", "cry")["frame"] == "sad"


def test_moi_trang_thai_mot_khung():
    assert frame_spec("thinking")["frame"] == "thinking"
    assert frame_spec("speaking")["frame"] == "talk"


def test_listening_dung_chung_khung_voi_idle():
    # Trợ lý đứng chờ mic gần như suốt phiên -> "đang nghe" là mặt nghỉ, không phải
    # một khung riêng chiếm màn hình mãi.
    assert frame_spec("listening")["frame"] == frame_spec("idle")["frame"]


def test_thinking_khong_bi_cam_xuc_de_len():
    # Đang nghĩ thì phải thấy là còn bận, bất kể tâm trạng.
    for emotion in ("neutral", "happy", "sad", "cry"):
        assert frame_spec("thinking", emotion)["frame"] == "thinking"


def test_cam_xuc_de_len_cac_trang_thai_con_lai():
    for state in ("idle", "listening", "speaking"):
        assert frame_spec(state, "sad")["frame"] == "sad"


def test_listening_label():
    assert frame_spec("listening")["label"] == "Đang nghe..."


def test_trang_thai_la_thi_ve_idle():
    assert frame_spec("khong_biet", "happy") == {"frame": "default", "label": "Sẵn sàng"}


def test_cam_xuc_la_thi_ve_neutral():
    assert frame_spec("idle", "la_lam")["frame"] == "default"


# --------------------------- blink_frame --------------------------- #

def test_chi_tu_the_goc_moi_chop_mat():
    assert blink_frame(BLINK_BASE) == BLINK_FRAME
    for frame in ("sad", "shy", "talk", "thinking"):
        assert blink_frame(frame) is None


def test_chop_mat_khai_bao_ca_khi_chua_co_anh():
    # Hàm chỉ nói "tư thế này chớp được bằng ảnh nào"; có ảnh hay chưa là việc của
    # ui.avatar. Nhờ vậy thả ảnh vào + bake lại là chớp mắt chạy, không phải sửa code.
    assert blink_frame(frame_spec("idle", "neutral")["frame"]) == BLINK_FRAME


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
