"""
Logging tập trung cho trợ lý ảo.

Dùng thay cho print() để có level (DEBUG/INFO/WARNING/ERROR), timestamp và
tùy chọn ghi ra file. Cấu hình qua utils.config (LOG_LEVEL, LOG_FILE).

Cách dùng:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Đang lắng nghe...")
    logger.error("Lỗi khi gọi Ollama: %s", err)
"""

import logging
import sys

from utils.config import config

_configured = False


def _configure_root():
    """Cấu hình root logger một lần (idempotent)."""
    global _configured
    if _configured:
        return

    level = getattr(logging, str(config.LOG_LEVEL).upper(), logging.INFO)
    handlers = []

    # Console handler (stdout, hỗ trợ UTF-8 cho tiếng Việt)
    console = logging.StreamHandler(sys.stdout)
    handlers.append(console)

    # File handler (nếu cấu hình LOG_FILE)
    if config.LOG_FILE:
        try:
            handlers.append(logging.FileHandler(config.LOG_FILE, encoding="utf-8"))
        except OSError:
            # Không mở được file log thì bỏ qua, vẫn log ra console
            pass

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Lấy logger đã cấu hình cho module."""
    _configure_root()
    return logging.getLogger(name)
