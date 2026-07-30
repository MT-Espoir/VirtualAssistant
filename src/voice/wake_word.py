"""
Từ khoá kích hoạt (wake word) — logic THUẦN, không I/O.
"""

from utils.text_norm import norm as _norm


def parse_wake_words(raw):
    """Chuỗi 'a, b ,c' -> ['a','b','c'] (bỏ khoảng trắng, mục rỗng)."""
    return [w.strip() for w in (raw or "").split(",") if w.strip()]


def match_wake_word(text, wake_words):
    """Tìm từ khoá kích hoạt trong `text` (so khớp theo token, bỏ dấu).

    Trả về (True, phần_còn_lại) nếu khớp — phần còn lại là câu gốc đã bỏ cụm từ
    khoá (giữ nguyên dấu); (False, text.strip()) nếu không khớp.
    """
    orig_tokens = (text or "").split()
    norm_tokens = [_norm(t) for t in orig_tokens]

    for w in wake_words:
        w_tokens = [_norm(t) for t in w.split() if _norm(t)]
        if not w_tokens:
            continue
        n = len(w_tokens)
        for i in range(len(norm_tokens) - n + 1):
            if norm_tokens[i:i + n] == w_tokens:
                remainder = " ".join(orig_tokens[:i] + orig_tokens[i + n:]).strip()
                remainder = remainder.lstrip(",.!?:;- ").strip()
                return True, remainder

    # Không có từ khoá nào được cấu hình -> coi như luôn khớp (tính năng vô hiệu).
    if not wake_words:
        return True, (text or "").strip()
    return False, (text or "").strip()


def wake_words_not_in(text, wake_words):
    """Các wake word KHÔNG xuất hiện trong `text`.
    """
    return [w for w in wake_words if not match_wake_word(text, [w])[0]]
