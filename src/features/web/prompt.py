"""Đoạn prompt riêng của feature `web` (router case "web").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_WEB` (2026-08-25).
Hai hằng ở đây phục vụ hai lượt LLM khác nhau — xem chú thích ở
`ROUTER_HINT` bên dưới.
"""

CASE_WEB = (
    'Yêu cầu thuộc nhóm WEB. TRƯỚC HẾT phân biệt HAI Ý ĐỊNH khác nhau — đây là điều quan '
    'trọng nhất của nhóm này:\n'
    "1) CÂU HỎI cần TRẢ LỜI trực tiếp bằng nội dung (vd 'hôm nay có sự kiện gì mà...', "
    "'vì sao...', 'tại sao...', 'X là ai/là gì', 'khi nào...', 'có tin gì về...'): gọi "
    'web_search_list để tìm, RỒI gọi read_search_result (index=1, thử thêm index=2 nếu '
    'bài đầu chưa đủ ý) để ĐỌC NỘI DUNG THẬT của bài viết. Sau khi đọc xong, TRẢ LỜI NGAY '
    'bằng chính nội dung + lý do rút ra từ đó, viết lại bằng lời của bạn. TUYỆT ĐỐI KHÔNG '
    'đọc lại tiêu đề bài viết hay đường link cho người dùng — họ cần câu trả lời, không '
    'cần danh sách. Có thể nói ngắn gọn đã xem qua thông tin trên mạng, nhưng KHÔNG đọc '
    'URL. Nếu nội dung đọc được không đủ để trả lời chắc chắn, nói thật là chưa tìm được '
    'thông tin rõ ràng, đừng bịa.\n'
    "2) Ý ĐỊNH DUYỆT/TỰ CHỌN LINK để mở xem (vd 'tìm giúp tôi vài trang về X để tôi "
    "chọn', 'cho tôi xem có link nào về X'): gọi web_search_list rồi ĐỌC LẠI NGUYÊN VĂN "
    'từng dòng kết quả có ĐÁNH SỐ (số thứ tự + tiêu đề) cho người dùng nghe, hỏi họ muốn '
    'mở số mấy; họ chọn số nào thì gọi open_search_result với index đó. TUYỆT ĐỐI KHÔNG '
    'tóm tắt chung chung kiểu "mình tìm được mấy trang" mà bỏ mất tiêu đề.\n'
    'Không rõ là ý định nào -> mặc định coi là (1), vì hầu hết câu hỏi bằng giọng nói cần '
    'câu trả lời ngay hơn là một danh sách để chọn.\n'
    'Với YouTube (tìm/mở/phát video): dùng play_youtube (phát video đầu tiên) hoặc '
    "search_on_site với site='youtube'. TUYỆT ĐỐI KHÔNG dùng web_search (Google) cho yêu "
    'cầu về YouTube.\n'
    'LƯU Ý: kết quả web_search_list/read_search_result là bài viết trên mạng, KHÔNG phải '
    'danh sách địa điểm có thật. Không được trình bày chúng như thể là quán/cửa hàng '
    'quanh người dùng; muốn tìm địa điểm ngoài đời thì phải dùng find_nearby/find_place.'
)

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = '- web: MỞ MỚI trang web, tìm kiếm Google, tìm/PHÁT một video hoặc bài hát MỚI trên YouTube, tra cứu Wikipedia, đọc trang'
