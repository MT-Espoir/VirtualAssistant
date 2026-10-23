"""
Tool của feature `browser` — Điều khiển Chrome qua extension: tab, media, mở-hoặc-dùng-lại.

Đóng tab dùng snapshot một lần, gắn kết nối và revision tại extension (R0.3).
"""

import time
import uuid

from agent.tools import ActionRefused, Tool, ToolRegistry



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

    approvals = {}
    approval_ttl = 60.0

    def close_tab(keyword, _close_approval=None):
        """Consume only code-created, connection-bound approval; never re-query keyword."""
        if not keyword or not str(keyword).strip():
            return "Cần cho biết từ khoá của tab cần đóng (tên trang hoặc tiêu đề)."
        approved = approvals.pop(_close_approval, None)
        if (approved is None or approved["keyword"] != str(keyword).strip()
                or time.monotonic() - approved["created"] >= approval_ttl):
            raise ActionRefused("browser_close_tab", {"keyword": keyword},
                                "Cần xem lại tab và xác nhận mới trước khi đóng.")
        if getattr(browser, "connection_id", None) != approved["connection"]:
            raise ActionRefused("browser_close_tab", {"keyword": keyword},
                                "Kết nối Chrome đã đổi. Cần xem lại tab và xác nhận lại.")
        resp = browser.send_command(action="CLOSE_TAB_BY_KEYWORD", keyword=approved["keyword"],
                                    dryRun=False, previewToken=approved["token"],
                                    tabIds=approved["ids"], expected_connection=approved["connection"])
        if not isinstance(resp, dict):
            resp = {}
        if resp.get("type") == "ERROR":
            raise RuntimeError(summarize_close(resp, keyword, True))
        proof_fields = [resp.get(key) for key in ("targetIds", "closedIds", "remainingIds", "unknownIds", "failedIds")]
        valid_lists = all(isinstance(values, list) and all(type(i) is int for i in values)
                          and len(set(values)) == len(values) for values in proof_fields)
        if (not valid_lists or resp.get("type") != "STATUS"
                or resp.get("action") != "CLOSE_TAB_BY_KEYWORD" or resp.get("dryRun") is not False
                or set(resp["targetIds"]) != set(approved["ids"])
                or getattr(browser, "connection_id", None) != approved["connection"]):
            raise RuntimeError("Đã gửi yêu cầu đóng tab, nhưng chưa có bằng chứng hợp lệ cho đúng tập tab đã duyệt.")
        closed, remaining, unknown = (set(resp[key]) for key in ("closedIds", "remainingIds", "unknownIds"))
        if (closed & remaining or closed & unknown or remaining & unknown
                or closed | remaining | unknown != set(approved["ids"])
                or not set(resp["failedIds"]).issubset(set(approved["ids"]))
                or type(resp.get("closedCount")) is not int or resp.get("closedCount") != len(closed)):
            raise RuntimeError("Đã gửi yêu cầu đóng tab, nhưng bằng chứng kết quả không nhất quán.")
        text = summarize_close(resp, keyword, True)
        ids = (resp or {}).get("closedIds")
        if (resp.get("type") != "STATUS" or resp.get("outcome") != "verified"
                or resp.get("readBack") is not True or not isinstance(ids, list)
                or len(ids) != len(approved["ids"]) or set(ids) != set(approved["ids"])
                or resp.get("closedCount") != len(ids) or resp["failedIds"]):
            raise RuntimeError(text)
        return text

    def _prepare_close(keyword=None, **_):
        """Build phrase and frozen arguments from the same read-only snapshot."""
        kw = str(keyword or "").strip()
        connection = getattr(browser, "connection_id", None)
        if not kw or connection is None:
            raise ValueError("Chưa có kết nối Chrome đáng tin để xem trước tab cần đóng.")
        resp = browser.send_command(action="CLOSE_TAB_BY_KEYWORD", keyword=kw, dryRun=True,
                                    expected_connection=connection)
        ids, token = (resp or {}).get("tabIds"), (resp or {}).get("previewToken")
        targets = (resp or {}).get("targets")
        if (not isinstance(ids, list) or not ids or any(type(i) is not int for i in ids)
                or len(set(ids)) != len(ids) or not isinstance(token, str) or not token
                or resp.get("type") != "STATUS" or resp.get("dryRun") is not True
                or resp.get("action") != "CLOSE_TAB_BY_KEYWORD"
                or not isinstance(targets, list) or [t.get("id") for t in targets] != ids
                or getattr(browser, "connection_id", None) != connection):
            raise ValueError("Chưa có snapshot tab hợp lệ. Cần kiểm tra Chrome rồi yêu cầu lại.")
        now = time.monotonic()
        for key in list(approvals):
            if now - approvals[key]["created"] >= approval_ttl:
                approvals.pop(key)
        if len(approvals) >= 64:
            approvals.pop(next(iter(approvals)))
        ticket = uuid.uuid4().hex
        approvals[ticket] = {"keyword": kw, "ids": list(ids), "token": token,
                             "connection": connection, "created": now}
        labels = ", ".join(f"tab {t['id']} ({t.get('domain') or 'trang nội bộ'})" for t in targets)
        return {"arguments": {"keyword": kw, "_close_approval": ticket},
                "phrase": f"đóng đúng {len(ids)} tab: {labels}"}

    def open_or_reuse(url, match_domain=None):
        try:
            cmd = build_open_or_reuse(url, match_domain)
        except ValueError as e:
            return str(e)
        return summarize_open_or_reuse(browser.send_command(**cmd), url)

    reg.register(Tool(
        name="browser_list_tabs",
        description="Liệt kê tabId và domain của các tab Chrome đang mở. Dùng khi người "
                    "dùng hỏi 'đang mở tab gì', hoặc để biết tab nào trước khi đóng.",
        input_schema={"type": "object", "properties": {}},
        handler=list_tabs,
        untrusted_output=True,   # nội dung do bên ngoài kiểm soát
    ))

    reg.register(Tool(
        name="browser_close_tab",
        description=("Đóng (các) tab Chrome có tiêu đề hoặc URL chứa 'keyword'. Trợ lý sẽ "
                     "tự hỏi xác nhận bằng tabId và domain, chỉ đóng tập tab đã duyệt."),
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
        prepare_confirmation=_prepare_close,
        # Domain vẫn là dữ liệu bên ngoài, không phải chỉ thị cho model.
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
