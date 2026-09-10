"""Cầu nối MCP client — kết nối tới một MCP server (stdio), lấy danh sách tool và gọi tool.

Nhái browser_bridge: chạy event loop asyncio ở THREAD NỀN, code đồng bộ gọi qua
run_coroutine_threadsafe (khớp kiến trúc đồng bộ của app). `mcp` SDK là phụ thuộc TÙY
CHỌN — thiếu thì bridge tự tắt, phần còn lại app vẫn chạy.

Phần LOGIC bridge (đăng ký MCP tool vào registry, heuristic destructive) tách khỏi kết nối
để test được bằng MCPClient GIẢ — xem _register_mcp_tools trong agent/tools.py và
`is_destructive_tool` dưới đây.
"""

import asyncio
import threading

from utils.logger import get_logger

logger = get_logger(__name__)


class MCPError(Exception):
    """Gọi MCP thất bại — NÉM chứ không trả về chuỗi trông như kết quả.

    Trước bản này `call_tool` trả chuỗi "(MCP báo lỗi) ..." khi hỏng. Nó đọc thì thân
    thiện, nhưng handler trả về bình thường nghĩa là `Agent._run_tool` xếp lượt đó là
    THÀNH CÔNG: `is_error=False`, và nhật ký kết quả ghi `ket_qua="xong"`. Hệ quả: MỌI
    lỗi MCP — hết hạn OAuth, server chết, mất mạng — đều vô hình với bộ đo
    (`docs/learning_from_experience_spec.md` §1.1).

    Đã xảy ra thật 2026-08-29: OAuth hết hạn, `gws_gmail_search` trả chuỗi lỗi, nhật ký
    ghi "xong". Mọi tool khác trong hệ đều NÉM khi hỏng; MCP là ngoại lệ duy nhất, và
    ngoại lệ đó chính là chỗ tín hiệu bị nuốt.
    """


# Từ khoá gợi ý tool GHI (khó hoàn tác) -> đánh dấu destructive (Agent hỏi xác nhận).
DEFAULT_DESTRUCTIVE_KEYWORDS = ("send", "create", "update", "delete", "remove",
                                "insert", "add", "move", "trash")


def is_destructive_tool(name, keywords=DEFAULT_DESTRUCTIVE_KEYWORDS):
    """True nếu tên tool chứa từ khoá GHI (gửi/tạo/xoá...). MCP không chuẩn hoá cờ này nên
    dùng heuristic theo tên; có thể ghi đè bằng cấu hình."""
    low = (name or "").lower()
    return any(k in low for k in keywords)


def _extract_text(result):
    """Gộp phần text trong kết quả call_tool của MCP thành một chuỗi cho agent đọc lại."""
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    joined = "\n".join(parts).strip()
    if getattr(result, "isError", False):
        return f"(MCP báo lỗi) {joined}" if joined else "(MCP báo lỗi)"
    return joined or "(không có nội dung trả về)"


class MCPClient:
    """Kết nối một MCP server qua stdio. `command`+`args` = lệnh chạy server (do bạn cấu hình)."""

    def __init__(self, command, args=None, env=None, timeout=30):
        self.command = command
        self.args = args or []
        self.env = env
        self.timeout = timeout
        self.loop = None
        self._thread = None
        self._session = None
        self._tools = []                  # [{name, description, input_schema}]
        self._ready = threading.Event()
        self._closed = None               # asyncio.Event, tạo trong loop

    @property
    def connected(self):
        return self._session is not None

    def start(self):
        """Khởi động ở thread nền + lấy danh sách tool. Trả True nếu kết nối được."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            logger.warning("Chưa cài 'mcp' — cầu nối MCP tắt (pip install mcp).")
            return False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=self.timeout)
        return self.connected

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._serve())
        except Exception as e:
            logger.error("Cầu nối MCP dừng do lỗi: %s", e)
            self._ready.set()
        finally:
            self.loop.close()

    async def _serve(self):
        """Giữ phiên MCP MỞ suốt vòng đời; call_tool lên lịch coroutine trên loop này."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
        self._closed = asyncio.Event()
        params = StdioServerParameters(command=self.command, args=self.args, env=self.env)
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    resp = await session.list_tools()
                    self._tools = [{
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": t.inputSchema or {"type": "object", "properties": {}},
                    } for t in resp.tools]
                    self._session = session
                    logger.info("MCP: đã kết nối server, %d tool.", len(self._tools))
                    self._ready.set()
                    await self._closed.wait()      # giữ mở tới khi stop()
        finally:
            self._session = None
            self._ready.set()

    def list_tools(self):
        return list(self._tools)

    def call_tool(self, name, arguments=None):
        """Gọi một MCP tool (đồng bộ). Trả chuỗi kết quả, hoặc NÉM `MCPError`.

        Ném chứ không trả chuỗi lỗi — xem docstring `MCPError`. Nơi gọi vẫn có câu chữ
        thân thiện để đọc cho người dùng, vì `Agent._run_tool` bắt ngoại lệ rồi tự dựng
        `ToolResult(is_error=True)`; khác biệt là bây giờ cờ lỗi ĐƯỢC BẬT.
        """
        if self.loop is None or not self.connected:
            raise MCPError("MCP chưa kết nối (server chưa chạy?).")
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self._call(name, arguments or {}), self.loop)
            return fut.result(self.timeout)
        except MCPError:
            raise                       # đã có nghĩa rồi, đừng bọc thêm một lớp nữa
        except Exception as e:
            logger.warning("MCP call_tool '%s' lỗi: %s", name, e)
            raise MCPError(f"gọi '{name}' thất bại: {e}") from e

    async def _call(self, name, arguments):
        result = await self._session.call_tool(name, arguments=arguments)
        text = _extract_text(result)
        # Server báo lỗi qua cờ `isError` chứ không qua ngoại lệ — quy về ngoại lệ ở ĐÂY,
        # chỗ duy nhất còn nhìn thấy cờ đó.
        if getattr(result, "isError", False):
            raise MCPError(text)
        return text

    def stop(self):
        if self.loop is not None and self._closed is not None:
            self.loop.call_soon_threadsafe(self._closed.set)
