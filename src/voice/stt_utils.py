"""Tiện ích THUẦN cho STT (không import thư viện âm thanh) — để test được."""


def whisper_lang_code(language):
    """Chuyển mã ngôn ngữ STT sang mã Whisper."""
    if not language:
        return None
    return language.split("-")[0].strip().lower() or None
