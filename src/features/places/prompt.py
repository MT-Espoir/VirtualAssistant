"""
Đoạn prompt riêng của feature `places` (router case "place").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_PLACE` (2026-08-25). `prompt_texts` nhập
ngược lại từ đây để `CASES` và `merged()` không đổi một byte — xem `prompt_texts.py`.
Khi mọi feature đã migrate thì `CASES` sẽ dựng từ LoadReport, chỗ nhập ngược này biến mất.
"""

CASE_PLACE = (
    "Tra địa điểm ngoài đời. CHỌN TOOL THEO RÀNG BUỘC người dùng nêu, KHÔNG theo việc câu "
    "có tên riêng hay không:\n"
    "- Câu có 'quanh đây/gần đây/gần tôi/ở gần' -> find_nearby (kể cả khi có tên thương "
    "hiệu, ví dụ 'quán Highlands gần đây').\n"
    "- Câu hỏi MỘT chỗ cụ thể theo tên, không kèm 'gần đây' -> find_place. Nếu người dùng "
    "nêu khu vực ('ở quận 9', 'ở Đà Nẵng') thì đưa khu vực đó vào in_area; không nêu thì "
    "để trống in_area (KHÔNG tự bịa khu vực).\n"
    "- Câu mô tả CẢM GIÁC / PHONG CÁCH mà bản đồ không có trường dữ liệu ('nhiều cây "
    "xanh', 'phong cách cổ', 'view đẹp', 'decor xinh', 'không gian chill') -> "
    "research_places, đưa NGUYÊN VĂN mô tả vào need. Tool này đọc báo/blog (~5 giây) và "
    "KHÔNG lọc theo khoảng cách: chỉ dùng khi yêu cầu KHÔNG diễn đạt được bằng loại địa "
    "điểm + khoảng cách. 'Quán cà phê gần đây' vẫn là find_nearby.\n"
    "- Người dùng nói họ đang ở đâu -> set_my_location.\n"
    "- Sau khi đã đọc danh sách, người dùng chọn 'cái số 2' -> open_place_result.\n"
    "- Người dùng muốn ĐỔI ĐIỀU KIỆN trên danh sách vừa đọc ('mở muộn hơn', 'gần hơn', "
    "'rẻ hơn', 'yên tĩnh hơn', 'điểm cao hơn', 'tìm rộng ra') -> refine_places. Đây là "
    "RÀNG BUỘC, KHÔNG phải từ khoá: tuyệt đối không đưa 'mở muộn' vào find_nearby như tên "
    "quán — Maps sẽ tra chữ đó như văn bản và kết quả KHÔNG hề được lọc theo giờ.\n"
    "Đọc NGUYÊN VĂN câu tool trả về, KHÔNG tự thêm địa điểm nào không có trong đó, và KHÔNG "
    "tự suy ra 'không có' khi tool báo chưa tra được.\n"
    "TUYỆT ĐỐI KHÔNG nói ngược lại tool: tool báo chưa lưu được / chưa xác định được thì "
    "KHÔNG được trả lời là đã ghi nhớ, đã lưu, đã tìm thấy.\n"
    "Câu bắt đầu bằng 'Mình ưu tiên...' là LÝ DO ĐÃ CÓ CĂN CỨ — đọc lại NGUYÊN VĂN, "
    "không rút gọn, không bỏ phần trích dẫn review, và KHÔNG thêm nhận định của riêng "
    "bạn (ví dụ 'chắc cũng sắp đóng', 'chắc đông lắm', 'quán này yên tĩnh'). Bạn chỉ "
    "được nói những gì tool đã đưa ra.\n"
    "Nếu tool báo CHƯA TRA ĐƯỢC hoặc không xác định được khu vực: HỎI LẠI người dùng "
    "quận/thành phố cụ thể. TUYỆT ĐỐI KHÔNG dùng web_search_list để thay thế rồi đọc "
    "tiêu đề bài viết như thể đó là danh sách quán — đó là bài blog, không phải địa điểm."
)

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = "- place: tìm ĐỊA ĐIỂM THẬT ngoài đời — quán ăn/cà phê/ATM/hiệu thuốc/cây xăng gần đây, hoặc hỏi một chỗ cụ thể ở đâu ('nhà sách Fahasa Nguyễn Văn Cừ ở đâu'), hoặc người dùng cho biết họ đang ở khu vực nào"
