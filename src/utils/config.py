"""
Cấu hình tập trung cho trợ lý ảo.

Mọi tham số vận hành (audio, ngôn ngữ, engine STT/TTS, LLM) được gom về đây.
Có thể override từng giá trị bằng biến môi trường (hoặc file .env, xem .env.example)
mà không cần sửa code — ví dụ:  set OLLAMA_MODEL=llama3

Cách dùng:
    from utils.config import config
    rate = config.SAMPLE_RATE
"""

import os

# Tùy chọn: nạp file .env nếu có cài python-dotenv (không bắt buộc).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get(name: str, default: str) -> str:
    """Đọc biến môi trường, trả về default nếu không có."""
    return os.getenv(name, default)


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    """Cấu hình toàn cục (đọc một lần khi khởi động)."""

    # --- Audio / ghi âm ---
    AUDIO_FORMAT = _get("AUDIO_FORMAT", "wav")
    SAMPLE_RATE = _get_int("SAMPLE_RATE", 16000)   # 16kHz chuẩn cho nhận dạng giọng nói
    CHUNK_SIZE = _get_int("CHUNK_SIZE", 1024)
    CHANNELS = _get_int("CHANNELS", 1)
    SPEECH_THRESHOLD_RATIO = _get_float("SPEECH_THRESHOLD_RATIO", 1.2)

    # --- Nhận dạng giọng nói (STT) ---
    STT_LANGUAGE = _get("STT_LANGUAGE", "vi-VN")
    STT_ENGINE = _get("STT_ENGINE", "google")

    # --- Tổng hợp giọng nói (TTS) ---
    TTS_ENGINE = _get("TTS_ENGINE", "gtts")
    TTS_LANGUAGE = _get("TTS_LANGUAGE", "vi")

    # --- LLM: agent tool-calling ---
    # LLM_PROVIDER: "ollama" (local, mặc định) | "claude" (API)
    LLM_PROVIDER = _get("LLM_PROVIDER", "ollama")
    LLM_MODEL = _get("LLM_MODEL", "claude-opus-4-8")   # dùng khi provider=claude
    LLM_MAX_TOKENS = _get_int("LLM_MAX_TOKENS", 1024)

    # --- Bộ nhớ hội thoại ---
    MAX_HISTORY_TURNS = _get_int("MAX_HISTORY_TURNS", 10)
    # Đường dẫn file lưu bộ nhớ (rỗng = chỉ nhớ trong phiên, không lưu ra file)
    MEMORY_PATH = _get("MEMORY_PATH", "")

    # --- LLM local qua Ollama ---
    OLLAMA_URL = _get("OLLAMA_URL", "http://localhost:11434")
    # Model local cần hỗ trợ tool-calling (qwen2.5, llama3.1, mistral-nemo...)
    OLLAMA_MODEL = _get("OLLAMA_MODEL", "qwen2.5:3b-instruct")

    # --- Logging ---
    LOG_LEVEL = _get("LOG_LEVEL", "INFO")
    LOG_FILE = _get("LOG_FILE", "")   # rỗng = chỉ log ra console


# Instance dùng chung toàn dự án
config = Config()
