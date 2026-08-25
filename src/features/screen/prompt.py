"""Đoạn prompt riêng của feature `screen` (router case "screen").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_SCREEN`. `prompt_texts` nhập
ngược lại để `CASES` và `merged()` không đổi một byte trong lúc migrate.
"""

CASE_SCREEN = (
    'Yêu cầu thuộc nhóm MÀN HÌNH: chụp, tìm chữ (OCR), cuộn.'
)
