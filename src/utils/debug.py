"""Hạ tầng log có cấu trúc cho panel debug thời gian thực.

Module này không biết Tkinter. Producer ở bất kỳ thread nào chỉ đẩy dict đã làm sạch
vào ``AssistantBus``; cửa sổ avatar mới là nơi đọc queue và vẽ trên main thread.
"""

import logging
from utils.privacy import logger_group


_SECRET_MARKERS = ("password", "passwd", "secret", "token", "api_key", "apikey",
                   "authorization", "cookie", "credential")
_MAX_TEXT = 1200
_MAX_ITEMS = 30


def _secret_key(key):
    normalized = str(key or "").lower().replace("-", "_")
    return any(marker in normalized for marker in _SECRET_MARKERS)


def safe_debug_value(value, key=None, depth=0):
    """Sao chép payload cho UI, che secret và đặt trần để panel không bị nghẽn."""
    if key is not None and _secret_key(key):
        return "<đã che>"
    if depth >= 5:
        return "<quá sâu>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= _MAX_TEXT else value[:_MAX_TEXT] + "…"
    if isinstance(value, dict):
        items = list(value.items())
        result = {str(k): safe_debug_value(v, key=k, depth=depth + 1)
                  for k, v in items[:_MAX_ITEMS]}
        if len(items) > _MAX_ITEMS:
            result["…"] = f"còn {len(items) - _MAX_ITEMS} trường"
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        result = [safe_debug_value(v, depth=depth + 1) for v in items[:_MAX_ITEMS]]
        if len(items) > _MAX_ITEMS:
            result.append(f"… còn {len(items) - _MAX_ITEMS} mục")
        return result
    return safe_debug_value(str(value), depth=depth + 1)


class DebugBusLogHandler(logging.Handler):
    """Chuyển record của logging sang AssistantBus mà không ghi file lần thứ hai."""

    def __init__(self, bus):
        super().__init__(level=logging.DEBUG)
        self.bus = bus

    def emit(self, record):
        try:
            details = {"logger": logger_group(record.name)}
            self.bus.emit_debug(
                "log", "Log record", details,
                level=record.levelname,
            )
        except Exception:
            # Debug UI là observer phụ trợ; tuyệt đối không được làm hỏng luồng thật.
            self.handleError(record)


def install_bus_log_handler(bus):
    handler = DebugBusLogHandler(bus)
    logging.getLogger().addHandler(handler)
    return handler


def uninstall_bus_log_handler(handler):
    if handler is None:
        return
    logging.getLogger().removeHandler(handler)
    handler.close()
