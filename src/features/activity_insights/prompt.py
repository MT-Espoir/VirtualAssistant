"""Prompt fragments for Activity Insights queries and explicit user controls."""

CASE_ACTIVITY = (
    "Yêu cầu xem thống kê hoạt động hoặc thời gian dùng ứng dụng của chính người dùng. "
    "BẮT BUỘC gọi tool activity_insights, chọn đúng khoảng thời gian và góc nhìn. "
    "Tóm tắt đúng số liệu tool trả về; nói rõ khi dữ liệu thiếu. Chỉ dùng action ghi "
    "của tool khi người dùng nói rõ app nào thuộc nhóm work/communication/media/"
    "personal, muốn exclude/include/reset app, hoặc muốn xóa activity history. "
    "Không tự đoán category. Không khen/chê chăm chỉ, không khuyên sức khỏe, không suy "
    "diễn stress, deadline, sức khỏe tinh thần hoặc năng suất từ dữ liệu này."
)

ROUTER_HINT = (
    "- activity: thống kê dùng app và activity"
)
