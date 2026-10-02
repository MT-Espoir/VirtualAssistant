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

    # --- quản trị máy (Tầng 1, thêm 2026-09-12) ---
    # Thêm để đo được MA TRẬN NHẦM LẪN của bộ tool quản trị mới (`docs/system_admin_spec.md`
    # §10 mục 9). Rủi ro thật cần đo nằm ở các cặp dễ lẫn, nên chúng được xếp cạnh nhau:
    #   kill_process vs close_app   — "tắt chrome" nghĩa là đóng lịch sự hay giết tiến trình?
    #   list_processes vs system_info — "máy chậm" hỏi CHỈ SỐ hay hỏi AI ĐANG NGỐN?
    #   power(lock) vs power(shutdown) — cùng một tool, khác nhau ở mức khó hoàn tác.
    {"id": "adm-slow", "text": "cái gì đang làm máy tôi chậm thế", "expect": ["list_processes"], "case": "system"},
    {"id": "adm-ram", "text": "ứng dụng nào đang ngốn ram nhất", "expect": ["list_processes"], "case": "system"},
    {"id": "adm-kill", "text": "chrome treo cứng rồi, kết thúc tiến trình chrome đi", "expect": ["kill_process"], "case": "system"},
    {"id": "adm-lock", "text": "khoá màn hình lại giúp tôi", "expect": ["power"], "case": "system"},
    {"id": "adm-shut", "text": "năm phút nữa tắt máy giúp tôi", "expect": ["power"], "case": "system"},
    {"id": "adm-awake", "text": "đừng để máy ngủ, tôi đang tải file", "expect": ["keep_awake"], "case": "system"},
    {"id": "adm-audio", "text": "chuyển âm thanh sang loa ngoài", "expect": ["audio_device"], "case": "system"},

    # --- weather ---
    {"id": "wx-today", "text": "thời tiết hôm nay thế nào", "expect": ["get_weather"], "case": "weather"},
    {"id": "wx-rain", "text": "Đà Nẵng hôm nay có mưa không", "expect": ["get_weather"], "case": "weather"},
    {"id": "wx-uv", "text": "tia UV hôm nay có mạnh không", "expect": ["get_weather"], "case": "weather"},

    # --- place (tra địa điểm) ---
    # Ràng buộc QUYẾT ĐỊNH tool, không phải việc câu có tên riêng hay không.
    {"id": "pl-near", "text": "quanh đây có quán cà phê nào không", "expect": ["find_nearby"], "case": "place"},
    {"id": "pl-near2", "text": "gần đây có hiệu thuốc nào mở cửa không", "expect": ["find_nearby"], "case": "place"},
    {"id": "pl-brand-near", "text": "có quán Highlands nào gần đây không", "expect": ["find_nearby"], "case": "place"},
    {"id": "pl-named", "text": "nhà sách Fahasa Nguyễn Văn Cừ ở đâu", "expect": ["find_place"], "case": "place"},
    {"id": "pl-named-area", "text": "tìm nhà sách Fahasa Nguyễn Văn Cừ ở quận 9", "expect": ["find_place"], "case": "place"},
    {"id": "pl-setloc", "text": "tôi đang ở Cầu Giấy", "expect": ["set_my_location"], "case": "place"},
    # Mô tả CẢM GIÁC/PHONG CÁCH -> research_places. Bản đồ không có trường nào cho những
    # thứ này; ném thẳng vào Maps là vô nghĩa một cách im lặng (Maps ép khớp, không trả rỗng).
    {"id": "pl-research-green", "text": "tìm quán cà phê nhiều cây xanh",
     "expect": ["research_places"], "case": "place"},
    {"id": "pl-research-vintage", "text": "có quán nào phong cách cổ không",
     "expect": ["research_places"], "case": "place"},
    {"id": "pl-research-view", "text": "tìm quán view đẹp để dẫn người yêu đi",
     "expect": ["research_places"], "case": "place"},
    # Ranh giới: "gần đây" + LOẠI thì vẫn là find_nearby, không được đẩy sang research
    # (research đọc web nên chậm hơn hẳn — dùng sai chỗ là phạt độ trễ vô ích).
    {"id": "pl-research-not", "text": "quán cà phê gần đây có chỗ nào không",
     "expect": ["find_nearby"], "case": "place"},
    {"id": "pl-pick", "text": "mở cho tôi chỗ số 2", "expect": ["open_place_result"], "case": "place"},
    # tinh chỉnh trên danh sách vừa đọc — RÀNG BUỘC, không phải từ khoá tìm kiếm
    {"id": "pl-refine-late", "text": "có chỗ nào mở muộn hơn không", "expect": ["refine_places"], "case": "place"},
    {"id": "pl-refine-near", "text": "gần hơn nữa đi", "expect": ["refine_places"], "case": "place"},
    {"id": "pl-refine-cheap", "text": "chỗ nào rẻ hơn không", "expect": ["refine_places"], "case": "place"},
    {"id": "pl-refine-wide", "text": "tìm rộng ra giúp tôi", "expect": ["refine_places"], "case": "place"},
    # dễ nhầm: tra ĐỊA ĐIỂM ngoài đời vs tìm THÔNG TIN trên mạng
    {"id": "pl-vs-web", "text": "tìm hiểu về nhà sách Fahasa", "expect": ["web_search_list"], "case": "web"},
    {"id": "pl-vs-weather", "text": "quanh đây có chỗ nào trú mưa không", "expect": ["find_nearby"], "case": "place"},

    # --- web ---
    {"id": "web-open", "text": "mở trang vnexpress", "expect": ["open_website"], "case": "web"},
    {"id": "web-search", "text": "tìm thông tin về toeic speaking", "expect": ["web_search_list"], "case": "web"},
    {"id": "web-yt", "text": "phát bài Nơi Này Có Anh trên youtube", "expect": ["play_youtube"], "case": "web"},
    {"id": "web-wiki", "text": "tra cứu Albert Einstein trên wikipedia", "expect": ["wikipedia_lookup"], "case": "web"},
    # câu hỏi cần TRẢ LỜI trực tiếp -> phải đọc nội dung (read_search_result), không chỉ
    # liệt kê tiêu đề rồi dừng lại chờ người dùng chọn.
    {"id": "web-question", "text": "hôm nay có sự kiện gì mà Việt Nam lại đi bão",
     "expect": ["web_search_list", "read_search_result"], "case": "web"},
    # Câu hỏi suy ngẫm/ý kiến không cần dữ liệu hiện thời: gọi web vừa chậm vừa phá nhịp nói.
    {"id": "general-love-vs-care", "text": "em nghĩ giữa yêu và thương khác nhau như nào",
     "expect": [], "case": "general"},

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


# Bộ phủ CATALOG — cố ý tách khỏi CASES.
#
# CASES là mẫu đại diện dùng để so độ trễ/tỉ lệ mở nhóm, nên nhân tạo một ca cho mỗi tool
# hiếm sẽ bóp méo phân bố. COVERAGE_CASES trả lời câu hỏi khác: "có tool nào chưa từng
# được model kiểm không?". Chạy riêng bằng `python -m evals.run_eval cov`, hoặc chạy cả hai
# bằng tiền tố `all`. Tool hiếm nhờ vậy không phải chờ người dùng tình cờ gọi ngoài đời.
COVERAGE_CASES = [
    # activity insights — chỉ đọc daily aggregate cục bộ
    {"id": "cov-activity", "text": "cho tôi xem thống kê dùng ứng dụng 7 ngày qua",
     "expect": ["activity_insights"], "case": "activity"},
    # system
    {"id": "cov-network", "text": "máy tôi đang nối Wi-Fi nào và có IP nội bộ bao nhiêu",
     "expect": ["system_info"], "case": "system"},
    {"id": "cov-list-windows", "text": "liệt kê các cửa sổ ứng dụng đang mở",
     "expect": ["list_windows"], "case": "system"},
    {"id": "cov-switch-window", "text": "chuyển sang cửa sổ Visual Studio Code",
     "expect": ["switch_window"], "case": "system"},

    # web — mỗi đường có ý định riêng, tránh để tool cũ bị web_search_list che hết
    {"id": "cov-web-fetch", "text": "đọc và tóm tắt nội dung https://example.com/bai-viet",
     "expect": ["web_fetch"], "case": "web"},
    {"id": "cov-web-search", "text": "tìm từ khoá python dataclass bằng Bing",
     "expect": ["web_search"], "case": "web"},
    {"id": "cov-search-site", "text": "tìm các repository RAG trên GitHub",
     "expect": ["search_on_site"], "case": "web"},
    {"id": "cov-open-result", "text": "mở kết quả tìm kiếm số 2 tôi vừa chọn",
     "expect": ["open_search_result"], "case": "web"},

    # schedule / browser / screen
    {"id": "cov-cancel-reminder", "text": "huỷ lịch nhắc họp lúc 3 giờ chiều",
     "expect": ["cancel_reminder"], "case": "schedule"},
    {"id": "cov-close-tab", "text": "đóng tab trình duyệt hiện tại",
     "expect": ["browser_close_tab"], "case": "browser"},
    {"id": "cov-reuse-tab", "text": "mở GitHub, nếu đã có tab thì dùng lại tab đó",
     "expect": ["browser_open_or_reuse"], "case": "browser"},
    {"id": "cov-scroll", "text": "cuộn màn hình xuống dưới",
     "expect": ["scroll_screen"], "case": "screen"},

    # profile / task
    {"id": "cov-remember", "text": "hãy nhớ rằng tôi dị ứng với đậu phộng",
     "expect": ["remember_about_user"], "case": "profile"},
    {"id": "cov-forget", "text": "hãy quên thông tin tôi dị ứng với đậu phộng",
     "expect": ["forget_about_user"], "case": "profile"},
    {"id": "cov-memory-export", "text": "xuất toàn bộ dữ liệu bộ nhớ của tôi ra file",
     "expect": ["manage_user_memory"], "case": "profile"},
    {"id": "cov-memory-delete", "text": "xóa sạch toàn bộ những gì bạn nhớ về tôi",
     "expect": ["manage_user_memory"], "case": "profile"},
    {"id": "cov-remove-task", "text": "xoá việc mua sữa khỏi danh sách",
     "expect": ["remove_task"], "case": "task"},
    {"id": "cov-list-routines", "text": "liệt kê các routine của tôi",
     "expect": ["list_routines"], "case": "task"},
    {"id": "cov-delete-routine", "text": "xoá routine buổi sáng",
     "expect": ["delete_routine"], "case": "task"},

    # pim / danh bạ
    {"id": "cov-save-contact", "text": "lưu số điện thoại của An là 0901234567",
     "expect": ["save_contact"], "case": "pim"},
    {"id": "cov-find-contact", "text": "tìm số điện thoại của An",
     "expect": ["find_contact"], "case": "pim"},
    {"id": "cov-list-contacts", "text": "liệt kê danh bạ của tôi",
     "expect": ["list_contacts"], "case": "pim"},
    {"id": "cov-remove-contact", "text": "xoá An khỏi danh bạ",
     "expect": ["remove_contact"], "case": "pim"},
]

COVERAGE_CASES += [
    {"id": "cov-iot-environment", "text": "nhiệt độ trong phòng hiện tại bao nhiêu",
     "expect": ["get_room_environment"], "case": "iot"},
    {"id": "cov-iot-ac", "text": "bật máy lạnh trong một giờ",
     "expect": ["control_room_ac"], "case": "iot"},
    {"id": "cov-iot-rule", "text": "khi nhiệt độ trên 32,5 độ C thì bật máy lạnh",
     "expect": ["configure_climate_automation"], "case": "iot"},
    {"id": "cov-camera-off", "text": "tắt webcam",
     "expect": ["turn_off_webcam"], "case": "camera"},
]

ALL_CASES = CASES + COVERAGE_CASES
