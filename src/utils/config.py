"""
Cấu hình tập trung cho trợ lý ảo.

Mọi tham số vận hành (audio, ngôn ngữ, engine STT/TTS, LLM) được gom về đây và đọc
từ biến môi trường. Cách override: đặt biến trong file `src/.env` (xem `.env.example`)
hoặc đặt trực tiếp ở shell — KHÔNG cần sửa code.

Thứ tự ưu tiên: biến môi trường thật (shell) > `src/.env` > mặc định trong file này.

Cách dùng:
    from utils.config import config
    rate = config.SAMPLE_RATE
"""

import os
from pathlib import Path

# Nạp `src/.env` theo ĐƯỜNG DẪN TUYỆT ĐỐI (cạnh các entry point) để không phụ thuộc
# thư mục đang chạy lệnh. Cần `pip install python-dotenv`; không có thì bỏ qua (vẫn
# đọc được biến môi trường thật). override=False: biến shell có sẵn được giữ nguyên.
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"    # .../src/.env
try:
    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH, override=False)
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


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


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
    # google (online, nhanh, kém với tiếng Anh) | whisper (offline, chính xác hơn,
    # xử lý tốt câu Việt xen tiếng Anh; lần đầu tải model, chậm hơn khi chạy CPU)
    STT_ENGINE = _get("STT_ENGINE", "google")
    # Cỡ model Whisper: tiny (nhanh nhất) | base | small | medium (chính xác nhất).
    WHISPER_MODEL = _get("WHISPER_MODEL", "base")
    # Giới hạn thời gian (giây) gọi dịch vụ STT (Google) — chống treo khi mạng chập.
    STT_TIMEOUT = _get_int("STT_TIMEOUT", 15)

    # --- Đầu vào cho app.py (launcher hợp nhất) ---
    # auto: thử micro, lỗi (thiếu PyAudio/không có mic) thì tự chuyển sang gõ phím
    # voice: bắt buộc micro (lỗi thì dừng) | text: luôn gõ phím
    INPUT_MODE = _get("INPUT_MODE", "auto")

    # --- Cầu nối điều khiển Chrome (extension qua WebSocket) ---
    # Bật để agent điều khiển media/tab trên Chrome. Cần cài extension trong
    # thư mục chrome_extension/ và `pip install websockets`.
    BROWSER_BRIDGE_ENABLED = _get_bool("BROWSER_BRIDGE_ENABLED", True)
    BROWSER_BRIDGE_HOST = _get("BROWSER_BRIDGE_HOST","127.0.0.1")
    BROWSER_BRIDGE_PORT = _get_int("BROWSER_BRIDGE_PORT","8765")
    # Token bắt tay — PHẢI trùng với TOKEN trong chrome_extension/background.js.
    # CHỈ đọc từ biến môi trường (đặt trong src/.env, KHÔNG hard-code trong code).
    # Rỗng = bỏ kiểm token (chỉ nên vậy khi thử cục bộ); nên đặt token để an toàn.
    BROWSER_BRIDGE_TOKEN = _get("BROWSER_BRIDGE_TOKEN", "")

    # --- Điều khiển/đọc màn hình (chụp, OCR tìm chữ, cuộn) — NHẠY CẢM, mặc định TẮT ---
    # Bảo mật: chỉ bật khi bạn chủ động cho phép. Nội dung màn hình (chữ OCR) sẽ đi
    # tới LLM -> chỉ hoạt động với LLM LOCAL (ollama); app tự từ chối nếu dùng online.
    SCREEN_CONTROL_ENABLED = _get_bool("SCREEN_CONTROL_ENABLED", False)
    SCREEN_CAPTURE_DIR = _get("SCREEN_CAPTURE_DIR", "")   # rỗng = <gốc dự án>/captures
    TESSERACT_CMD = _get("TESSERACT_CMD", "")             # rỗng = tự dò đường dẫn

    # --- Từ khoá kích hoạt (wake word) — chỉ áp dụng khi nhập bằng giọng nói ---
    # Bật để trợ lý chỉ hành động với câu có chứa từ khoá; giúp bỏ qua lời nhạc/clip
    # phát ra loa (tránh mic thu lại rồi tự trả lời loạn).
    REQUIRE_WAKE_WORD = _get_bool("REQUIRE_WAKE_WORD", True)
    WAKE_WORDS = _get("WAKE_WORDS", "trợ lý,tro ly,jarvis,ying,assistant")
    # Barge-in: cho phép ngắt lời AI đang nói bằng wake word (chỉ khi dùng giọng nói
    # + đã bật REQUIRE_WAKE_WORD). Không cần AEC; đánh đổi độ tin cậy (xem docs).
    BARGE_IN = _get_bool("BARGE_IN", True)
    # Fast-path: lệnh trực tiếp (cuộn, chụp màn hình) chạy thẳng tool, không qua LLM
    # -> phản hồi tức thì, đỡ độ trễ "suy nghĩ" của model local.
    FAST_COMMANDS = _get_bool("FAST_COMMANDS", True)
    # Router: dùng 1 lượt LLM phân loại yêu cầu -> thu hẹp prompt+tool cho model chọn
    # đúng hơn. Tắt (=false) nếu muốn nhanh hơn (đưa toàn bộ tool cho LLM như cũ) —
    # KHÔNG khuyến khích: đã thử, model nhỏ chọn sai/không gọi tool khi thấy nhiều tool.
    USE_ROUTER = _get_bool("USE_ROUTER", True)

    # --- Avatar (cửa sổ khuôn mặt) ---
    AVATAR_SCALE = _get_float("AVATAR_SCALE", 0.7)     # kích thước (0.4–1.5), nhỏ hơn = gọn
    AVATAR_OPACITY = _get_float("AVATAR_OPACITY", 1.0)  # độ mờ (0.25–1.0)

    # --- Tổng hợp giọng nói (TTS) ---
    TTS_ENGINE = _get("TTS_ENGINE", "gtts")
    TTS_LANGUAGE = _get("TTS_LANGUAGE", "vi")
    # Giọng robot: áp ring modulation lên giọng gTTS (giữ phát âm tiếng Việt)
    TTS_ROBOT = _get_bool("TTS_ROBOT", False)
    TTS_ROBOT_CARRIER = _get_int("TTS_ROBOT_CARRIER", 80)   # Hz; thấp = robot hơn
    # Tốc độ nói: >1 nhanh hơn (vd 1.3). pyttsx3 giữ cao độ; gTTS nhanh hơn = cao giọng hơn.
    TTS_SPEED = _get_float("TTS_SPEED", 1.0)

    # --- LLM: agent tool-calling ---
    # LLM_PROVIDER: "ollama" (local, mặc định) | "claude" (API) | "gemini" (API, xoay model)
    LLM_PROVIDER = _get("LLM_PROVIDER", "ollama")
    LLM_MODEL = _get("LLM_MODEL", "claude-opus-4-8")   # dùng khi provider=claude
    LLM_MAX_TOKENS = _get_int("LLM_MAX_TOKENS", 1024)

    # --- Bộ nhớ hội thoại ---
    MAX_HISTORY_TURNS = _get_int("MAX_HISTORY_TURNS", 10)
    # Đường dẫn file lưu bộ nhớ (rỗng = chỉ nhớ trong phiên, không lưu ra file)
    MEMORY_PATH = _get("MEMORY_PATH", "")

    # --- Gemini API (LLM_PROVIDER=gemini) — XOAY VÒNG model theo hạn mức free tier ---
    GEMINI_API_KEY = _get("GEMINI_API_KEY", "")
    # Danh sách model theo THỨ TỰ ưu tiên: "tên:RPM:RPD" cách nhau bởi dấu phẩy. Mỗi lượt
    # dùng model khả dụng đầu tiên; hết RPM chặn ~60s (rơi xuống model kế rồi tự quay lại),
    # hết RPD chặn tới hết ngày. RPM/RPD = 0 nghĩa là không giới hạn. ĐỔI tên model cho
    # khớp ID thật trong Google AI Studio nếu cần.
    GEMINI_MODELS = _get(
        "GEMINI_MODELS",
        "gemini-2.5-flash:5:20,gemini-2.5-flash-lite:10:20,gemini-3.1-flash-lite:15:500")

    # --- LLM local qua Ollama ---
    OLLAMA_URL = _get("OLLAMA_URL", "http://localhost:11434")
    # Model local cần hỗ trợ tool-calling (qwen2.5, llama3.1, mistral-nemo...)
    OLLAMA_MODEL = _get("OLLAMA_MODEL", "qwen2.5:3b-instruct")
    # Thời gian chờ tối đa (giây) mỗi lượt gọi model local. Model to (7B) chạy CPU có
    # thể lâu -> tăng nếu hay gặp 'Read timed out'; giảm nếu muốn bỏ sớm khi model treo.
    LLM_TIMEOUT = _get_int("LLM_TIMEOUT", 180)

    # --- Thời tiết (Open-Meteo) ---
    # Địa điểm mặc định khi người dùng hỏi "thời tiết hôm nay" mà không nói thành phố.
    WEATHER_DEFAULT_LOCATION = _get("WEATHER_DEFAULT_LOCATION", "Hà Nội")

    # --- Tìm web + đọc kết quả (qua extension Chrome đọc DOM) ---
    # Engine mặc định cho web_search_list: google | duckduckgo. Cần extension bật +
    # host_permissions cho miền tương ứng (xem chrome_extension/manifest.json).
    WEB_SEARCH_ENGINE = _get("WEB_SEARCH_ENGINE", "google")

    # --- Logging ---
    LOG_LEVEL = _get("LOG_LEVEL", "INFO")
    LOG_FILE = _get("LOG_FILE", "")   # rỗng = chỉ log ra console


# Instance dùng chung toàn dự án
config = Config()
