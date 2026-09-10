"""
Logging tập trung cho trợ lý ảo.

Dùng thay cho print() để có level (DEBUG/INFO/WARNING/ERROR), timestamp và
ghi ra file. Cấu hình qua utils.config (LOG_LEVEL, LOG_FILE, LOG_MAX_BYTES,
LOG_BACKUP_COUNT).

HAI NƠI log đi tới, đừng lẫn:
  - `assistant.log` (gốc repo): `launch_assistant.vbs` đổ stdout+stderr vào đó bằng `>`,
    nên nó có CẢ print() — nhưng bị GHI ĐÈ mỗi lần chạy, và chỉ có khi mở bằng launcher.
  - `logs/app.log` (LOG_FILE): do chính module này ghi, chỉ có dòng logger, nhưng SỐNG
    QUA nhiều lần chạy và có trần dung lượng. Chạy từ terminal thì chỉ file này có.
Logger KHÔNG ghi vào `assistant.log`: hai cơ chế cùng mở một file sẽ chèn lẫn nhau.

Cách dùng:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Đang lắng nghe...")
    logger.error("Lỗi khi gọi Ollama: %s", err)
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from utils.config import config

_configured = False
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _nen_ghi_file() -> bool:
    """Lượt chạy này có ghi log ra file không.

    Dưới pytest thì KHÔNG: log của test trộn vào log ứng dụng chỉ làm nhiễu đúng lúc cần
    chẩn đoán, mà bản thân test không cần lưu lại gì.
    """
    return bool(config.LOG_FILE) and "pytest" not in sys.modules


def _file_handler():
    """Handler ghi file có XOAY VÒNG, hoặc None nếu không mở được.

    Xoay vòng chứ không ghi thẳng: một phiên đã ~273 KB (đo 2026-08-28), để nguyên thì
    file phình không giới hạn — và lúc cần đọc để chẩn đoán lại đúng là lúc không mở nổi.
    """
    try:
        duong_dan = Path(config.LOG_FILE)
        duong_dan.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(duong_dan, maxBytes=config.LOG_MAX_BYTES,
                                      backupCount=config.LOG_BACKUP_COUNT, encoding="utf-8")
        # Console chỉ cần giờ (bạn đang ngồi xem, biết hôm nay là ngày nào); file thì
        # sống qua nhiều ngày nên giờ trần là mốc mơ hồ — phải có NGÀY.
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        return handler
    except OSError as e:
        # Mất log còn hơn không khởi động được trợ lý -> nuốt lỗi, vẫn còn console.
        print(f"(không mở được file log {config.LOG_FILE}: {e})")
        return None


def _configure_root():
    """Cấu hình root logger một lần (idempotent)."""
    global _configured
    if _configured:
        return

    level = getattr(logging, str(config.LOG_LEVEL).upper(), logging.INFO)

    # Console handler (stdout, hỗ trợ UTF-8 cho tiếng Việt)
    handlers = [logging.StreamHandler(sys.stdout)]

    if _nen_ghi_file():
        handler = _file_handler()
        if handler is not None:
            handlers.append(handler)

    logging.basicConfig(
        level=level,
        format=_FORMAT,
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Lấy logger đã cấu hình cho module."""
    _configure_root()
    return logging.getLogger(name)
