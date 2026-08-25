"""Đoạn prompt riêng của feature `weather` (router case "weather").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_WEATHER`. `prompt_texts` nhập ngược lại
để `CASES` và `merged()` không đổi một byte.
"""

CASE_WEATHER = (
    'Yêu cầu về THỜI TIẾT. BẮT BUỘC gọi tool get_weather (KHÔNG tự bịa số liệu). Nếu người '
    "dùng có nói địa điểm thì truyền vào 'location', không thì để trống. Đọc lại kết quả tự "
    'nhiên, GIỮ phần khuyến nghị và ghi nguồn.'
)
