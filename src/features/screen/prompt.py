"""Đoạn prompt riêng của feature `screen` (router case "screen").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_SCREEN`. `prompt_texts` nhập
ngược lại để `CASES` và `merged()` không đổi một byte trong lúc migrate.
"""

CASE_SCREEN = (
    'Yêu cầu thuộc nhóm MÀN HÌNH: chụp, tìm chữ (OCR), cuộn.'
)

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = '- screen: chụp màn hình, tìm chữ trên màn hình, cuộn màn hình'
