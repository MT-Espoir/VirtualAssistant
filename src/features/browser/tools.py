"""
Tool của feature `browser` — Điều khiển Chrome qua extension: tab, media, mở-hoặc-dùng-lại.

Chuyển nguyên khối từ `agent/tools.py` (2026-08-25); thân hàm KHÔNG sửa một
dòng nào. `register(reg, ctx)` chỉ là lớp bọc mỏng lấy dependency từ ctx.
"""

from agent.tools import Tool, ToolRegistry



def register(reg, ctx):
    """Đăng ký tool của feature `browser` theo đúng thứ tự đăng ký cũ."""
    if ctx.browser is not None:
        _register_browser_tools(reg, ctx.browser)


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

    def close_tab(keyword):
        """Đóng tab THẬT. Cổng duyệt của registry đã chặn trước đó — xem `_mo_ta_dong_tab`."""
        if not keyword or not str(keyword).strip():
            return "Cần cho biết từ khoá của tab cần đóng (tên trang hoặc tiêu đề)."
        resp = browser.send_command(action="CLOSE_TAB_BY_KEYWORD",
                                    keyword=keyword, dryRun=False)
        return summarize_close(resp, keyword, True)

    def _mo_ta_dong_tab(keyword=None, **_):
        """Cụm mô tả để HỎI, kèm danh sách tab sẽ đóng (chạy thử `dryRun`).

        Trước đây tool tự làm hai pha bằng tham số `confirm`, và luật "đừng tự đặt
        confirm=true ngay lần đầu" nằm trong MÔ TẢ TOOL — tức nằm đúng trong thứ mà
        prompt injection ghi đè được. Mô phỏng tấn công 2026-08-29 xác nhận nó lọt:
        `confirm=True` ngay lần đầu là tab đóng thật, không cổng nào chạy.
        Nay việc chặn thuộc về `registry.gate()` ở tầng code; chỗ này chỉ còn lo CÂU CHỮ.

        Vẫn chạy thử để đọc tên tab cho người dùng nghe — đó là phần giá trị duy nhất của
        cơ chế cũ, và mất nó thì câu hỏi trở nên mơ hồ ("đóng tab nào?"). Chrome hỏng thì
        lùi về câu chung: `gate()` bắt ngoại lệ, hỏi vẫn hỏi.
        """
        kw = str(keyword or "").strip()
        resp = browser.send_command(action="CLOSE_TAB_BY_KEYWORD", keyword=kw, dryRun=True)
        matched = (resp or {}).get("matched") or []
        if not matched:
            return f"đóng tab khớp '{kw}'"
        ten = ", ".join((t.get("title") or "?").strip() for t in matched[:5])
        return f"đóng {len(matched)} tab khớp '{kw}' ({ten})"

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
        untrusted_output=True,   # nội dung do bên ngoài kiểm soát
    ))

    reg.register(Tool(
        name="browser_close_tab",
        description=("Đóng (các) tab Chrome có tiêu đề hoặc URL chứa 'keyword'. Trợ lý sẽ "
                     "tự hỏi xác nhận và đọc danh sách tab trước khi đóng."),
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string",
                            "description": "Từ khoá khớp tiêu đề/URL tab, vd 'facebook'"},
            },
            "required": ["keyword"],
        },
        handler=close_tab,
        # Đóng tab = mất thứ đang mở dở, không hoàn tác được. Cổng ở TẦNG CODE thay cho
        # luật viết trong mô tả tool — luật viết trong mô tả thì injection ghi đè được.
        destructive=True,
        confirm_message=_mo_ta_dong_tab,
        # Câu trả về liệt kê TÊN TAB — do trang tự đặt, kẻ tấn công viết được.
        untrusted_output=True,
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
        exfil=True,
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
