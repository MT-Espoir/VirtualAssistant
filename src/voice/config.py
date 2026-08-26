"""
Toàn bộ cấu hình GIỌNG NÓI của trợ lý — một chỗ duy nhất.

Trước đây 18 tham số giọng nói nằm rải trong `utils/config.py` xen giữa cấu hình LLM,
đường dẫn dữ liệu, cờ tính năng... Muốn biết "trợ lý nói bằng gì, nghe thế nào" thì phải
lọc bằng mắt. Gom về đây để chúng đọc được như một khối, và để việc thay giọng (đổi sang
giọng tự huấn luyện) chỉ đụng một file.

`utils/config.py` VẪN là nơi đọc biến môi trường — module này không đọc `os.environ`,
chỉ nhóm lại và đặt tên cho có nghĩa. Một nguồn sự thật, hai cách nhìn.

Xem `docs/voice_finetune_spec.md` cho phần huấn luyện giọng riêng.
"""

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(frozen=True)
class NgheConfig:
    """Đầu vào: micro + nhận dạng tiếng nói (STT)."""
    input_mode: str = "auto"           # auto | voice | text
    engine: str = "google"             # google | whisper
    language: str = "vi-VN"
    timeout_s: int = 10                # chống treo khi mạng lag
    whisper_model: str = "base"        # chỉ dùng khi engine=whisper

    # Tham số thu âm (VAD dựa trên RMS, không dùng thư viện VAD ngoài)
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    silence_duration: float = 1.5      # im lặng bao lâu thì coi là nói xong
    speech_threshold_ratio: float = 1.0
    max_utterance_s: float = 15.0


@dataclass(frozen=True)
class NoiConfig:
    """Đầu ra: tổng hợp tiếng nói (TTS).

    `engine` quyết định giọng:
      gtts     — Google, cần mạng, giọng chung ai cũng có
      pyttsx3  — giọng hệ điều hành, offline
      piper    — giọng đã FINE-TUNE (ONNX), offline; xem `piper_*` bên dưới
      vieneu   — giọng CLONE từ ~3s audio mẫu, KHÔNG cần huấn luyện; xem `vieneu_*`
    """
    engine: str = "gtts"
    language: str = "vi"
    speed: float = 1.5                 # >1 nhanh hơn
    robot: bool = False                # hiệu ứng giọng robot
    robot_carrier: int = 80            # Hz; thấp = robot hơn

    # --- giọng riêng (Piper / VITS đã fine-tune) ---
    # Đường dẫn tới model đã xuất. Piper xuất ra CẶP file: `<tên>.onnx` (trọng số) và
    # `<tên>.onnx.json` (cấu hình phoneme + sample rate). Thiếu một trong hai là không chạy.
    piper_model: str = ""
    piper_config: str = ""             # để trống -> suy ra là `<piper_model>.json`
    piper_speaker: int = 0             # model nhiều giọng mới cần; giọng riêng thường 0
    # Hai núm tinh chỉnh lúc suy luận, KHÔNG cần huấn luyện lại:
    piper_length_scale: float = 1.0    # >1 nói chậm lại
    piper_noise_scale: float = 0.667   # biến thiên ngữ điệu; thấp = đều đều hơn

    # --- giọng clone (VieNeu-TTS) ---
    # Chỉ cần MỘT đoạn thu ~3 giây. Đổi file này là đổi giọng — không huấn luyện lại.
    vieneu_ref_audio: str = ""
    # `v3turbo` (mặc định): 48 kHz, chạy ONNX Runtime, không cần torch/llama_cpp.
    vieneu_mode: str = "v3turbo"
    vieneu_precision: str = "int8"


@dataclass(frozen=True)
class VoiceConfig:
    """Gom cả hai chiều + từ đánh thức."""
    nghe: NgheConfig = field(default_factory=NgheConfig)
    noi: NoiConfig = field(default_factory=NoiConfig)
    wake_words: Tuple[str, ...] = ()
    require_wake_word: bool = True

    @property
    def dung_giong_rieng(self) -> bool:
        return self.noi.engine in ("piper", "vieneu")


def from_config(config) -> VoiceConfig:
    """Dựng `VoiceConfig` từ `utils.config.config`.

    Đọc bằng `getattr` có mặc định: các tham số Piper chỉ tồn tại khi người dùng khai
    trong `.env`, và trợ lý phải chạy được khi chưa ai nghĩ tới giọng riêng.
    """
    def g(ten, mac_dinh):
        return getattr(config, ten, mac_dinh)

    wake = tuple(w.strip() for w in str(g("WAKE_WORDS", "")).split(",") if w.strip())
    return VoiceConfig(
        nghe=NgheConfig(
            input_mode=g("INPUT_MODE", "auto"),
            engine=g("STT_ENGINE", "google"),
            language=g("STT_LANGUAGE", "vi-VN"),
            timeout_s=g("STT_TIMEOUT", 10),
            whisper_model=g("WHISPER_MODEL", "base"),
            sample_rate=g("SAMPLE_RATE", 16000),
            channels=g("CHANNELS", 1),
            chunk_size=g("CHUNK_SIZE", 1024),
            silence_duration=g("SILENCE_DURATION", 1.5),
            speech_threshold_ratio=g("SPEECH_THRESHOLD_RATIO", 1.0),
            max_utterance_s=g("MAX_UTTERANCE_SECONDS", 15.0),
        ),
        noi=NoiConfig(
            engine=g("TTS_ENGINE", "gtts"),
            language=g("TTS_LANGUAGE", "vi"),
            speed=g("TTS_SPEED", 1.0),
            robot=g("TTS_ROBOT", False),
            robot_carrier=g("TTS_ROBOT_CARRIER", 80),
            piper_model=g("PIPER_MODEL", ""),
            piper_config=g("PIPER_CONFIG", ""),
            piper_speaker=g("PIPER_SPEAKER", 0),
            piper_length_scale=g("PIPER_LENGTH_SCALE", 1.0),
            piper_noise_scale=g("PIPER_NOISE_SCALE", 0.667),
            vieneu_ref_audio=g("VIENEU_REF_AUDIO", ""),
            vieneu_mode=g("VIENEU_MODE", "v3turbo"),
            vieneu_precision=g("VIENEU_PRECISION", "int8"),
        ),
        wake_words=wake,
        require_wake_word=g("REQUIRE_WAKE_WORD", True),
    )
