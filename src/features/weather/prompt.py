"""Đoạn prompt riêng của feature `weather` (router case "weather").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_WEATHER` (2026-08-25).
Hai hằng ở đây phục vụ hai lượt LLM khác nhau — xem chú thích ở
`ROUTER_HINT` bên dưới.
"""

CASE_WEATHER = (
    'Yêu cầu về THỜI TIẾT. BẮT BUỘC gọi tool get_weather (KHÔNG tự bịa số liệu). Nếu người '
    "dùng có nói địa điểm thì truyền vào 'location', không thì để trống. Đọc lại kết quả tự "
    'nhiên, GIỮ phần khuyến nghị và ghi nguồn.'
)

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = '- weather: hỏi thời tiết, trời nắng/mưa, nhiệt độ, khả năng mưa, tia UV'
