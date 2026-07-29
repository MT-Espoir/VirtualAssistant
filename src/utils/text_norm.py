"""
Chuẩn hoá văn bản dùng chung (DRY) — bỏ dấu tiếng Việt, thường hoá.

Gom về một chỗ thay vì lặp ở nhiều module; nhờ vậy lỗi kiểu 'đ' chỉ sửa một lần.
"""

import string
import unicodedata


def strip_accents(s):
    """Bỏ dấu tiếng Việt. 'đ'/'Đ' (U+0111/0110) không bị NFD tách nên map tay."""
    s = (s or "").replace("đ", "d").replace("Đ", "D")
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def norm(s):
    """Chuẩn hoá để so khớp: thường hoá + bỏ dấu + bỏ dấu câu ở rìa."""
    return strip_accents((s or "").lower()).strip().strip(string.punctuation).strip()
