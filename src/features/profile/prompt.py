"""Đoạn prompt riêng của feature `profile` (router case "profile").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_PROFILE`. `prompt_texts` nhập
ngược lại để `CASES` và `merged()` không đổi một byte trong lúc migrate.
"""

CASE_PROFILE = (
    'Người dùng cho biết THÔNG TIN CÁ NHÂN. BẮT BUỘC gọi tool remember_about_user, chỉ '
    'truyền đúng (các) trường họ vừa nói: name (tên), address_form (cách xưng hô), location '
    '(nơi ở/địa điểm mặc định), note (điều khác cần nhớ). Nếu note là SỰ KIỆN có thời '
    'điểm (phỏng vấn, cuộc hẹn) thì truyền thêm when dạng ISO, suy từ ngày giờ hiện '
    'tại. Ngược lại, nếu người dùng muốn BỎ một điều đã nhớ thì gọi forget_about_user '
    'với từ khoá. Sau đó xác nhận ngắn gọn, thân '
    'thiện.'
)

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = "- profile: người dùng cho biết THÔNG TIN CÁ NHÂN cần nhớ lâu dài, hoặc bảo trợ lý QUÊN một điều đã nhớ ('quên chuyện... đi', 'đừng nhớ... nữa') — tên ('tôi tên là...'), cách xưng hô ('gọi tôi là...'), nơi ở/địa điểm mặc định ('tôi ở...'), hoặc điều muốn trợ lý ghi nhớ ('nhớ giúp tôi...')"
