"""Đoạn prompt riêng của feature `pim` (router case "pim").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_PIM`. `prompt_texts` nhập
ngược lại để `CASES` và `merged()` không đổi một byte trong lúc migrate.
"""

CASE_PIM = (
    'Yêu cầu về LỊCH, EMAIL hoặc DANH BẠ (qua công cụ MCP của Google + sổ danh bạ cục bộ).\n'
    'GIẢI TÊN NGƯỜI NHẬN: nếu người dùng nói TÊN thay vì địa chỉ email (vd "gửi cho sếp"), '
    'TRƯỚC KHI soạn/gửi hãy tra địa chỉ: gọi gws_contacts_search (Google Contacts) TRƯỚC; '
    'nếu không có kết quả thì gọi find_contact (sổ cục bộ). Không thấy ở cả hai -> HỎI LẠI '
    'địa chỉ, đừng bịa. Khi người dùng cung cấp email mới cho một cái tên, dùng '
    'save_contact để nhớ.\n'
    'SOẠN NỘI DUNG MAIL: khi người dùng chỉ nêu Ý ĐỊNH (vd "xin nghỉ phép", "cảm ơn sau '
    'buổi họp"), hãy TỰ VIẾT nội dung hoàn chỉnh: có lời chào đầu, thân bài rõ ý, lời chào '
    'cuối và ký tên người dùng nếu biết. Chọn văn phong theo ngữ cảnh: TRANG TRỌNG với '
    'sếp/đối tác/thầy cô (kính gửi, ạ), THÂN MẬT với bạn bè. Suy ra tiêu đề ngắn gọn nếu '
    'người dùng không nêu. Không bịa thông tin chưa có (ngày giờ, tên) — thiếu thì hỏi lại.\n'
    'GỬI hay LƯU NHÁP: nếu người dùng muốn xem lại/sửa trước thì dùng công cụ LƯU NHÁP '
    '(không gửi ra ngoài); nếu muốn gửi luôn thì dùng công cụ GỬI. Khi chưa rõ, ưu tiên LƯU '
    'NHÁP.\n'
    'VIẾT MAIL — QUAN TRỌNG NHẤT: khi người dùng bảo bạn VIẾT/SOẠN một email (vd "viết mail '
    'xin hướng dẫn đồ án", "soạn mail cảm ơn"), BẮT BUỘC gọi công cụ mail (LƯU NHÁP nếu họ '
    'chưa bảo gửi) với nội dung thư đã viết đầy đủ trong tham số body. TUYỆT ĐỐI KHÔNG đọc '
    'nội dung thư ra thành lời rồi dừng lại mà không gọi công cụ nào — người dùng cần NHÌN '
    'lá thư, không phải nghe nó.\n'
    'CHƯA BIẾT NGƯỜI NHẬN thì VẪN gọi công cụ, để trống tham số người nhận rồi hỏi họ gửi '
    'cho ai ở câu trả lời. TUYỆT ĐỐI KHÔNG vì thiếu địa chỉ mà bỏ luôn việc gọi công cụ — '
    'thiếu địa chỉ vẫn soạn được thư, và người dùng cần thấy thư trước đã. Chỉ đừng BỊA ra '
    'một địa chỉ email không có thật.\n'
    'Trợ lý sẽ TỰ hiện bản nháp lên một panel cho người dùng ĐỌC BẰNG MẮT và tự hỏi xác '
    'nhận trước khi thư được gửi/lưu — bạn KHÔNG cần đọc lại toàn bộ nội dung thư thành '
    'lời, cũng đừng hỏi "bạn có muốn tôi gửi không?" rồi ngồi chờ mà không gọi công cụ. '
    'Phần xác nhận đã có cơ chế riêng lo.'
)
