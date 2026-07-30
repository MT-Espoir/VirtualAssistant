
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
