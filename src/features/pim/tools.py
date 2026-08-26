"""
Tool của feature `pim` — Danh bạ cục bộ + lịch/email qua MCP. Hai nguồn, cùng một case router.

Chuyển nguyên khối từ `agent/tools.py` (2026-08-25); thân hàm KHÔNG sửa một
dòng nào. `register(reg, ctx)` chỉ là lớp bọc mỏng lấy dependency từ ctx.
"""

from agent.tools import Tool, ToolRegistry
from utils.logger import get_logger
from utils.text_norm import strip_accents


logger = get_logger(__name__)


def register(reg, ctx):
    """Đăng ký tool của feature `pim` theo đúng thứ tự đăng ký cũ."""
    if ctx.contacts is not None:
        _register_contact_tools(reg, ctx.contacts)
    if ctx.mcp is not None:
        _register_mcp_tools(reg, ctx.mcp)


def _register_contact_tools(reg: ToolRegistry, contacts):
    """Tool SỔ DANH BẠ cục bộ: lưu/tra địa chỉ email theo tên để khỏi phải đọc cả địa chỉ.
    Là nguồn PHỤ — trợ lý tra Google Contacts (gws_contacts_search) trước, không thấy mới
    dùng/lưu sổ này. remove_contact là destructive -> Agent tự hỏi xác nhận."""

    def save_contact(name, email):
        c = contacts.add(name, email)
        if c is None:
            return "Cần cả TÊN và địa chỉ EMAIL để lưu liên hệ."
        return f'Đã lưu liên hệ: {c["name"]} — {c["email"]}.'

    def find_contact(name):
        matches = contacts.find(name)
        if not matches:
            return f"Không thấy liên hệ nào tên '{name}' trong sổ danh bạ."
        lines = "\n".join(f'- {c["name"]}: {c["email"]}' for c in matches)
        return f"Tìm thấy {len(matches)} liên hệ:\n{lines}"

    def list_contacts():
        items = contacts.list()
        if not items:
            return "Sổ danh bạ đang trống."
        lines = "\n".join(f'- {c["name"]}: {c["email"]}' for c in items)
        return f"Có {len(items)} liên hệ:\n{lines}"

    def remove_contact(name):
        matches = contacts.find(name)
        if not matches:
            return f"Không thấy liên hệ nào tên '{name}'."
        if len(matches) > 1:
            names = ", ".join(c["name"] for c in matches)
            return f"Có {len(matches)} liên hệ khớp: {names}. Bạn muốn xoá ai?"
        removed = contacts.remove(matches[0]["id"])
        return f'Đã xoá liên hệ: {removed["name"]}.'

    reg.register(Tool(
        name="save_contact",
        description="Lưu một liên hệ (tên -> email) vào sổ danh bạ để lần sau chỉ cần gọi "
                    "tên. Dùng khi người dùng nói 'lưu liên hệ...', 'số/mail của X là...', "
                    "'ghi nhớ email của...'.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên hoặc biệt danh, vd 'sếp', 'mẹ'"},
                "email": {"type": "string", "description": "Địa chỉ email của liên hệ"},
            },
            "required": ["name", "email"],
        },
        handler=save_contact,
    ))

    reg.register(Tool(
        name="find_contact",
        description="Tra địa chỉ email của một liên hệ đã lưu trong sổ danh bạ CỤC BỘ theo "
                    "tên. Dùng để lấy email trước khi soạn/gửi mail khi người dùng chỉ nói tên.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên liên hệ cần tra, vd 'sếp'"},
            },
            "required": ["name"],
        },
        handler=find_contact,
    ))

    reg.register(Tool(
        name="list_contacts",
        description="Liệt kê toàn bộ liên hệ trong sổ danh bạ cục bộ. Dùng khi người dùng "
                    "hỏi 'danh bạ có ai', 'tôi lưu những liên hệ nào'.",
        input_schema={"type": "object", "properties": {}},
        handler=list_contacts,
        speakable=True,
    ))

    reg.register(Tool(
        name="remove_contact",
        description="Xoá một liên hệ khỏi sổ danh bạ, khớp theo tên. Trợ lý sẽ tự hỏi xác "
                    "nhận trước khi xoá.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên liên hệ cần xoá"},
            },
            "required": ["name"],
        },
        handler=remove_contact,
        destructive=True,
        confirm_message=lambda name=None: f"xoá liên hệ '{name}'",
    ))


def _register_mcp_tools(reg: ToolRegistry, mcp, destructive_keywords=None):
    """Đăng ký mỗi tool của MCP server thành một Tool: handler gọi `mcp.call_tool`. Tool
    GHI (heuristic theo tên: send/create/delete...) đánh dấu destructive -> cổng xác nhận.

    NGOÀI RA: mọi tool mang hình dạng EMAIL đều được gắn `preview` để hiện panel nháp,
    KỂ CẢ tool không destructive: tool LƯU NHÁP không chứa từ khoá GHI nào nên heuristic
    tên xếp nó là "chỉ đọc" -> không cổng, không panel. Mà "viết mail" (chưa gửi) chính là
    lúc người dùng cần nhìn bản nháp nhất. Cột mốc để hiện panel phải là "có nội dung do
    LLM viết ra", không phải "tên tool có chữ send".
    """
    from services.mcp_bridge import is_destructive_tool, DEFAULT_DESTRUCTIVE_KEYWORDS
    from actions.email_draft import email_draft, say_draft
    keywords = destructive_keywords or DEFAULT_DESTRUCTIVE_KEYWORDS

    def _confirm(tool_name):
        """Cụm mô tả để hỏi xác nhận. Lời gọi hình dạng EMAIL được nói bằng tiếng người
        ('gửi email tới sếp...') thay vì đọc tên tool máy móc ('thực hiện gws_gmail_send')."""
        saves_draft = "draft" in tool_name.lower() or "nhap" in strip_accents(tool_name).lower()

        def phrase(**args):
            draft = email_draft(args)
            # Dò tên chỉ để chọn ĐỘNG TỪ ('lưu nháp' vs 'gửi'). Đoán sai làm câu chữ hơi
            # lệch chứ KHÔNG làm mất cổng duyệt — việc chặn do email_draft quyết định.
            return (say_draft(draft, action="draft" if saves_draft else "send")
                    if draft else f"thực hiện '{tool_name}'")
        return phrase

    for spec in mcp.list_tools():
        name = spec["name"]
        if reg.has(name):                          # tránh trùng tên tool sẵn có
            logger.warning("Bỏ qua MCP tool trùng tên: %s", name)
            continue
        destructive = is_destructive_tool(name, keywords)
        reg.register(Tool(
            name=name,
            description=spec.get("description", ""),
            input_schema=spec.get("input_schema") or {"type": "object", "properties": {}},
            handler=(lambda tn: (lambda **kwargs: mcp.call_tool(tn, kwargs)))(name),
            destructive=destructive,
            # Tool MCP trả nội dung LỊCH và EMAIL — do người khác gửi tới, không phải
            # người dùng viết. Đánh dấu ở đây (chứ không liệt kê tên) vì tool MCP sinh
            # động theo server: server thêm tool mới thì nó tự được bọc.
            untrusted_output=True,
            confirm_message=_confirm(name),
            # Gắn cho MỌI tool: tool không mang hình dạng email thì email_draft trả None
            # -> không panel, không cổng, luồng y như cũ.
            preview=lambda **a: email_draft(a),
        ))
