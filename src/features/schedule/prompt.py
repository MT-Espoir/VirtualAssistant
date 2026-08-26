"""Đoạn prompt riêng của feature `schedule` (router case "schedule").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_SCHEDULE` (2026-08-25).
Hai hằng ở đây phục vụ hai lượt LLM khác nhau — xem chú thích ở
`ROUTER_HINT` bên dưới.
"""

CASE_SCHEDULE = (
    "Yêu cầu thuộc nhóm HẸN GIỜ. PHÂN BIỆT: 'nhắc tôi X lúc T' -> schedule_reminder (chỉ "
    "NHẮC, và nói đúng là 'tôi sẽ NHẮC bạn...', ĐỪNG hứa tự làm). Còn 'lúc T hãy "
    "mở/phát/làm Y', '22h30 mở youtube' -> schedule_action với command=Y (trợ lý sẽ TỰ THỰC "
    "THI khi tới giờ). Cả hai dùng 'delay_minutes' (số phút nữa) HOẶC 'at' (giờ HH:MM)."
)

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = "- schedule: hẹn GIỜ cụ thể — đặt/xem/huỷ lời nhắc ('nhắc tôi... lúc...'), HOẶC hẹn trợ lý TỰ LÀM một việc vào giờ đó ('22h30 mở youtube', 'lúc 8h phát nhạc')"
