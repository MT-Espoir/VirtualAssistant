"""
Chọn KHUNG HÌNH avatar từ trạng thái + cảm xúc.

Tên trả về là tên file (không đuôi) trong `ui/image/frames/`, do
`packaging/make_avatar_frames.py` sinh ra. Phần thuần, không đụng Tkinter, nên test
được mà không cần màn hình.
"""

STATES = ("idle", "listening", "thinking", "speaking")
EMOTIONS = ("neutral", "happy", "sad", "cry", "shy")

_STATE_LABEL = {
    "idle":      "Sẵn sàng",
    "listening": "Đang nghe...",
    "thinking":  "Đang nghĩ...",
    "speaking":  "Đang nói...",
}

# Khung hình theo TRẠNG THÁI — trợ lý đang làm gì.
#
# `listening` dùng chung khung với `idle`, KHÔNG có khung riêng: trợ lý đứng trong
# `recorder.listen_once()` gần như suốt phiên (xem `app._listen_voice`), nên "đang nghe"
# là trạng thái NGHỈ chứ không phải một khoảnh khắc đáng đánh dấu. Cho nó khung riêng
# thì khung đó chiếm màn hình gần như mãi mãi.
_STATE_FRAME = {
    "idle":      "default",
    "listening": "default",
    "thinking":  "thinking",
    "speaking":  "talk",
}

# Khung hình theo CẢM XÚC, đè lên khung trạng thái. Chỉ những cảm xúc có ảnh RIÊNG mới
# nằm ở đây; happy/neutral không có ảnh riêng nên cứ để trạng thái quyết định.
_EMOTION_FRAME = {
    "sad": "sad",
    "cry": "sad",
    "shy": "shy",
}

# Trạng thái mà cảm xúc KHÔNG được đè lên: đang nghĩ thì việc người dùng cần biết là
# "trợ lý còn bận", quan trọng hơn tâm trạng lúc đó.
_EMOTION_BLIND = ("thinking",)

# Ảnh chớp mắt là MỘT tấm, vẽ đúng tư thế `default`. Đắp nó lên tư thế khác thì nhân
# vật đổi luôn cả dáng tay chứ không chỉ nhắm mắt, nên chỉ tư thế này chớp được.
BLINK_FRAME = "blinking"
BLINK_BASE = "default"


def frame_spec(state="idle", emotion="neutral"):
    """Trả {"frame", "label"} — `frame` là tên khung hình cần hiện."""
    if state not in _STATE_FRAME:
        state = "idle"
    if emotion not in EMOTIONS:
        emotion = "neutral"

    frame = _STATE_FRAME[state]
    if state not in _EMOTION_BLIND:
        frame = _EMOTION_FRAME.get(emotion, frame)
    return {"frame": frame, "label": _STATE_LABEL[state]}


def blink_frame(frame):
    """Khung hình thay thế lúc chớp mắt, hoặc None nếu tư thế này không chớp được.

    Trả tên ảnh kể cả khi ảnh chưa tồn tại: bên gọi (`ui/avatar.py`) chỉ dùng nếu đã
    nạp được ảnh đó, nên thả `blinking_emotion.png` vào rồi bake lại là chớp mắt tự
    chạy, không phải sửa dòng nào.
    """
    return BLINK_FRAME if frame == BLINK_BASE else None


def guess_emotion(text):
    """Đoán cảm xúc đơn giản từ nội dung trả lời (dùng khi LLM chưa gắn nhãn)."""
    t = (text or "").lower()
    if any(k in t for k in ("xin lỗi", "lỗi", "không thể", "không được", "thất bại")):
        return "sad"
    return "happy"
