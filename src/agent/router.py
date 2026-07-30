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

# Ánh xạ case -> tên tool. Đặt trong code (cạnh nơi biết tool) để không lệch với
# registry; None = dùng tất cả. Chỉ các tool THỰC SỰ đăng ký mới được dùng.
# LƯU Ý thứ tự: classify() khớp tên case bằng substring, mà "web" là con của "weather"
# -> phải đặt "weather" TRƯỚC "web" để "weather" không bị "web" nuốt nhầm.
CASE_TOOLS = {
    "weather": ["get_weather"],
    "web": ["open_website", "web_search", "web_search_list", "open_search_result",
            "play_youtube", "search_on_site", "web_fetch", "wikipedia_lookup"],
    "system": ["open_app", "close_app", "set_volume", "set_brightness", "system_info"],
    "screen": ["take_screenshot", "find_on_screen", "scroll_screen"],
    "browser": ["browser_media_control", "browser_list_tabs", "browser_close_tab",
                "browser_open_or_reuse"],
    "schedule": ["schedule_reminder", "list_reminders", "cancel_reminder"],
    "general": None,
}


class Router:
    def __init__(self, llm, data=None, case_tools=None):
        self.llm = llm
        self.data = data or prompts.load()
        self.case_tools = case_tools or CASE_TOOLS

    def classify(self, text):
        """Một lượt LLM -> tên case. Lỗi/không nhận ra -> 'general'."""
        router_prompt = self.data.get("router", "")
        if not router_prompt:
            return "general"
        try:
            turn = self.llm.generate(system=router_prompt,
                                     messages=[Message(role="user", text=text)], tools=[])
        except Exception as e:
            logger.warning("Router phân loại lỗi: %s — dùng 'general'.", e)
            return "general"
        raw = norm(turn.text or "")
        for name in self.case_tools:
            if name != "general" and name in raw:
                return name
        return "general"

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
        if names:
            narrowed = [s for s in specs if s["name"] in names]
            if narrowed:                       # có tool trong nhóm -> thu hẹp
                specs = narrowed
        logger.info("🧭 router: case=%s (%d tool)", case, len(specs))
        return system, specs
