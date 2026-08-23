"""
Chuẩn hoá văn bản dùng chung (DRY) — bỏ dấu tiếng Việt, thường hoá.

Gom về một chỗ thay vì lặp ở nhiều module; nhờ vậy lỗi kiểu 'đ' chỉ sửa một lần.
"""

import string
import unicodedata


def strip_accents(s):
    """Bỏ dấu tiếng Việt. 'đ'/'Đ' (U+0111/0110) không bị NFD tách nên map tay.

    Map cả 'ð'/'Ð' (U+00F0/00D0 — chữ ETH): nhiều nguồn dữ liệu ngoài dùng nhầm ký tự này
    thay cho 'đ'/'Đ'. Không map thì "Ðà Lạt" (từ Open-Meteo) KHÔNG khớp "Đà Lạt" người
    dùng gõ, dù nhìn y hệt nhau.
    """
    s = (s or "").replace("đ", "d").replace("Đ", "D").replace("ð", "d").replace("Ð", "D")
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def norm(s):
    """Chuẩn hoá để so khớp: thường hoá + bỏ dấu + bỏ dấu câu ở rìa."""
    return strip_accents((s or "").lower()).strip().strip(string.punctuation).strip()
