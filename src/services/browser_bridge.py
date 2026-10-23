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
import hmac
import json
import threading
import uuid

from utils.logger import get_logger
from utils.telemetry import annotate, mark, measured, trace_headers

logger = get_logger(__name__)

KEEPALIVE_INTERVAL_S = 20      # < 30s để giữ service worker MV3 sống
_HANDSHAKE_TIMEOUT_S = 5
PROTOCOL_VERSION = 2
_DATA_ACTIONS = {"PING", "GET_TABS", "CONTROL_MEDIA", "GET_MEDIA_STATE",
                 "CLOSE_TAB_BY_KEYWORD", "OPEN_OR_REUSE_URL"}
_HELLO_FIELDS = {"type", "token", "protocolVersion", "profileId", "sessionId"}
_MAX_HELLO_BYTES = 4096
_MAX_ACCEPTED_SESSIONS = 4096


def _anonymous_id(value):
    """Canonical random UUID, never an account name, path or browser fingerprint."""
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
        return parsed.version == 4 and str(parsed) == value
    except (ValueError, AttributeError):
        return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


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
        self._connection_id = None      # opaque local session; not a Chrome profile ID
        self._pending = {}             # request_id -> asyncio.Future
        self._pending_sources = {}     # every request is bound to its socket
        self._selected_profile_id = None  # pinned for this bridge process, even offline
        self._profile_id = None
        self._session_id = None
        self._seen_session_ids = set()
        self._last_rejection = None    # reason code only, never HELLO/token content
        self._started = threading.Event()
        # None = extension chưa kết nối/chưa gửi snapshot; bool = duy nhất dữ liệu Meet
        # được phép rời extension. Không URL/title/tab id.
        self._meeting_open = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    @property
    def connection_id(self):
        return self._connection_id if self.connected else None

    @property
    def selected_profile_id(self):
        return self._selected_profile_id

    @property
    def profile_id(self):
        return self._profile_id if self.connected else None

    @property
    def connection_status(self):
        return {"state": "connected" if self.connected else
                "awaiting_selected_profile" if self._selected_profile_id else "waiting",
                "last_rejection": self._last_rejection}

    @property
    def meeting_open(self):
        return self._meeting_open

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
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
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
            await self._reject(ws, "origin_not_allowed")
            return
        identity = await self._handshake(ws)
        if identity is None:
            return
        # No await between arbitration and installing the owner. Concurrent HELLOs
        # cannot both win; a later authenticated client never replaces the owner.
        if self._client is not None:
            await self._reject(ws, "client_already_active")
            return
        if self._selected_profile_id is not None and identity["profileId"] != self._selected_profile_id:
            await self._reject(ws, "profile_not_selected")
            return
        if identity["sessionId"] in self._seen_session_ids:
            await self._reject(ws, "session_replayed")
            return
        if len(self._seen_session_ids) >= _MAX_ACCEPTED_SESSIONS:
            await self._reject(ws, "session_history_full")
            return
        self._selected_profile_id = identity["profileId"]
        self._seen_session_ids.add(identity["sessionId"])
        self._profile_id, self._session_id = identity["profileId"], identity["sessionId"]
        self._connection_id = uuid.uuid4().hex
        self._meeting_open = None
        self._client = ws
        logger.info("Chrome Extension đã kết nối.")
        try:
            async for message in ws:
                self._on_message(message, ws)
        except Exception as e:
            logger.info("Extension ngắt kết nối: %s", e)
        finally:
            if self._client is ws:
                self._client = None
                self._connection_id = None
                self._profile_id = self._session_id = None
                self._meeting_open = None
                for rid, source in list(self._pending_sources.items()):
                    future = self._pending.get(rid)
                    if source is ws and future is not None and not future.done():
                        future.set_result({"type": "ERROR", "request_id": rid,
                                           "reason": "connection_lost", "outcome": "unknown",
                                           "message": "Kết nối Chrome ngắt trong khi xử lý; chưa xác nhận kết quả. Không tự gửi lại."})

    async def _reject(self, ws, reason):
        self._last_rejection = reason
        logger.warning("Từ chối kết nối extension: %s", reason)
        try:
            await ws.close()
        except Exception:
            pass

    async def _handshake(self, ws):
        """Strict versioned HELLO; return only anonymous identity after authentication."""
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=_HANDSHAKE_TIMEOUT_S)
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > _MAX_HELLO_BYTES:
                raise ValueError("invalid_hello_frame")
            hello = json.loads(raw, object_pairs_hook=_unique_object)
        except Exception:
            await self._reject(ws, "invalid_hello_frame")
            return None
        if (not isinstance(hello, dict) or set(hello) != _HELLO_FIELDS
                or hello.get("type") != "HELLO"
                or type(hello.get("protocolVersion")) is not int
                or hello["protocolVersion"] != PROTOCOL_VERSION
                or not _anonymous_id(hello.get("profileId")) or not _anonymous_id(hello.get("sessionId"))):
            await self._reject(ws, "invalid_hello_schema")
            return None
        candidate = hello.get("token")
        authenticated = False
        if isinstance(self.token, str) and self.token and isinstance(candidate, str):
            try:
                authenticated = hmac.compare_digest(candidate.encode("utf-8"), self.token.encode("utf-8"))
            except UnicodeError:
                pass
        if not authenticated:
            await self._reject(ws, "authentication_failed")
            return None
        return {"profileId": hello["profileId"], "sessionId": hello["sessionId"]}

    def _on_message(self, message, ws=None):
        """Only the active owner may publish state or fulfill its own pending request."""
        if ws is None or ws is not self._client:
            return
        try:
            data = json.loads(message, object_pairs_hook=_unique_object)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        if data.get("type") == "MEETING_STATE":
            return
        rid = data.get("request_id")
        if not isinstance(rid, str) or not rid:
            return                              # PONG hoặc thông báo không cần khớp
        if self._pending_sources.get(rid) is not ws:
            return
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
    @measured("browser_media", "browser_roundtrip")
    def send_command(self, action, timeout=None, expected_connection=None, **kwargs):
        """Gửi lệnh và CHỜ phản hồi tương ứng (đồng bộ). Trả dict phản hồi, hoặc
        dict {'type':'ERROR','message':...} thân thiện khi chưa kết nối/timeout."""
        if action not in _DATA_ACTIONS:
            return {"type": "ERROR", "reason": "data_scope_not_authorized", "outcome": "failed",
                    "message": "Đường đọc nội dung trang đang tạm khóa. Chưa gửi lệnh."}
        if self.loop is None or not self.connected:
            annotate(outcome="failed", dependency="unavailable")
            logger.warning("Bridge: không gửi được '%s' — extension chưa kết nối "
                           "(kiểm tra: extension đã bật? token .env == token background.js?).",
                           action)
            reason = "selected_profile_disconnected" if self._selected_profile_id else "no_client"
            message = ("Profile Chrome đã ghim đang ngắt kết nối; chưa gửi lệnh. Client khác không được tự thay đích."
                       if self._selected_profile_id else "Chrome chưa kết nối (cần kiểm tra extension/HELLO/token).")
            return {"type": "ERROR", "reason": reason, "outcome": "failed", "message": message}

        timeout = timeout or self.timeout
        annotate(dependency="available")
        payload = {"action": action, **kwargs, **trace_headers()}
        if expected_connection is None:
            expected_connection = self.connection_id
        cfut = None
        try:
            cfut = asyncio.run_coroutine_threadsafe(
                self._send_and_wait(payload, timeout, expected_connection), self.loop)
            resp = cfut.result(timeout + 2)
            if isinstance(resp, dict) and resp.get("type") == "ERROR":
                annotate(outcome="unknown" if resp.get("outcome") == "unknown" else "failed")
                logger.warning("Bridge: extension báo lỗi cho '%s': %s",
                               action, resp.get("message"))
            return resp
        except Exception as e:
            if cfut is not None:
                cancel = getattr(cfut, "cancel", None)
                if cancel is not None:
                    cancel()
            annotate(outcome="unknown", error_type=type(e).__name__)
            logger.warning("Bridge: lỗi/timeout khi gửi '%s' (extension treo/ngủ?): %s",
                           action, type(e).__name__)
            return {"type": "ERROR", "reason": "transport_error", "outcome": "unknown",
                    "message": f"Lỗi cầu nối ({type(e).__name__}); chưa xác nhận kết quả. Không tự gửi lại."}

    async def _send_and_wait(self, payload, timeout, expected_connection=None):
        if payload.get("action") not in _DATA_ACTIONS:
            return {"type": "ERROR", "reason": "data_scope_not_authorized",
                    "message": "Chưa có quyền đọc nội dung trang."}
        ws = self._client
        if ws is None or (expected_connection is not None
                          and expected_connection != self.connection_id):
            return {"type": "ERROR", "reason": "connection_changed",
                    "message": "Kết nối Chrome đã đổi. Cần xem lại tab và xác nhận lại."}
        rid = uuid.uuid4().hex
        payload["request_id"] = rid
        fut = self.loop.create_future()
        self._pending[rid] = fut
        self._pending_sources[rid] = ws
        deadline = self.loop.time() + timeout
        try:
            await asyncio.wait_for(ws.send(json.dumps(payload)), timeout)
            mark("packet_sent")
            return await asyncio.wait_for(fut, max(0, deadline - self.loop.time()))
        finally:
            self._pending.pop(rid, None)
            self._pending_sources.pop(rid, None)
