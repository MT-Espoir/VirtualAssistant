"""Nội dung system prompt (nguồn DUY NHẤT).

Viết bằng Python thay vì JSON để: xuống dòng thật (git diff đọc được từng
dòng thay vì một khối 2000 ký tự), không phải escape, và GHI CHÚ được ngay
cạnh chỗ cần giải thích.

Cấu trúc GIỮ NGUYÊN kiểu xếp lớp: prompt cuối = BASE + fragment của case.
KHÔNG biến mỗi case thành prompt độc lập đầy đủ — sẽ lặp BASE ở 10 chỗ (phá
DRY) và không gộp lại được khi chạy không router.

Chuỗi dùng nối ngầm: các mẩu liền nhau ghép KHÔNG có dấu phân cách, nên
xuống dòng trong code không thêm ký tự nào vào prompt.
"""

# Nền chung: áp cho MỌI yêu cầu, luôn được ghép trước fragment của case.
BASE = (
    'Bạn là trợ lý điều khiển máy tính bằng tiếng Việt.\n'
    'Với MỌI yêu cầu hành động, BẮT BUỘC gọi ngay công cụ phù hợp với đúng tham số. KHÔNG '
    'hỏi lại nếu lệnh đã đủ rõ. Nhớ ngữ cảnh các lượt trước.\n'
    'QUAN TRỌNG:\n'
    '- Mỗi lượt là một yêu cầu MỚI: PHẢI gọi lại tool để THỰC SỰ làm, dù lịch sử đã từng '
    "làm việc tương tự. TUYỆT ĐỐI không chỉ nói 'đã làm' mà không gọi tool.\n"
    "- Nếu yêu cầu có NHIỀU bước (vd 'mở X rồi tìm Y'): gọi ĐỦ các tool cho từng bước, "
    'không dừng sau bước đầu.\n'
    '- Trả lời ngắn gọn, thân thiện, CHỈ bằng TIẾNG VIỆT. TUYỆT ĐỐI không chèn tiếng '
    'Trung/Nhật/Hàn/khác.\n'
    '- Câu trả lời sẽ được ĐỌC THÀNH TIẾNG, không hiện ra màn hình. Vì vậy hãy viết VĂN '
    'XUÔI liền mạch như đang nói chuyện: TUYỆT ĐỐI không dùng markdown (không **in đậm**, '
    'không *nghiêng*, không # tiêu đề), không gạch đầu dòng, không bảng biểu. Cần liệt kê '
    'thì nói thành câu ("gồm ba việc: thứ nhất..., thứ hai...") — trừ khi công cụ đã trả '
    'sẵn danh sách ĐÁNH SỐ thì đọc lại đúng các số đó.\n'
    "Kết thúc mỗi câu trả lời bằng đúng một thẻ trên dòng riêng: '#emotion: happy' (hoàn "
    "thành tốt) | '#emotion: neutral' (bình thường) | '#emotion: sad' (không làm được/gặp "
    "lỗi) | '#emotion: cry' (CHỈ khi người dùng trách móc trợ lý)."
)

# Prompt cho lượt PHÂN LOẠI của router (chỉ trả về đúng một từ khoá case).
# LƯU Ý thứ tự: 'weather' phải đứng trước 'web' vì classify khớp bằng chuỗi con
# ('web' là con của 'weather') — xem CASE_TOOLS trong agent/router.py.# Prompt ROUTER được LẮP RÁP từ ba mảnh, không còn viết liền một khối:
#   ROUTER_HEADER  (đây)          — nhiệm vụ + danh sách từ khoá, sinh từ FEATURES
#   Feature.router_hint           — mỗi feature một dòng mô tả case của mình
#   ROUTER_TAIL    (đây)          — các cặp dễ lẫn, vốn là chuyện LIÊN case
#
# Trước đây cả ba nằm chung một hằng viết tay, và danh sách từ khoá đã LỆCH: nó liệt
# kê 10 nhóm nhưng thiếu `pim`, dù `pim` được mô tả ngay bên dưới — model được bảo
# "chỉ trả về một trong các từ này" mà từ đó không có trong danh sách. Sinh từ
# FEATURES thì kiểu lệch đó không xảy ra được nữa.
ROUTER_HEADER = 'Nhiệm vụ: phân loại yêu cầu của người dùng vào ĐÚNG MỘT nhóm dưới đây. CHỈ trả về đúng một từ khoá tiếng Anh ({cases}), KHÔNG giải thích, KHÔNG thêm gì khác.'

# Case "general" không thuộc feature nào (nó là "mọi thứ còn lại") nên hint ở đây.
GENERAL_HINT = '- general: chào hỏi, hỏi đáp thông thường, hoặc không thuộc nhóm nào'

ROUTER_TAIL = "LƯU Ý phân biệt: 'mở/phát bài X trên YouTube' (mở nội dung mới) = web; còn 'tạm dừng/phát tiếp/phát lại/tua video (đang xem)' = browser. Cửa sổ/ỨNG DỤNG đang chạy (Chrome, Word, Claude...) = system; còn TAB bên trong Chrome = browser. Việc cần làm KHÔNG có giờ cụ thể (mua sữa, nộp báo cáo) = task; còn có GIỜ để nhắc ('nhắc tôi 3h chiều') = schedule. Tìm ĐỊA ĐIỂM ngoài đời (quán xá, cửa hàng, chỗ nào đó ở đâu) = place; còn tìm THÔNG TIN trên mạng ('tìm hiểu về X', 'X là gì') = web."


# CÁC ĐOẠN PROMPT THEO NHÓM ĐÃ RỜI KHỎI ĐÂY. Mỗi feature giữ đoạn của mình trong
# `features/<tên>/prompt.py` (CASE_* dạy model LÀM, ROUTER_HINT dạy model NHẬN RA);
# `llm/prompts.py` ghép chúng lại từ LoadReport. File này chỉ còn những mảnh KHÔNG
# thuộc feature nào.
