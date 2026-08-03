"""
Bộ ca kiểm (dataset) cho eval — các yêu cầu đại diện + tool/case mong đợi.

Mỗi ca: {id, text, expect (list tên tool mong đợi; rỗng = KHÔNG nên gọi tool),
          case (case router mong đợi)}.

Đây đo ĐƯỜNG AGENT/LLM (không đi qua fast-path của app.py). Vài lệnh trong thực tế
được fast-path xử lý tất định (âm lượng/media/cuộn/chụp) — ở đây ta cố ý đo xem MODEL
tự chọn đúng tool tới đâu (đường dự phòng khi câu lệ ra ngoài mẫu fast-path).

Thêm ca mới: chỉ cần nối vào CASES. Giữ đa dạng cách nói để đo độ bền thật.
"""

CASES = [
    # --- system ---
    {"id": "sys-vol", "text": "tăng âm lượng lên 50", "expect": ["set_volume"], "case": "system"},
    {"id": "sys-bright", "text": "giảm độ sáng màn hình xuống", "expect": ["set_brightness"], "case": "system"},
    {"id": "sys-open", "text": "mở notepad giúp tôi", "expect": ["open_app"], "case": "system"},
    {"id": "sys-close", "text": "đóng ứng dụng chrome", "expect": ["close_app"], "case": "system"},
    {"id": "sys-info", "text": "máy tôi còn bao nhiêu pin", "expect": ["system_info"], "case": "system"},

    # --- weather ---
    {"id": "wx-today", "text": "thời tiết hôm nay thế nào", "expect": ["get_weather"], "case": "weather"},
    {"id": "wx-rain", "text": "Đà Nẵng hôm nay có mưa không", "expect": ["get_weather"], "case": "weather"},
    {"id": "wx-uv", "text": "tia UV hôm nay có mạnh không", "expect": ["get_weather"], "case": "weather"},

    # --- web ---
    {"id": "web-open", "text": "mở trang vnexpress", "expect": ["open_website"], "case": "web"},
    {"id": "web-search", "text": "tìm thông tin về toeic speaking", "expect": ["web_search_list"], "case": "web"},
    {"id": "web-yt", "text": "phát bài Nơi Này Có Anh trên youtube", "expect": ["play_youtube"], "case": "web"},
    {"id": "web-wiki", "text": "tra cứu Albert Einstein trên wikipedia", "expect": ["wikipedia_lookup"], "case": "web"},

    # --- schedule ---
    {"id": "sch-add", "text": "nhắc tôi họp lúc 3 giờ chiều", "expect": ["schedule_reminder"], "case": "schedule"},
    {"id": "sch-action", "text": "22h30 mở youtube giúp tôi", "expect": ["schedule_action"], "case": "schedule"},
    {"id": "sch-list", "text": "xem các lịch nhắc của tôi", "expect": ["list_reminders"], "case": "schedule"},

    # --- screen ---
    {"id": "scr-shot", "text": "chụp lại màn hình", "expect": ["take_screenshot"], "case": "screen"},
    {"id": "scr-find", "text": "trên màn hình có chữ đăng nhập không", "expect": ["find_on_screen"], "case": "screen"},

    # --- browser (điều khiển media / tab) ---
    {"id": "br-pause", "text": "tạm dừng video trên youtube", "expect": ["browser_media_control"], "case": "browser"},
    {"id": "br-next", "text": "chuyển sang bài tiếp theo", "expect": ["browser_media_control"], "case": "browser"},
    {"id": "br-tabs", "text": "đang mở những tab nào", "expect": ["browser_list_tabs"], "case": "browser"},

    # --- general: KHÔNG nên gọi tool ---
    {"id": "gen-hi", "text": "chào buổi sáng", "expect": [], "case": "general"},
    {"id": "gen-how", "text": "bạn khỏe không", "expect": [], "case": "general"},
    {"id": "gen-thanks", "text": "cảm ơn bạn nhiều nhé", "expect": [], "case": "general"},

    # --- task (việc cần làm, KHÔNG gắn giờ) ---
    {"id": "task-add", "text": "thêm việc mua sữa", "expect": ["add_task"], "case": "task"},
    {"id": "task-list", "text": "còn việc gì cần làm không", "expect": ["list_tasks"], "case": "task"},
    {"id": "task-done", "text": "xong việc mua sữa rồi", "expect": ["complete_task"], "case": "task"},
    {"id": "task-routine", "text": "tạo routine buổi sáng gồm mở chrome và đọc thời tiết",
     "expect": ["create_routine"], "case": "task"},
    # phân biệt: có GIỜ -> schedule, không phải task
    {"id": "task-vs-sch", "text": "nhắc tôi mua sữa lúc 5 giờ chiều",
     "expect": ["schedule_reminder"], "case": "schedule"},

    # --- đa bước ---
    {"id": "multi", "text": "mở notepad rồi tăng âm lượng lên 60",
     "expect": ["open_app", "set_volume"], "case": "system"},
]
