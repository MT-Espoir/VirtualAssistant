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

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = '- browser: điều khiển video/nhạc ĐANG phát sẵn trên Chrome — tạm dừng, phát tiếp, PHÁT LẠI, tua tới/lùi, chỉnh âm lượng video, chuyển bài kế/trước; hoặc quản lý TAB CHROME (liệt kê/đóng/chuyển tab TRONG Chrome)'
