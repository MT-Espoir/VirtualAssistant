"""
Logic THUẦN cho khuôn mặt avatar — không import Tkinter, để test được.

face_spec(state, emotion) trả về mô tả cách vẽ khuôn mặt (màu nền, nhãn trạng thái,
kiểu mắt, kiểu miệng). Phần render (ui/avatar.py) dựa vào mô tả này.
"""

STATES = ("idle", "listening", "thinking", "speaking")
EMOTIONS = ("neutral", "happy", "sad")

# Màu nền + nhãn theo trạng thái
_STATE_STYLE = {
    "idle":      ("#2b2d42", "Sẵn sàng"),
    "listening": ("#1b4965", "Đang nghe..."),
    "thinking":  ("#5a3e2b", "Đang nghĩ..."),
    "speaking":  ("#2d4739", "Đang nói..."),
}

# Kiểu mắt/miệng theo cảm xúc
_EMOTION_FACE = {
    "neutral": {"eyes": "open", "mouth": "neutral"},
    "happy":   {"eyes": "happy", "mouth": "smile"},
    "sad":     {"eyes": "open", "mouth": "frown"},
}


def face_spec(state="idle", emotion="neutral"):
    """Trả về dict mô tả khuôn mặt cho (state, emotion)."""
    if state not in _STATE_STYLE:
        state = "idle"
    if emotion not in _EMOTION_FACE:
        emotion = "neutral"

    bg, label = _STATE_STYLE[state]
    face = dict(_EMOTION_FACE[emotion])

    # Đang nói -> miệng mở (override cảm xúc); đang nghĩ -> mắt "nhìn lên"
    if state == "speaking":
        face["mouth"] = "open"
    elif state == "thinking":
        face["eyes"] = "think"

    return {"bg": bg, "label": label, "eyes": face["eyes"], "mouth": face["mouth"]}


def guess_emotion(text):
    """Đoán cảm xúc đơn giản từ nội dung trả lời (dùng khi LLM chưa gắn nhãn)."""
    t = (text or "").lower()
    if any(k in t for k in ("xin lỗi", "lỗi", "không thể", "không được", "thất bại")):
        return "sad"
    return "happy"
