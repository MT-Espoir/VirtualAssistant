"""
Tool của feature `pim` — Danh bạ cục bộ + lịch/email qua MCP. Hai nguồn, cùng một case router.

Chuyển nguyên khối từ `agent/tools.py` (2026-08-25); thân hàm KHÔNG sửa một
dòng nào. `register(reg, ctx)` chỉ là lớp bọc mỏng lấy dependency từ ctx.
"""

import re

from agent.tools import Tool, ToolRegistry
from utils.logger import get_logger
from utils.text_norm import strip_accents


logger = get_logger(__name__)

# Tham chiếu tượng trưng cho ĐỊA CHỈ EMAIL của một liên hệ. Model chỉ thấy chuỗi này;
# địa chỉ thật được thay ở tầng runtime ngay trước khi gọi tool.
#
# Email của NGƯỜI KHÁC là dữ liệu bên thứ ba: bạn tự quyết được cho mình, không quyết
# thay họ được. Nên nó không được phép nằm trong ngữ cảnh gửi sang nhà cung cấp LLM chỉ
# vì người dùng lỡ hỏi "danh bạ có ai".
THAM_CHIEU_LIEN_HE = "@lienhe:"


def giai_lien_he(gia_tri, contacts):
    """'@lienhe:Sếp' -> địa chỉ email thật. Không phải tham chiếu -> trả nguyên văn.

    Tra không ra cũng trả nguyên văn: chuỗi "@lienhe:X" không phải địa chỉ hợp lệ nên
    lệnh gửi sẽ hỏng rõ ràng — hư theo chiều AN TOÀN, hơn là đoán bừa một người nhận.
    """
    if not isinstance(gia_tri, str) or not gia_tri.startswith(THAM_CHIEU_LIEN_HE):
        return gia_tri
    ten = gia_tri[len(THAM_CHIEU_LIEN_HE):].strip()
    khop = contacts.find(ten) if contacts is not None else []
    if len(khop) != 1:                      # 0 = không có; >1 = mơ hồ, đừng đoán
        return gia_tri
    return khop[0]["email"]


def giai_tham_chieu(args, contacts):
    """Thay mọi tham chiếu liên hệ trong tham số một lời gọi tool. Hàm thuần."""
    return {k: giai_lien_he(v, contacts) for k, v in (args or {}).items()}


def la_nguoi_nhan_la(dia_chi, contacts):
    """Địa chỉ này CHƯA TỪNG có trong danh bạ? Hàm thuần theo `contacts`.

    Không có danh bạ -> False: khi chưa có gì để so thì mọi địa chỉ đều "lạ", và cảnh báo
    kêu ở mọi lần gửi sẽ bị bào mòn thành tiếng ồn trước khi kịp cứu ai.
    """
    dia_chi = (dia_chi or "").strip().lower()
    if not dia_chi or contacts is None:
        return False
    try:
        da_biet = {(c.get("email") or "").strip().lower() for c in contacts.list()}
    except Exception:
        return False
    if not da_biet:
        return False
    return not any(e and e in dia_chi for e in da_biet)


def register(reg, ctx):
    """Đăng ký tool của feature `pim` theo đúng thứ tự đăng ký cũ."""
    if ctx.contacts is not None:
        _register_contact_tools(reg, ctx.contacts)
    if ctx.mcp is not None:
        _register_mcp_tools(reg, ctx.mcp, ctx.contacts)
        # Chỉ có nghĩa khi server MCP thật sự cung cấp tool đọc thư VÀ có màn hình để vẽ.
        # Kiểm bằng `reg.has` thay vì tin server nào cũng giống nhau — đổi server khác là
        # tool này tự vắng mặt, thay vì đăng ký rồi nổ lúc chạy.
        if ctx.bus is not None and reg.has(_TEN_TOOL_DOC) and reg.has(_TEN_TOOL_TIM):
            _register_show_mail(reg, ctx.mcp, ctx.bus)


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
        if len(matches) > 1:
            ten = ", ".join(c["name"] for c in matches)
            return f"Có {len(matches)} liên hệ khớp: {ten}. Bạn muốn ai?"
        # KHÔNG trả địa chỉ thật — trả THAM CHIẾU. Địa chỉ chỉ hiện hình ở tầng runtime
        # ngay lúc gọi tool gửi mail, và trên panel để người dùng kiểm bằng mắt.
        c = matches[0]
        return (f"Có liên hệ '{c['name']}'. Khi gửi mail, điền người nhận là "
                f"'{THAM_CHIEU_LIEN_HE}{c['name']}' — hệ thống tự thay bằng địa chỉ thật.")

    def list_contacts():
        items = contacts.list()
        if not items:
            return "Sổ danh bạ đang trống."
        # CHỈ TÊN, không địa chỉ: câu hỏi "danh bạ có ai" không đáng giá bằng việc đổ
        # email của tất cả người quen vào ngữ cảnh rồi gửi sang nhà cung cấp LLM.
        ten = ", ".join(c["name"] for c in items)
        return f"Có {len(items)} liên hệ: {ten}."

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
        persistent=True,
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


def _register_mcp_tools(reg: ToolRegistry, mcp, contacts=None, destructive_keywords=None):
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
            # GIẢI tham chiếu trước khi hỏi: người dùng phải nghe/nhìn ĐỊA CHỈ THẬT để
            # kiểm, chứ không phải chuỗi '@lienhe:Sếp' vô nghĩa với họ. Model thấy tham
            # chiếu, người dùng thấy sự thật — đúng chiều của cả hai bên.
            args = giai_tham_chieu(args, contacts)
            draft = email_draft(args)
            if draft and la_nguoi_nhan_la(draft.get("to"), contacts):
                # Gửi tới địa chỉ CHƯA TỪNG thấy chính là chữ ký của rò rỉ dữ liệu. Đánh
                # đúng ca tấn công thay vì làm phiền đều mọi lần gửi — người nhận quen thì
                # câu hỏi vẫn như cũ, nên cảnh báo này không bị bào mòn vì nghe mãi.
                return "⚠ gửi tới địa chỉ LẠ (chưa từng có trong danh bạ) — " + \
                       say_draft(draft, action="draft" if saves_draft else "send")
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
            handler=(lambda tn: (lambda **kwargs:
                                 mcp.call_tool(tn, giai_tham_chieu(kwargs, contacts))))(name),
            destructive=destructive,
            # Tool MCP trả nội dung LỊCH và EMAIL — do người khác gửi tới, không phải
            # người dùng viết. Đánh dấu ở đây (chứ không liệt kê tên) vì tool MCP sinh
            # động theo server: server thêm tool mới thì nó tự được bọc.
            untrusted_output=True,
            confirm_message=_confirm(name),
            # Gắn cho MỌI tool: tool không mang hình dạng email thì email_draft trả None
            # -> không panel, không cổng, luồng y như cũ.
            preview=lambda **a: email_draft(giai_tham_chieu(a, contacts)),
        ))


# --------------------------- HIỆN thư lên màn hình --------------------------- #

_TEN_TOOL_DOC = "gws_gmail_read"        # tool MCP dùng để lấy nội dung một lá thư
_TEN_TOOL_TIM = "gws_gmail_search"      # tool MCP dùng để tìm thư theo tiêu chí

# Một dòng do `_ke_thu` của server dựng ra: "- [ma] Người gửi — Tiêu đề (25/08 09:12)".
_DONG_THU = re.compile(r"^-\s*\[([^\]]+)\]\s*(.*)$")
_NGAY_CUOI = re.compile(r"\s\((\d{2}/\d{2} \d{2}:\d{2})\)$")


def tach_thu(text):
    """Chuỗi `gws_gmail_read` trả về -> {tu, tieu_de, than}. Hàm THUẦN.

    Định dạng nguồn: "Từ: ...\nTiêu đề: ...\n\n<thân thư>". Không khớp (server đổi định
    dạng, hoặc thư lạ) -> dồn TẤT CẢ vào thân thư: hiện thừa vài dòng đầu vẫn hơn là hiện
    một panel trống khi người dùng vừa bảo "cho tôi xem".
    """
    text = text or ""
    dau, phan_cach, than = text.partition("\n\n")
    thu = {"tu": "", "tieu_de": "", "than": than if phan_cach else text}
    if not phan_cach:
        return thu
    for dong in dau.splitlines():
        nhan, dau_hai_cham, gia_tri = dong.partition(":")
        if not dau_hai_cham:
            continue
        khoa = strip_accents(nhan).strip().lower()
        if khoa == "tu":
            thu["tu"] = gia_tri.strip()
        elif khoa == "tieu de":
            thu["tieu_de"] = gia_tri.strip()
    return thu


def tach_danh_sach(text):
    """Chuỗi `gws_gmail_search`/`gws_gmail_unread` trả về -> [{id, tu, tieu_de, ngay}].

    Hàm THUẦN. Dòng không đúng khuôn (dòng tiêu đề "Tìm thấy N email...", dòng trống) bị
    bỏ qua chứ không làm hỏng cả danh sách — server có thể thêm dòng dẫn nhập bất cứ lúc nào.
    """
    rows = []
    for dong in (text or "").splitlines():
        khop = _DONG_THU.match(dong.strip())
        if not khop:
            continue
        ma, con_lai = khop.group(1), khop.group(2)
        tu, phan_cach, tieu_de = con_lai.partition(" — ")
        if not phan_cach:                       # không có dấu ngăn -> coi cả cụm là tiêu đề
            tu, tieu_de = "", con_lai
        ngay = ""
        co_ngay = _NGAY_CUOI.search(tieu_de)
        if co_ngay:
            ngay, tieu_de = co_ngay.group(1), tieu_de[:co_ngay.start()]
        rows.append({"id": ma, "tu": tu.strip(), "tieu_de": tieu_de.strip(), "ngay": ngay})
    return rows


def _register_show_mail(reg: ToolRegistry, mcp, bus):
    """Tool HIỆN một lá thư lên panel — nội dung KHÔNG đi qua ngữ cảnh LLM.

    Vì sao là tool CỤC BỘ chứ không phải một tool MCP nữa: server MCP chạy ở tiến trình
    RIÊNG (stdio), không với tới được `bus` để vẽ lên màn hình. Nên phần lấy dữ liệu ở
    server, phần trưng ra ở đây.

    Câu trả về CỐ ĐỊNH, không nhét tiêu đề thư vào. Hai lý do đi cùng nhau: tiêu đề do
    người ngoài soạn nên nếu nhét vào thì tool phải mang cờ `untrusted_output`, mà cờ đó
    khiến kết quả bị bọc trong cặp mốc ⟦DỮ LIỆU NGOÀI⟧ — rồi `speakable` sẽ ĐỌC LÊN cả
    cặp mốc đó. Giữ câu cố định thì vừa nói được thẳng, vừa không có chữ của người lạ nào
    lọt vào hội thoại. Tiêu đề nằm trên panel, chỗ nó thuộc về.
    """
    # Danh sách thư vừa hiện, để mở được theo SỐ THỨ TỰ. Cùng khuôn với `session` của
    # feature `places` (find_nearby -> open_place_result).
    phien = {"rows": []}

    def _ma_thu(message_id=None, index=None):
        """Suy ra mã thư từ mã trực tiếp HOẶC số thứ tự. Trả (mã, câu_lỗi)."""
        if message_id:
            return str(message_id).strip(), None
        if index is None:
            return None, "Cần cho biết mã thư, hoặc số thứ tự thư trong danh sách vừa hiện."
        rows = phien["rows"]
        if not rows:
            return None, "Chưa có danh sách thư nào — hãy tìm thư trước đã."
        try:
            i = int(str(index).strip())
        except (TypeError, ValueError):
            return None, "Cần cho biết số thứ tự thư cần mở (ví dụ 1, 2, 3)."
        if i < 1 or i > len(rows):
            return None, f"Danh sách chỉ có {len(rows)} thư, không có số {i}."
        return rows[i - 1]["id"], None

    def show_email(message_id=None, index=None):
        ma, loi = _ma_thu(message_id, index)
        if loi:
            return loi
        # KHÔNG bắt lỗi ở đây: nuốt rồi trả chuỗi thân thiện thì `_run_tool` xem lượt này là
        # THÀNH CÔNG, và nhật ký kết quả ghi "xong" cho một lượt hỏng — đúng cái bẫy đã vá ở
        # `MCPError`. Để nó ném ra: agent bắt, bật `is_error`, rồi model tự soạn lời xin lỗi —
        # người dùng vẫn nghe câu tử tế, mà tín hiệu thì không mất.
        noi_dung = str(mcp.call_tool(_TEN_TOOL_DOC, {"message_id": ma}))
        try:
            bus.emit_mail(tach_thu(noi_dung))
        except Exception as e:      # panel hỏng không được làm vỡ lượt
            logger.warning("Không hiện được panel thư: %s", e)
            return "Tôi lấy được thư nhưng chưa hiện lên màn hình được."
        return "Đã hiện thư lên màn hình cho bạn xem."

    def show_email_list(q):
        q = (q or "").strip()
        if not q:
            return "Cần cho biết tìm thư theo tiêu chí gì."
        ket_qua = str(mcp.call_tool(_TEN_TOOL_TIM, {"q": q}))   # lỗi -> ném, xem show_email
        rows = tach_danh_sach(ket_qua)
        phien["rows"] = rows
        try:
            bus.emit_mail_list(rows, q=q)
        except Exception as e:
            logger.warning("Không hiện được panel danh sách thư: %s", e)
            return "Tôi tìm được thư nhưng chưa hiện lên màn hình được."
        if not rows:
            return "Không tìm thấy thư nào khớp."
        return (f"Đã hiện {len(rows)} thư lên màn hình. "
                "Bạn bấm vào một thư, hoặc nói số thứ tự để tôi mở.")

    reg.register(Tool(
        name="show_email_list",
        description="TÌM thư rồi HIỆN DANH SÁCH lên màn hình để người dùng nhìn và bấm chọn. "
                    "Dùng khi người dùng muốn XEM danh sách ('cho tôi xem các mail của...', "
                    "'hiện thư về...'). Chỉ muốn NGHE đọc tiêu đề thì dùng gws_gmail_search. "
                    "'q' theo cú pháp Gmail, giống gws_gmail_search.",
        input_schema={
            "type": "object",
            "properties": {"q": {"type": "string",
                                 "description": "Tiêu chí tìm, vd 'from:hcmut.edu.vn tốt nghiệp'"}},
            "required": ["q"],
        },
        handler=show_email_list,
        speakable=True,
    ))

    reg.register(Tool(
        name="show_email",
        description="HIỆN nội dung một email lên màn hình để người dùng ĐỌC BẰNG MẮT. Dùng "
                    "khi người dùng nói 'cho tôi xem/mở thư đó', 'mở thư thứ hai'. Cho "
                    "'message_id' (mã thư) HOẶC 'index' (số thứ tự trong danh sách vừa hiện). "
                    "Muốn TÓM TẮT hay trả lời câu hỏi về nội dung thư thì dùng gws_gmail_read.",
        input_schema={
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Mã thư"},
                "index": {"type": "integer", "description": "Số thứ tự trong danh sách vừa hiện"},
            },
        },
        handler=show_email,
        speakable=True,
    ))
