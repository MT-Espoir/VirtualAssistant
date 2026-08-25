"""
Tool của feature `task` — Việc cần làm + thói quen (routine). Hai kho tách nhau, chung một case router.

Chuyển nguyên khối từ `agent/tools.py` (2026-08-25); thân hàm KHÔNG sửa một
dòng nào. `register(reg, ctx)` chỉ là lớp bọc mỏng lấy dependency từ ctx.
"""

from agent.tools import Tool, ToolRegistry



def register(reg, ctx):
    """Đăng ký tool của feature `task` theo đúng thứ tự đăng ký cũ."""
    if ctx.tasks is not None:
        _register_task_tools(reg, ctx.tasks)
    if ctx.routines is not None:
        _register_routine_tools(reg, ctx.routines)


def _register_task_tools(reg: ToolRegistry, tasks):
    """Tool quản lý VIỆC CẦN LÀM (to-do). Khớp việc theo từ khoá trong nội dung; khớp nhiều
    -> hỏi lại, không đoán bừa. remove_task là destructive -> Agent tự hỏi xác nhận."""

    def add_task(text, due=None):
        t = tasks.add(text, due=due)
        if t is None:
            return "Bạn muốn thêm việc gì? Hãy nói nội dung việc cần làm."
        return f'Đã thêm việc: "{t["text"]}".'

    def list_tasks(include_done=False):
        items = tasks.list(include_done=include_done)
        if not items:
            return "Hiện không có việc nào cần làm."
        lines = "\n".join(f'- {"(xong) " if t["done"] else ""}{t["text"]}' for t in items)
        return f"Có {len(items)} việc:\n{lines}"

    def complete_task(keyword):
        matches = [m for m in tasks.find(keyword) if not m["done"]]
        if not matches:
            return f"Không thấy việc nào chưa xong giống '{keyword}'."
        if len(matches) > 1:
            names = ", ".join(f'"{m["text"]}"' for m in matches)
            return f"Có {len(matches)} việc khớp: {names}. Bạn muốn hoàn thành việc nào?"
        tasks.complete(matches[0]["id"])
        return f'Đã đánh dấu xong: "{matches[0]["text"]}".'

    def remove_task(keyword):
        matches = tasks.find(keyword)          # cả việc đã xong cũng xoá được
        if not matches:
            return f"Không thấy việc nào giống '{keyword}'."
        if len(matches) > 1:
            names = ", ".join(f'"{m["text"]}"' for m in matches)
            return f"Có {len(matches)} việc khớp: {names}. Bạn muốn xoá việc nào?"
        removed = tasks.remove(matches[0]["id"])
        return f'Đã xoá việc: "{removed["text"]}".'

    reg.register(Tool(
        name="add_task",
        description="Thêm một việc cần làm (to-do) KHÔNG gắn giờ cụ thể. Dùng khi người dùng "
                    "nói 'thêm việc...', 'ghi chú việc...', 'tôi cần làm...'. (Nếu có GIỜ cụ "
                    "thể để nhắc thì dùng schedule_reminder, không phải tool này.)",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Nội dung việc cần làm"},
                "due": {"type": "string", "description": "Hạn (tuỳ chọn), vd 'thứ 6'"},
            },
            "required": ["text"],
        },
        handler=add_task,
    ))

    reg.register(Tool(
        name="list_tasks",
        description="Liệt kê các việc cần làm. Dùng khi người dùng hỏi 'còn việc gì', "
                    "'việc hôm nay', 'danh sách việc'. Mặc định chỉ việc chưa xong.",
        input_schema={
            "type": "object",
            "properties": {
                "include_done": {"type": "boolean",
                                 "description": "true = liệt kê cả việc đã xong"},
            },
        },
        handler=list_tasks,
        speakable=True,      # danh sách đã định dạng sẵn
    ))

    reg.register(Tool(
        name="complete_task",
        description="Đánh dấu một việc là ĐÃ XONG (không xoá), khớp theo từ khoá trong nội "
                    "dung. Dùng khi người dùng nói 'xong việc...', 'làm xong...', 'hoàn thành...'.",
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Từ khoá nội dung việc, vd 'mua sữa'"},
            },
            "required": ["keyword"],
        },
        handler=complete_task,
    ))

    reg.register(Tool(
        name="remove_task",
        description="Xoá hẳn một việc khỏi danh sách, khớp theo từ khoá. Trợ lý sẽ tự hỏi "
                    "xác nhận trước khi xoá. Dùng khi người dùng nói 'xoá việc...', 'bỏ việc...'.",
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "Từ khoá nội dung việc cần xoá"},
            },
            "required": ["keyword"],
        },
        handler=remove_task,
        destructive=True,
        confirm_message=lambda keyword=None: f"xoá việc '{keyword}'",
    ))


def _register_routine_tools(reg: ToolRegistry, routines):
    """Tool QUẢN LÝ routine (tạo/xem/xoá). Việc CHẠY routine do app.py lo (fast-path)."""

    def create_routine(name, steps):
        r = routines.create(name, steps)
        if r is None:
            return "Routine cần một tên và ít nhất một bước."
        verb = "cập nhật" if r["replaced"] else "tạo"
        return f'Đã {verb} routine "{r["name"]}" gồm {len(r["steps"])} bước.'

    def list_routines():
        items = routines.list()
        if not items:
            return "Chưa có routine nào."
        lines = "\n".join(f'- {r["name"]} ({len(r["steps"])} bước)' for r in items)
        return f"Có {len(items)} routine:\n{lines}"

    def delete_routine(name):
        return (f'Đã xoá routine "{name}".' if routines.delete(name)
                else f"Không thấy routine tên '{name}'.")

    reg.register(Tool(
        name="create_routine",
        description="Tạo một QUY TRÌNH (routine) có tên gồm nhiều bước, để chạy lại bằng một "
                    "câu. Dùng khi người dùng nói 'tạo routine X gồm A, B, C', 'đặt routine...'. "
                    "Tách mỗi việc thành một phần tử trong 'steps' (câu lệnh tiếng Việt).",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên routine, vd 'buổi sáng'"},
                "steps": {"type": "array", "items": {"type": "string"},
                          "description": "Danh sách bước, mỗi bước là một câu lệnh, "
                                         "vd ['mở chrome', 'đọc thời tiết']"},
            },
            "required": ["name", "steps"],
        },
        handler=create_routine,
    ))

    reg.register(Tool(
        name="list_routines",
        description="Liệt kê các routine đã có. Dùng khi người dùng hỏi 'có routine nào', "
                    "'các quy trình của tôi'.",
        input_schema={"type": "object", "properties": {}},
        handler=list_routines,
    ))

    reg.register(Tool(
        name="delete_routine",
        description="Xoá một routine theo tên. Trợ lý sẽ tự hỏi xác nhận trước khi xoá.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên routine cần xoá"},
            },
            "required": ["name"],
        },
        handler=delete_routine,
        destructive=True,
        confirm_message=lambda name=None: f"xoá routine '{name}'",
    ))
