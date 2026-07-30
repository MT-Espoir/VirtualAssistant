"""Tiện ích THUẦN cho STT (không import thư viện âm thanh) — để test được."""


def whisper_lang_code(language):
    """Chuyển mã ngôn ngữ STT sang mã Whisper.

    Whisper dùng mã ISO 639-1 ('vi'), không nhận dạng khu vực ('vi-VN'). Trả về
    phần trước dấu '-'; rỗng/None -> None để Whisper TỰ nhận diện ngôn ngữ.
    """
    if not language:
        return None
    return language.split("-")[0].strip().lower() or None
