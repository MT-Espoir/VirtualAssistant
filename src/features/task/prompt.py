"""Đoạn prompt riêng của feature `task` (router case "task").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_TASK` (2026-08-25).
Hai hằng ở đây phục vụ hai lượt LLM khác nhau — xem chú thích ở
`ROUTER_HINT` bên dưới.
"""

CASE_TASK = (
    'Yêu cầu thuộc nhóm VIỆC CẦN LÀM hoặc QUY TRÌNH (routine). Việc: add_task để thêm; '
    "list_tasks để xem (mặc định chỉ việc chưa xong); complete_task khi 'xong việc...'; "
    "remove_task khi 'xoá việc...'. Routine: create_routine khi 'tạo routine X gồm A, B, C' "
    "(TÁCH mỗi việc thành một phần tử trong 'steps'); list_routines khi 'có routine nào'; "
    "delete_routine khi 'xoá routine X'. remove_task/delete_routine sẽ tự hỏi xác nhận. "
    'Khớp theo từ khoá.'
)

# Dòng mô tả case gửi cho BỘ PHÂN LOẠI (prompt ROUTER), khác `CASE_*` ở trên là
# chỉ dẫn gửi cho lượt LÀM VIỆC. Hai vai trò khác nhau nên tách hẳn hai hằng.
ROUTER_HINT = "- task: VIỆC CẦN LÀM không gắn giờ — thêm việc ('thêm việc mua sữa'), xem việc ('còn việc gì', 'việc hôm nay', 'danh sách việc'), đánh dấu xong ('xong việc...'), xoá việc; HOẶC quản lý QUY TRÌNH có tên (routine) — tạo ('tạo routine buổi sáng gồm...'), xem ('có routine nào'), xoá routine"
