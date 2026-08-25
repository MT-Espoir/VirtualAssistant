"""
Định nghĩa "tool" (công cụ) và registry cho agent.

Mỗi Tool = tên + mô tả + JSON schema tham số + hàm thực thi. LLM đọc mô tả +
schema để quyết định gọi tool nào với tham số gì (tool-calling). Registry gom
các tool lại, cung cấp:
  - specs():  danh sách định nghĩa tool để gửi cho LLM
  - run():    thực thi tool theo tên với tham số LLM sinh ra

build_default_registry(actions) dựng sẵn bộ tool điều khiển máy tính từ
AssistantActions (core/actions_facade.py) — tái dùng đúng phần refactor Tầng 2.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from utils.config import config
from utils.logger import get_logger
from utils.text_norm import strip_accents

logger = get_logger(__name__)


def _first_number(value):
    """Rút số đầu tiên trong value (số hoặc chuỗi kiểu '5', '5 phút'). None nếu không có."""
    m = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(m.group().replace(",", ".")) if m else None


def _relative_from_text(text, now):
    """'5 phút' / 'sau 2 tiếng' / '30 giây' -> datetime. None nếu không có số."""
    low = strip_accents(str(text).lower())
    n = _first_number(low)
    if n is None:
        return None
    if "gio" in low or "tieng" in low or "hour" in low:
        return now + timedelta(hours=n)
    if "giay" in low or "sec" in low:
        return now + timedelta(seconds=n)
    return now + timedelta(minutes=n)          # mặc định coi là phút


def _parse_fire_time(delay_minutes=None, at=None, now=None):
    """Tính thời điểm nhắc — CHỊU LỖI với tham số lộn xộn do model sinh ra.

    delay_minutes: số hoặc chuỗi có số ('5', '5 phút'). at: ISO, 'HH:MM', hoặc cả cụm
    tương đối lọt vào đây ('sau 5 phút', '2 tiếng'). Trả datetime, hoặc None.
    """
    now = now or datetime.now()

    if delay_minutes is not None:
        n = _first_number(delay_minutes)
        if n is not None:
            return now + timedelta(minutes=n)

    if at:
        at = str(at).strip()
        try:                                    # ISO đầy đủ, vd 2026-07-25T15:00
            return datetime.fromisoformat(at)
        except ValueError:
            pass
        m = re.match(r"^(\d{1,2})\s*[:hg]\s*(\d{1,2})", at)   # HH:MM / HHhMM / HHgMM
        if m:
            fire = now.replace(hour=int(m.group(1)) % 24, minute=int(m.group(2)) % 60,
                               second=0, microsecond=0)
            return fire + timedelta(days=1) if fire <= now else fire
        rel = _relative_from_text(at, now)      # 'sau 5 phút' lọt vào 'at'
        if rel is not None:
            return rel

    return None


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict          # JSON Schema cho tham số
    handler: Callable[..., str]  # nhận **kwargs theo schema, trả về chuỗi
    destructive: bool = False    # True = khó hoàn tác -> Agent hỏi xác nhận trước khi chạy
    confirm_message: Callable[..., str] = None  # (**args) -> cụm mô tả việc sẽ làm, để hỏi
    # (**args) -> dict để HIỆN RA cho người dùng xem trước khi xác nhận, hoặc None nếu
    # không có gì đáng xem. Chỉ có nghĩa với tool destructive (Agent gọi lúc hoãn hành
    # động). Dùng cho nội dung mà TAI không kiểm được — thư dài, văn bản do LLM viết ra.
    preview: Callable[..., dict] = None
    # True = kết quả trả về ĐÃ là câu tiếng Việt hoàn chỉnh, đọc thẳng cho người dùng được.
    # Agent dùng cờ này để BỎ lượt LLM soạn lời (tiết kiệm 1 call) — chỉ khi model gọi đúng
    # MỘT tool này và không làm gì thêm. Đánh đổi: câu trả lời không mang giọng persona,
    # nên chỉ bật cho tool mà output vốn đã tự nhiên. KHÔNG bật cho tool cần diễn giải
    # (tìm web, đọc mail, tóm tắt trang).
    speakable: bool = False

    def spec(self) -> dict:
        """Định nghĩa tool gửi cho LLM (định dạng Anthropic tool-use)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool trùng tên: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> List[str]:
        """Tên tool THEO ĐÚNG thứ tự đăng ký (dict giữ thứ tự chèn).

        Bộ nạp feature so tên trước/sau khi gọi `register` để biết feature nào đăng ký
        tool nào — nhờ vậy `CASE_TOOLS` suy ra được thay vì chép tay.
        """
        return list(self._tools)

    def specs(self) -> List[dict]:
        return [t.spec() for t in self._tools.values()]

    def run(self, name: str, arguments: dict) -> str:
        """Thực thi tool. Ném KeyError nếu không có tool tên đó."""
        tool = self._tools[name]
        logger.debug("Chạy tool %s(%s)", name, arguments)
        return tool.handler(**(arguments or {}))

# Bộ tool mặc định (điều khiển máy tính) dựng từ AssistantActions
def build_default_registry(actions, scheduler=None, browser=None,
                           profile=None) -> ToolRegistry:
    """Tạo registry điều khiển máy tính từ một facade actions (hoặc mock).

    Nếu truyền `scheduler` (ReminderScheduler) thì đăng ký thêm bộ tool lập lịch.
    Nếu truyền `browser` (BrowserBridge) thì đăng ký thêm tool điều khiển Chrome.
    Nếu truyền `profile` (UserProfile) thì tool thời tiết dùng địa điểm mặc định trong
    hồ sơ (thay cho cấu hình cứng).

    ĐANG THU HẸP DẦN: mỗi feature tách ra `features/<tên>/` lại bớt một tham số ở đây.
    Còn lại là nhóm lõi (system, weather, web) — bước cuối của việc 4 sẽ dọn nốt.
    """
    reg = ToolRegistry()

    reg.register(Tool(
        name="open_app",
        description="Mở một ứng dụng trên máy (ví dụ Chrome, Notepad, Word).",
        input_schema={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Tên ứng dụng cần mở"},
            },
            "required": ["app_name"],
        },
        handler=lambda app_name: actions.open_application(app_name),
        speakable=True,      # "Đã mở Chrome."
    ))

    reg.register(Tool(
        name="close_app",
        description="Đóng một ứng dụng đang chạy. Trợ lý sẽ tự hỏi xác nhận trước khi đóng.",
        input_schema={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "Tên ứng dụng cần đóng"},
            },
            "required": ["app_name"],
        },
        handler=lambda app_name: actions.close_application(app_name),
        destructive=True,      # đóng app có thể mất dữ liệu chưa lưu -> chốt xác nhận trong code
        confirm_message=lambda app_name=None: f"đóng ứng dụng {app_name}",
    ))

    reg.register(Tool(
        name="list_windows",
        description="Liệt kê các cửa sổ/ứng dụng ĐANG MỞ trên máy (theo tiêu đề). Dùng khi "
                    "người dùng hỏi 'đang mở những gì', 'có cửa sổ/ứng dụng nào đang chạy', "
                    "hoặc để biết tên cửa sổ trước khi chuyển sang nó.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: actions.list_windows(),
    ))

    reg.register(Tool(
        name="switch_window",
        description="Chuyển sang (đưa RA TRƯỚC) một cửa sổ/ứng dụng ĐANG CHẠY SẴN theo tên, "
                    "vd 'chuyển sang Chrome', 'qua cửa sổ Word', 'mở lại Claude đang mở'. "
                    "KHÁC open_app (mở ứng dụng MỚI) — tool này chỉ focus cửa sổ đã chạy.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Tên/một phần tiêu đề cửa sổ cần chuyển sang"},
            },
            "required": ["name"],
        },
        handler=lambda name: actions.switch_window(name),
    ))

    reg.register(Tool(
        name="set_volume",
        description=("Điều chỉnh âm lượng hệ thống. Dùng 'level' để đặt mức tuyệt "
                     "đối (0-100), hoặc 'change' để tăng/giảm tương đối (số âm để giảm)."),
        input_schema={
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Mức âm lượng 0-100"},
                "change": {"type": "integer", "description": "Thay đổi tương đối, vd 10 hoặc -15"},
            },
        },
        handler=lambda level=None, change=None: actions.control_volume(level=level, change=change),
        speakable=True,      # câu xác nhận ngắn
    ))

    reg.register(Tool(
        name="set_brightness",
        description=("Điều chỉnh độ sáng màn hình. Dùng 'level' để đặt mức tuyệt "
                     "đối (0-100), hoặc 'change' để tăng/giảm tương đối."),
        input_schema={
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Mức độ sáng 0-100"},
                "change": {"type": "integer", "description": "Thay đổi tương đối"},
            },
        },
        handler=lambda level=None, change=None: actions.control_brightness(level=level, change=change),
        speakable=True,
    ))

    # (Đã gỡ tool 'shutdown'/'restart' — tắt/khởi động lại máy quá rủi ro khi STT
    #  nghe nhầm; cố ý không cung cấp cho agent.)

    reg.register(Tool(
        name="system_info",
        description="Xem tình trạng máy tính: RAM, ổ đĩa, CPU, pin.",
        input_schema={
            "type": "object",
            "properties": {
                "what": {"type": "string",
                         "enum": ["all", "memory", "disk", "cpu", "battery"],
                         "description": "Mục cần xem (mặc định all)"},
            },
        },
        handler=lambda what="all": actions.system_info(what),
        speakable=True,      # "RAM: đã dùng 9.8 GB/15.4 GB (64%)..."
    ))

    reg.register(Tool(
        name="web_fetch",
        description="Tải nội dung một trang web theo URL để đọc/tóm tắt. "
                    "Dùng khi người dùng đưa link hoặc muốn tóm tắt một trang cụ thể.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL đầy đủ (http/https)"},
            },
            "required": ["url"],
        },
        handler=lambda url: actions.web_fetch(url),
    ))

    reg.register(Tool(
        name="wikipedia_lookup",
        description="Tra cứu nhanh một chủ đề trên Wikipedia (trả đoạn tóm tắt). "
                    "Dùng khi người dùng hỏi 'X là gì', tra cứu khái niệm/nhân vật.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Chủ đề/từ khóa cần tra"},
            },
            "required": ["topic"],
        },
        handler=lambda topic: actions.wikipedia_lookup(topic),
    ))

    reg.register(Tool(
        name="get_weather",
        description="Xem thời tiết hôm nay ở một địa điểm: mô tả trời, nhiệt độ, khả năng "
                    "mưa, chỉ số tia UV, kèm khuyến nghị (che nắng, mang áo mưa...). Dùng "
                    "khi người dùng hỏi 'thời tiết hôm nay', 'trời có mưa không', 'nắng "
                    "không', 'tia UV mạnh không'. Không nói địa điểm thì để trống.",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string",
                             "description": "Tên thành phố/địa điểm; để trống nếu người "
                                            "dùng không nói (dùng địa điểm mặc định)"},
            },
        },
        handler=lambda location=None: actions.get_weather(
            location or (profile.get_default_location() if profile else None)
            or config.WEATHER_DEFAULT_LOCATION),
        speakable=True,      # đã gồm mô tả trời + khuyến nghị + ghi nguồn
    ))

    reg.register(Tool(
        name="open_website",
        description="Mở một trang web trong trình duyệt.",
        input_schema={
            "type": "object",
            "properties": {
                "website": {"type": "string", "description": "Tên hoặc URL trang web"},
            },
            "required": ["website"],
        },
        handler=lambda website: actions.open_website(website),
    ))

    reg.register(Tool(
        name="web_search",
        description="Tìm kiếm trên web với engine chỉ định.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung tìm kiếm"},
                "engine": {"type": "string", "enum": ["google", "bing", "youtube"],
                           "description": "Công cụ tìm kiếm (mặc định google)"},
            },
            "required": ["query"],
        },
        handler=lambda query, engine="google": actions.search_web(query, engine),
    ))

    reg.register(Tool(
        name="play_youtube",
        description="Tìm và phát một video/bài hát trên YouTube.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Tên video/bài hát"},
            },
            "required": ["query"],
        },
        handler=lambda query: actions.search_and_play_youtube_direct(query),
    ))

    reg.register(Tool(
        name="search_on_site",
        description="Tìm kiếm nội dung trên một trang cụ thể (facebook, youtube, github...).",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung tìm kiếm"},
                "site": {"type": "string", "description": "Tên trang, vd facebook, youtube"},
            },
            "required": ["query", "site"],
        },
        handler=lambda query, site: actions.search_on_specific_site(query, site),
    ))

    if scheduler is not None:
        _register_schedule_tools(reg, scheduler)

    if browser is not None:
        _register_browser_tools(reg, browser)
        _register_web_search_tools(reg, browser, actions)

    # `places` đã tách sang `features/places/` — nạp qua `load_features`, xem `app.py`.

    return reg


def _register_browser_tools(reg: ToolRegistry, browser):
    """Tool điều khiển Chrome (media + quản lý tab) qua BrowserBridge/extension."""
    from services.browser_protocol import (
        build_media_command, summarize_media_response,
        summarize_tab_list, summarize_close,
        build_open_or_reuse, summarize_open_or_reuse)

    def media_control(action, value=None):
        try:
            cmd = build_media_command(action, value)
        except ValueError as e:
            return str(e)
        resp = browser.send_command(**cmd)
        return summarize_media_response(resp, action, value)

    def list_tabs():
        return summarize_tab_list(browser.send_command(action="GET_TABS"))

    def close_tab(keyword, confirm=False):
        if not keyword or not str(keyword).strip():
            return "Cần cho biết từ khoá của tab cần đóng (tên trang hoặc tiêu đề)."
        resp = browser.send_command(action="CLOSE_TAB_BY_KEYWORD",
                                    keyword=keyword, dryRun=not confirm)
        return summarize_close(resp, keyword, confirm)

    def open_or_reuse(url, match_domain=None):
        try:
            cmd = build_open_or_reuse(url, match_domain)
        except ValueError as e:
            return str(e)
        return summarize_open_or_reuse(browser.send_command(**cmd), url)

    reg.register(Tool(
        name="browser_list_tabs",
        description="Liệt kê các tab Chrome đang mở (tiêu đề + trang). Dùng khi người "
                    "dùng hỏi 'đang mở tab gì', hoặc để biết tab nào trước khi đóng.",
        input_schema={"type": "object", "properties": {}},
        handler=list_tabs,
    ))

    reg.register(Tool(
        name="browser_close_tab",
        description=(
            "Đóng (các) tab Chrome có tiêu đề hoặc URL chứa 'keyword'. QUAN TRỌNG — đóng "
            "tab KHÓ HOÀN TÁC: BẮT BUỘC gọi lần đầu với confirm=false để xem danh sách tab "
            "sẽ đóng, ĐỌC danh sách đó cho người dùng và CHỜ họ đồng ý; chỉ gọi lại với "
            "confirm=true SAU KHI người dùng xác nhận. Không tự đặt confirm=true ngay lần đầu."),
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string",
                            "description": "Từ khoá khớp tiêu đề/URL tab, vd 'facebook'"},
                "confirm": {"type": "boolean",
                            "description": "false = chỉ xem trước; true = thật sự đóng "
                                           "(chỉ dùng sau khi người dùng đã đồng ý)"},
            },
            "required": ["keyword"],
        },
        handler=close_tab,
    ))

    reg.register(Tool(
        name="browser_open_or_reuse",
        description=(
            "Mở một URL trong Chrome, TÁI DÙNG tab cùng trang nếu đã mở (chuyển tab đó "
            "tới URL mới + đưa lên trước) thay vì tạo tab mới. Dùng khi mở/chuyển sang "
            "một trang có thể đã mở sẵn, vd mở video YouTube khác trong tab YouTube đang có."),
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL đầy đủ cần mở"},
                "match_domain": {"type": "string",
                                 "description": "Tên miền để tìm tab tái dùng "
                                                "(mặc định tự suy từ url, vd youtube.com)"},
            },
            "required": ["url"],
        },
        handler=open_or_reuse,
    ))

    reg.register(Tool(
        name="browser_media_control",
        description=(
            "Điều khiển trình phát media (video/nhạc) trên tab Chrome đang mở, ví dụ "
            "YouTube. Dùng khi người dùng nói 'tạm dừng/phát tiếp nhạc', 'tua', 'chỉnh "
            "âm lượng video', 'bài kế/trước'. 'action': play, pause, toggle (đảo phát/dừng), "
            "next, prev (trong playlist), set_volume (cần 'value' 0-100), adjust_volume (cần "
            "'value' = mức thay đổi tương đối, vd +10/-10 để to/nhỏ hơn), seek (cần 'value' "
            "= số giây tua tới; số âm để tua lùi)."),
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "enum": ["play", "pause", "toggle", "next", "prev",
                                    "set_volume", "adjust_volume", "seek"],
                           "description": "Hành động điều khiển media"},
                "value": {"type": "number",
                          "description": "set_volume (0-100), adjust_volume (±, vd 10/-10), "
                                         "hoặc seek (giây)"},
            },
            "required": ["action"],
        },
        handler=media_control,
    ))


def _register_web_search_tools(reg: ToolRegistry, browser, actions):
    """Tìm web + ĐỌC danh sách kết quả (extension trích DOM), rồi mở kết quả người dùng
    chọn theo SỐ THỨ TỰ — hoặc ĐỌC NỘI DUNG một kết quả để trả lời câu hỏi trực tiếp
    (khác việc mở tab). Giữ trạng thái danh sách kết quả gần nhất giữa các lượt trong
    closure `session` — người dùng/model chỉ cần nói 'số 2', KHÔNG cần chép lại URL dài.
    """
    from services.browser_protocol import (
        build_search_read, parse_search_results, summarize_search_results,
        build_open_or_reuse)

    session = {"results": []}      # kết quả tìm kiếm gần nhất (sống suốt phiên)

    def search_list(query, engine=None):
        try:
            cmd = build_search_read(query, engine or config.WEB_SEARCH_ENGINE)
        except ValueError as e:
            return str(e)
        # Đọc DOM cần mở tab + chờ render -> cho timeout rộng hơn lệnh thường.
        resp = browser.send_command(timeout=25, **cmd)
        results, err = parse_search_results(resp)
        if err:
            return err
        session["results"] = results
        return summarize_search_results(results, query)

    def open_result(index=None):
        results = session["results"]
        if not results:
            return "Chưa có kết quả tìm kiếm nào để mở — hãy tìm trước đã."
        try:
            i = int(str(index).strip())
        except (TypeError, ValueError):
            return "Cần cho biết số thứ tự kết quả cần mở (ví dụ 1, 2, 3)."
        if i < 1 or i > len(results):
            return f"Chỉ có {len(results)} kết quả, không có số {i}."
        chosen = results[i - 1]
        browser.send_command(**build_open_or_reuse(chosen["url"]))
        return f"Đang mở kết quả số {i}: {chosen['title']}."

    reg.register(Tool(
        name="web_search_list",
        description=("Tìm thông tin trên web rồi ĐỌC danh sách vài kết quả đầu để người "
                     "dùng chọn (KHÔNG mở thẳng). Dùng khi người dùng muốn 'tìm thông tin "
                     "về X', 'tra cứu X', 'tìm hiểu về X' — trừ YouTube/Wikipedia. Sau đó "
                     "người dùng chọn số nào thì dùng open_search_result."),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Nội dung cần tìm"},
                "engine": {"type": "string", "enum": ["google", "duckduckgo"],
                           "description": "Công cụ tìm (mặc định theo cấu hình)"},
            },
            "required": ["query"],
        },
        handler=search_list,
    ))

    reg.register(Tool(
        name="open_search_result",
        description=("Mở một kết quả trong danh sách VỪA tìm bằng web_search_list, theo "
                     "SỐ THỨ TỰ. Dùng khi người dùng nói 'mở kết quả số 2', 'vào link 1', "
                     "'cái đầu tiên'..."),
        input_schema={
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "Số thứ tự kết quả (1, 2, 3...)"},
            },
            "required": ["index"],
        },
        handler=open_result,
    ))

    def read_result(index=1):
        results = session["results"]
        if not results:
            return "Chưa có kết quả tìm kiếm nào — hãy gọi web_search_list trước."
        try:
            i = int(str(index).strip())
        except (TypeError, ValueError):
            i = 1
        if i < 1 or i > len(results):
            return f"Chỉ có {len(results)} kết quả, không có số {i}."
        chosen = results[i - 1]
        text = actions.web_fetch(chosen["url"])
        return f"Nội dung bài '{chosen['title']}':\n{text}"

    reg.register(Tool(
        name="read_search_result",
        description=("Tải NỘI DUNG THẬT của một kết quả trong danh sách VỪA tìm bằng "
                     "web_search_list, theo SỐ THỨ TỰ (mặc định số 1) — để ĐỌC rồi TRẢ LỜI "
                     "CÂU HỎI của người dùng bằng nội dung đó. Dùng cho câu hỏi cần thông "
                     "tin cụ thể (vd 'hôm nay có sự kiện gì...', 'vì sao...', 'X là ai'), "
                     "KHÁC với open_search_result (chỉ mở tab, không đọc nội dung)."),
        input_schema={
            "type": "object",
            "properties": {
                "index": {"type": "integer",
                          "description": "Số thứ tự kết quả cần đọc (mặc định 1)"},
            },
        },
        handler=read_result,
    ))


def _register_schedule_tools(reg: ToolRegistry, scheduler):
    def schedule_reminder(message, delay_minutes=None, at=None):
        fire = _parse_fire_time(delay_minutes=delay_minutes, at=at)
        if fire is None:
            return "Cần cho biết thời điểm: delay_minutes (số phút nữa) hoặc at (HH:MM)."
        task = scheduler.add(message, fire)
        return (f"Đã đặt nhắc lúc {fire.strftime('%H:%M %d/%m')}: "
                f"\"{message}\" (mã {task['id']}).")

    def list_reminders():
        tasks = scheduler.list()
        if not tasks:
            return "Hiện không có lịch nhắc nào."
        lines = []
        for t in tasks:
            when = datetime.fromisoformat(t["fire_at"]).strftime("%H:%M %d/%m")
            lines.append(f"- [{t['id']}] {when}: {t['message']}")
        return "Các lịch nhắc:\n" + "\n".join(lines)

    def cancel_reminder(task_id):
        return ("Đã hủy lịch nhắc." if scheduler.cancel(task_id)
                else f"Không tìm thấy lịch nhắc mã '{task_id}'.")

    def schedule_action(command, delay_minutes=None, at=None):
        fire = _parse_fire_time(delay_minutes=delay_minutes, at=at)
        if fire is None:
            return "Cần cho biết thời điểm: delay_minutes (số phút nữa) hoặc at (HH:MM)."
        scheduler.add(command, fire, kind="do")
        return f"Được, tôi sẽ tự làm giúp bạn lúc {fire.strftime('%H:%M %d/%m')}: {command}."

    reg.register(Tool(
        name="schedule_reminder",
        description="Đặt một lời NHẮC (chỉ ĐỌC nhắc, KHÔNG tự làm) vào thời điểm sau. Dùng khi "
                    "người dùng nói 'nhắc tôi X lúc...'. Cho 'delay_minutes' (số phút nữa) HOẶC "
                    "'at' (giờ HH:MM, hoặc ISO datetime).",
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Nội dung cần nhắc"},
                "delay_minutes": {"type": "number", "description": "Nhắc sau bao nhiêu phút"},
                "at": {"type": "string", "description": "Giờ nhắc, vd '15:00' hoặc ISO datetime"},
            },
            "required": ["message"],
        },
        handler=schedule_reminder,
    ))

    reg.register(Tool(
        name="schedule_action",
        description="Hẹn THỰC THI một lệnh vào thời điểm sau (trợ lý TỰ LÀM khi tới giờ, không "
                    "chỉ nhắc). Dùng khi người dùng nói 'lúc X hãy mở/phát/làm Y', '22h30 mở "
                    "youtube'. 'command' = câu lệnh sẽ chạy (vd 'mở youtube'). Cho 'delay_minutes' "
                    "(số phút nữa) HOẶC 'at' (giờ HH:MM).",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Lệnh cần thực thi khi tới giờ, vd 'mở youtube'"},
                "delay_minutes": {"type": "number", "description": "Làm sau bao nhiêu phút"},
                "at": {"type": "string", "description": "Giờ thực thi, vd '22:30'"},
            },
            "required": ["command"],
        },
        handler=schedule_action,
    ))

    reg.register(Tool(
        name="list_reminders",
        description="Liệt kê các lịch nhắc đang có.",
        input_schema={"type": "object", "properties": {}},
        handler=list_reminders,
        speakable=True,
    ))

    reg.register(Tool(
        name="cancel_reminder",
        description="Hủy một lịch nhắc theo mã (id).",
        input_schema={
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "Mã lịch nhắc"}},
            "required": ["task_id"],
        },
        handler=cancel_reminder,
    ))
