"""Đoạn prompt riêng của feature `system` (router case "system").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_SYSTEM`. `prompt_texts` nhập ngược lại
để `CASES` và `merged()` không đổi một byte.
"""

CASE_SYSTEM = (
    'Yêu cầu thuộc nhóm HỆ THỐNG: mở/đóng app, quản lý cửa sổ, âm lượng, độ sáng, thông tin '
    'máy. Phân biệt: MỞ MỚI một ứng dụng = open_app; còn CHUYỂN sang / đưa ra trước một cửa '
    "sổ ĐANG CHẠY SẴN (vd 'chuyển sang Chrome', 'qua Claude', 'mở lại cửa sổ Word đang mở') "
    "= switch_window; hỏi 'đang mở những gì/cửa sổ nào' = list_windows."
)
