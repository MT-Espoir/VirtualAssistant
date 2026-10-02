"""Đoạn prompt riêng của feature `profile` (router case "profile").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_PROFILE` (2026-08-25).
Hai hằng ở đây phục vụ hai lượt LLM khác nhau — xem chú thích ở
`ROUTER_HINT` bên dưới.
"""

CASE_PROFILE = (
    'Người dùng cho biết THÔNG TIN CÁ NHÂN. BẮT BUỘC gọi tool remember_about_user, chỉ '
    'truyền đúng (các) trường họ vừa nói: name (tên), address_form (cách xưng hô), location '
    '(nơi ở/địa điểm mặc định), note (điều khác cần nhớ). Nếu note là SỰ KIỆN có thời '
    'điểm (phỏng vấn, cuộc hẹn) thì truyền thêm when dạng ISO, suy từ ngày giờ hiện '
    'tại. Nếu người dùng muốn BỎ một điều đã nhớ thì gọi forget_about_user với từ khoá; '
    'nếu muốn XOÁ SẠCH mọi trí nhớ thì gọi manage_user_memory action=delete_all; nếu muốn '
    'xem/sao lưu dữ liệu đã nhớ thì gọi action=export. Sau đó xác nhận ngắn gọn, thân '
    'thiện.'
)

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = "- profile: người dùng cho biết THÔNG TIN CÁ NHÂN cần nhớ lâu dài, bảo trợ lý QUÊN/XÓA dữ liệu đã nhớ, hoặc muốn XUẤT/XEM dữ liệu bộ nhớ — tên ('tôi tên là...'), cách xưng hô ('gọi tôi là...'), nơi ở/địa điểm mặc định ('tôi ở...'), hoặc điều muốn trợ lý ghi nhớ ('nhớ giúp tôi...')"
