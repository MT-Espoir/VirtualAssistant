"""Đoạn prompt riêng của feature `schedule` (router case "schedule").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_SCHEDULE`. `prompt_texts` nhập
ngược lại để `CASES` và `merged()` không đổi một byte trong lúc migrate.
"""

CASE_SCHEDULE = (
    "Yêu cầu thuộc nhóm HẸN GIỜ. PHÂN BIỆT: 'nhắc tôi X lúc T' -> schedule_reminder (chỉ "
    "NHẮC, và nói đúng là 'tôi sẽ NHẮC bạn...', ĐỪNG hứa tự làm). Còn 'lúc T hãy "
    "mở/phát/làm Y', '22h30 mở youtube' -> schedule_action với command=Y (trợ lý sẽ TỰ THỰC "
    "THI khi tới giờ). Cả hai dùng 'delay_minutes' (số phút nữa) HOẶC 'at' (giờ HH:MM)."
)
