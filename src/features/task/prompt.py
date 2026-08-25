"""Đoạn prompt riêng của feature `task` (router case "task").

Chuyển nguyên văn từ `llm/prompt_texts.py::CASE_TASK`. `prompt_texts` nhập
ngược lại để `CASES` và `merged()` không đổi một byte trong lúc migrate.
"""

CASE_TASK = (
    'Yêu cầu thuộc nhóm VIỆC CẦN LÀM hoặc QUY TRÌNH (routine). Việc: add_task để thêm; '
    "list_tasks để xem (mặc định chỉ việc chưa xong); complete_task khi 'xong việc...'; "
    "remove_task khi 'xoá việc...'. Routine: create_routine khi 'tạo routine X gồm A, B, C' "
    "(TÁCH mỗi việc thành một phần tử trong 'steps'); list_routines khi 'có routine nào'; "
    "delete_routine khi 'xoá routine X'. remove_task/delete_routine sẽ tự hỏi xác nhận. "
    'Khớp theo từ khoá.'
)
