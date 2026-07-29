"""
Logic THUẦN cho khuôn mặt avatar (màn hình đen trong khung bezel trắng, kiểu
thiết bị robot) — không import Tkinter, để test được.

Khuôn mặt chọn theo POSE, suy ra từ (state, emotion):
  - state == "thinking"  -> luôn là pose "confused" (bối rối), bất kể emotion
  - ngược lại            -> pose = emotion (neutral/happy/sad/cry)
Màn hình luôn nền đen cố định (không đổi màu theo state); state chỉ còn ảnh
hưởng tới việc chọn pose "confused" và nhãn text hiển thị dưới khung bezel.
Cách vẽ từng pose (đường cong/nét cho mắt-miệng) nằm ở ui/avatar.py.
"""

STATES = ("idle", "listening", "thinking", "speaking")
EMOTIONS = ("neutral", "happy", "sad", "cry")
POSES = ("neutral", "happy", "sad", "cry", "confused")

_STATE_LABEL = {
    "idle":      "Sẵn sàng",
    "listening": "Đang nghe...",
    "thinking":  "Đang nghĩ...",
    "speaking":  "Đang nói...",
}


def face_spec(state="idle", emotion="neutral"):
    """Trả về {"pose", "label"} — pose quyết định cách vẽ mắt/miệng."""
    if state not in _STATE_LABEL:
        state = "idle"
    if emotion not in EMOTIONS:
        emotion = "neutral"

    pose = "confused" if state == "thinking" else emotion
    return {"pose": pose, "label": _STATE_LABEL[state]}


def guess_emotion(text):
    """Đoán cảm xúc đơn giản từ nội dung trả lời (dùng khi LLM chưa gắn nhãn)."""
    t = (text or "").lower()
    if any(k in t for k in ("xin lỗi", "lỗi", "không thể", "không được", "thất bại")):
        return "sad"
    return "happy"
