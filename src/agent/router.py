"""
Router: phân loại yêu cầu vào một "case" bằng MỘT lượt LLM, rồi chọn prompt + THU HẸP
bộ tool cho case đó trước khi agent gọi tool.

Vì model nhỏ chọn tool kém khi thấy quá nhiều tool + prompt to, thu hẹp về đúng nhóm
liên quan giúp chọn đúng hơn nhiều. LLM vẫn tự quyết cách gọi tool -> câu phức tạp
KHÔNG bị "hijack" như fast-path. Không rõ case / lỗi -> dùng full tool (an toàn).

(Đã thử phân loại bằng TỪ KHOÁ không-LLM để bỏ lượt LLM này — nhưng khiến model không
gọi được tool nữa, nên GIỮ NGUYÊN lượt LLM phân loại.)
"""

from llm import prompts
from llm.client import Message
from utils.logger import get_logger
from utils.text_norm import norm

logger = get_logger(__name__)
# Case "general" = không thu hẹp tool. Không đến từ feature nào (nó là "mọi thứ còn
# lại") nên phải khai ở đây; mọi case khác suy ra từ registry qua LoadReport.case_tools().
GENERAL = "general"


def case_tools_from(report):
    """{case -> [tool]} suy ra từ ĐÚNG thứ registry đã nhận, cộng case 'general'.

    Thay cho bảng `CASE_TOOLS` chép tay trước đây. Bảng đó là nguồn sự thật THỨ HAI bên
    cạnh registry: sai một tên là tool biến mất khỏi tầm nhìn của model mà không có lỗi
    nào — đúng lỗi đã xảy ra với `research_places`.
    """
    bang = report.case_tools()
    bang[GENERAL] = None
    return bang


class Router:
    def __init__(self, llm, case_tools, data=None, mcp_prefix=None):
        self.llm = llm
        self.data = data or prompts.load()
        # BẮT BUỘC truyền vào, dựng bằng `case_tools_from(report)` — không còn hằng số
        # mặc định nào để rơi về, vì "mặc định" chính là nguồn sự thật thứ hai đã gây lỗi.
        self.case_tools = case_tools
        self.mcp_prefix = mcp_prefix or ""      # tiền tố tên tool MCP để thu hẹp case 'pim'

    def classify(self, text):
        """Một lượt LLM -> tên case. Lỗi/không nhận ra -> 'general'."""
        router_prompt = self.data.get("router", "")
        if not router_prompt:
            return GENERAL
        try:
            turn = self.llm.generate(system=router_prompt,
                                     messages=[Message(role="user", text=text)], tools=[])
        except Exception as e:
            logger.warning("Router phân loại lỗi: %s — dùng 'general'.", e)
            return GENERAL
        return self.match_case(turn.text or "")

    def match_case(self, text):
        """Tìm tên case trong câu model trả về. DÀI TRƯỚC, nên không phụ thuộc thứ tự dict.

        Trước đây hàm này duyệt `CASE_TOOLS` theo thứ tự khai báo, nên thứ tự đó vừa là
        chuyện hiệu suất (thứ tự đăng ký tool) vừa là chuyện đúng/sai (case nào được khớp
        trước). Nay tách hẳn: khớp tên DÀI NHẤT trước thì một case là tiền tố/khúc con của
        case khác cũng không nuốt nhầm, dù `FEATURES` xếp kiểu gì.

        (Bộ tên hiện tại không có cặp nào là khúc con của nhau — đã kiểm. Nhưng chỉ cần
        thêm một case tên 'mail' cạnh 'email' là hiểm hoạ thành thật.)
        """
        raw = norm(text)
        ung_vien = [n for n in self.case_tools if n != GENERAL and n in raw]
        return max(ung_vien, key=len) if ung_vien else GENERAL

    def select(self, text, registry):
        """Trả (system_prompt, tool_specs) cho lượt này theo case đã phân loại."""
        return self.select_for_case(self.classify(text), registry)

    def select_for_case(self, case, registry):
        """Trả (system_prompt, tool_specs) cho một case ĐÃ biết (tách khỏi classify để
        đo lường/tái dùng được — vd bộ eval cần biết case mà không phải classify 2 lần)."""
        base = self.data.get("base", "")
        frag = self.data.get("cases", {}).get(case, "")
        system = (base + "\n" + frag).strip() if frag else base

        specs = registry.specs()
        names = self.case_tools.get(case)
        if case == "pim":                          # tool MCP (theo tiền tố) + tool danh bạ cục bộ
            extra = names or []
            narrowed = [s for s in specs
                        if (self.mcp_prefix and s["name"].startswith(self.mcp_prefix))
                        or s["name"] in extra]
        elif names:
            narrowed = [s for s in specs if s["name"] in names]
        else:
            narrowed = []
        if narrowed:                               # có tool khớp -> thu hẹp; không -> giữ full
            specs = narrowed
        logger.info("🧭 router: case=%s (%d tool)", case, len(specs))
        return system, specs
