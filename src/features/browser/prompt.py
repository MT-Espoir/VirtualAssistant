"""Đoạn prompt riêng của feature `browser` (router case "browser").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_BROWSER`. `prompt_texts` nhập
ngược lại để `CASES` và `merged()` không đổi một byte trong lúc migrate.
"""

CASE_BROWSER = (
    'Yêu cầu thuộc nhóm ĐIỀU KHIỂN CHROME. Điều khiển video/nhạc ĐANG phát (tạm dừng, phát '
    'tiếp, phát lại, tua, chỉnh âm lượng video, bài kế/trước): BẮT BUỘC gọi tool '
    "browser_media_control với 'action' phù hợp "
    "(pause/play/toggle/next/prev/set_volume/seek) — TUYỆT ĐỐI không chỉ trả lời 'đã dừng' "
    'mà không gọi tool. Khi đóng tab (browser_close_tab): BẮT BUỘC gọi confirm=false trước '
    'để xem danh sách tab, đọc cho người dùng và chờ họ đồng ý, chỉ gọi lại confirm=true '
    'sau khi được đồng ý.'
)
