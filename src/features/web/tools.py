"""
Tool của feature `web` — Tim kiem web co doc ket qua. Cac tool web INLINE (open_website, web_search, play_youtube, search_on_site, web_fetch, wikipedia_lookup) con nam o build_default_registry, se gop vao day o buoc cuoi cua viec 4.

Chuyển nguyên khối từ `agent/tools.py` (2026-08-25); thân hàm KHÔNG sửa một
dòng nào. `register(reg, ctx)` chỉ là lớp bọc mỏng lấy dependency từ ctx.
"""

from agent.tools import Tool, ToolRegistry
from utils.config import config



def register(reg, ctx):
    """Đăng ký tool của feature `web` theo đúng thứ tự đăng ký cũ."""
    actions = ctx.actions

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

    # Nhóm đọc kết quả tìm kiếm cần cầu nối Chrome; thiếu thì bỏ qua,
    # phần tìm kiếm cơ bản ở trên vẫn dùng được.
    if ctx.browser is not None:
        _register_web_search_tools(reg, ctx.browser, ctx.actions)


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
