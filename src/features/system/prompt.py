"""Đoạn prompt riêng của feature `system` (router case "system").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_SYSTEM` (2026-08-25).
Hai hằng ở đây phục vụ hai lượt LLM khác nhau — xem chú thích ở
`ROUTER_HINT` bên dưới.
"""

CASE_SYSTEM = (
    'Yêu cầu thuộc nhóm HỆ THỐNG: mở/đóng app, quản lý cửa sổ, âm lượng, độ sáng, thông tin '
    'máy. Phân biệt: MỞ MỚI một ứng dụng = open_app; còn CHUYỂN sang / đưa ra trước một cửa '
    "sổ ĐANG CHẠY SẴN (vd 'chuyển sang Chrome', 'qua Claude', 'mở lại cửa sổ Word đang mở') "
    "= switch_window; hỏi 'đang mở những gì/cửa sổ nào' = list_windows."
)

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = '- system: mở/đóng ứng dụng, LIỆT KÊ cửa sổ đang mở, CHUYỂN sang một cửa sổ/ứng dụng đang chạy (đưa ra trước), chỉnh âm lượng, độ sáng, xem thông tin máy'
