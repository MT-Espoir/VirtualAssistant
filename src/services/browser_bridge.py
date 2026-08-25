"""
Cầu nối tới Chrome Extension qua WebSocket — chạy server ở THREAD NỀN, event loop
riêng, để hoà vào kiến trúc đồng bộ hiện tại (giống ReminderScheduler).

Thiết kế:
  - Python là SERVER (extension không chạy server được); extension là CLIENT.
  - Bind 127.0.0.1 (chỉ local) + bắt tay token đơn giản để chặn tiến trình lạ.
  - send_command() ĐỒNG BỘ: gắn request_id, gửi, chờ đúng phản hồi có timeout
    (request/response correlation) — nhờ vậy tool trả kết quả THẬT cho agent, không
    fire-and-forget.
  - Keepalive: server chủ động PING mỗi ~20s. Extension nhận message -> reset bộ
    đếm idle của service worker (MV3), giữ kết nối sống mà không phụ thuộc timer bên
    trong service worker.

'websockets' là phụ thuộc TÙY CHỌN, import lười — thiếu thì bridge tự tắt, phần còn
lại của app vẫn chạy bình thường.
"""

import asyncio
import json
import threading
import uuid

from utils.logger import get_logger

logger = get_logger(__name__)

KEEPALIVE_INTERVAL_S = 20      # < 30s để giữ service worker MV3 sống
_HANDSHAKE_TIMEOUT_S = 5


def is_origin_allowed(origin):
    """Chỉ cho phép kết nối từ EXTENSION Chrome (`chrome-extension://...`) hoặc client
    KHÔNG phải trình duyệt (không gửi Origin — vd test/native tin cậy).

    CHẶN mọi Origin http/https: một website độc có thể mở `ws://127.0.0.1:8765`, nhưng
    TRÌNH DUYỆT tự đặt Origin theo tên miền của site và JS không sửa được -> site không
    thể giả `chrome-extension://`. Đây là lớp chặn chính cho vector "website điều khiển
    bridge" (bổ sung cho token bắt tay)."""
    if not origin:
        return True
    return origin.startswith("chrome-extension://")


class BrowserBridge:
    def __init__(self, host="127.0.0.1", port=8765, token="", timeout=8):
        self.host = host
        self.port = port
        self.token = token
        self.timeout = timeout

        self.loop = None
        self._thread = None
        self._server = None
        self._client = None            # kết nối extension hiện tại
        self._pending = {}             # request_id -> asyncio.Future
        self._started = threading.Event()

    @property
    def connected(self) -> bool:
        return self._client is not None

    # ------------------------- vòng đời ------------------------- #
    def start(self) -> bool:
        """Khởi động server ở thread nền. Trả False nếu thiếu 'websockets'."""
        try:
            import websockets  # noqa: F401
            from websockets.asyncio.server import serve  # noqa: F401
        except ImportError:
            logger.warning("Chưa cài 'websockets' — cầu nối Chrome bị tắt "
                           "(pip install websockets).")
            return False

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._started.wait(timeout=5)
        return True

    def stop(self):
        """Đóng socket lắng nghe RỒI mới dừng vòng lặp.

        Chỉ gọi `loop.stop()` thì socket lắng nghe không bao giờ được đóng và cổng vẫn bị
        giữ tới khi tiến trình thoát hẳn — dựng lại bridge trên cùng cổng trong cùng một
        tiến trình sẽ hỏng với 'address already in use', và hỏng ÂM THẦM vì lỗi chỉ nằm
        trong log còn `connected` thì vẫn là False như lúc chưa có ai nối vào.
        """
        if self.loop is None:
            return
        if self._server is not None:
            async def _close():
                self._server.close()
                await self._server.wait_closed()

            try:
                asyncio.run_coroutine_threadsafe(_close(), self.loop).result(timeout=3)
            except Exception as e:
                logger.warning("Không đóng gọn được cầu nối Chrome: %s", e)
        self.loop.call_soon_threadsafe(self.loop.stop)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._start_server())
            self.loop.create_task(self._keepalive())
            self._started.set()
            self.loop.run_forever()
        except Exception as e:
            logger.error("Cầu nối Chrome dừng do lỗi: %s", e)
            self._started.set()
        finally:
            self.loop.close()

    async def _start_server(self):
        from websockets.asyncio.server import serve
        self._server = await serve(self._handler, self.host, self.port)
        logger.info("Cầu nối Chrome chạy ws://%s:%d (chờ extension kết nối)...",
                    self.host, self.port)

    # ------------------------- xử lý kết nối ------------------------- #
    def _origin_ok(self, ws):
        """Đọc Origin từ handshake WS (an toàn với mọi phiên bản websockets) rồi kiểm."""
        origin = None
        req = getattr(ws, "request", None)
        if req is not None:
            try:
                headers = req.headers
                origin = headers.get("Origin") or headers.get("origin")
            except Exception:
                origin = None
        return is_origin_allowed(origin)

    async def _handler(self, ws):
        """Một kết nối extension: kiểm Origin -> bắt tay token -> vòng nhận message."""
        if not self._origin_ok(ws):
            logger.warning("Từ chối kết nối WS: Origin không hợp lệ (chỉ nhận extension).")
            await ws.close()
            return
        if not await self._handshake(ws):
            return
        self._client = ws
        logger.info("Chrome Extension đã kết nối.")
        try:
            async for message in ws:
                self._on_message(message)
        except Exception as e:
            logger.info("Extension ngắt kết nối: %s", e)
        finally:
            if self._client is ws:
                self._client = None

    async def _handshake(self, ws):
        """Chờ HELLO {token}. Sai token -> đóng. Trả True nếu hợp lệ."""
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT_S)
            hello = json.loads(raw)
        except Exception:
            logger.warning("Bắt tay extension thất bại (không nhận được HELLO).")
            await ws.close()
            return False
        if self.token and hello.get("token") != self.token:
            logger.warning("Extension gửi token sai — từ chối kết nối.")
            await ws.close()
            return False
        return True

    def _on_message(self, message):
        """Khớp phản hồi theo request_id -> giải Future đang chờ."""
        try:
            data = json.loads(message)
        except ValueError:
            return
        rid = data.get("request_id")
        if not rid:
            return                              # PONG hoặc thông báo không cần khớp
        fut = self._pending.get(rid)
        if fut is not None and not fut.done():
            fut.set_result(data)

    async def _keepalive(self):
        while True:
            await asyncio.sleep(KEEPALIVE_INTERVAL_S)
            ws = self._client
            if ws is not None:
                try:
                    await ws.send(json.dumps({"action": "PING"}))
                except Exception:
                    pass

    # ------------------------- gửi lệnh (đồng bộ) ------------------------- #
    def send_command(self, action, timeout=None, **kwargs):
        """Gửi lệnh và CHỜ phản hồi tương ứng (đồng bộ). Trả dict phản hồi, hoặc
        dict {'type':'ERROR','message':...} thân thiện khi chưa kết nối/timeout."""
        if self.loop is None or not self.connected:
            logger.warning("Bridge: không gửi được '%s' — extension chưa kết nối "
                           "(kiểm tra: extension đã bật? token .env == token background.js?).",
                           action)
            return {"type": "ERROR", "message": "Chrome chưa kết nối (extension chưa bật?)."}

        timeout = timeout or self.timeout
        payload = {"action": action, **kwargs}
        try:
            cfut = asyncio.run_coroutine_threadsafe(
                self._send_and_wait(payload, timeout), self.loop)
            resp = cfut.result(timeout + 2)
            if isinstance(resp, dict) and resp.get("type") == "ERROR":
                logger.warning("Bridge: extension báo lỗi cho '%s': %s",
                               action, resp.get("message"))
            return resp
        except Exception as e:
            logger.warning("Bridge: lỗi/timeout khi gửi '%s' (extension treo/ngủ?): %s",
                           action, e)
            return {"type": "ERROR", "message": f"Lỗi cầu nối: {e}"}

    async def _send_and_wait(self, payload, timeout):
        rid = uuid.uuid4().hex[:8]
        payload["request_id"] = rid
        fut = self.loop.create_future()
        self._pending[rid] = fut
        try:
            await self._client.send(json.dumps(payload))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(rid, None)
