"""
Nhận dạng giọng nói (STT) — hỗ trợ Google (online) và Whisper (offline).
"""

import speech_recognition as sr

from voice.corrections import correct as correct_transcript
from voice.stt_utils import whisper_lang_code
from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)


class SpeechRecognizer:
    def __init__(self, language="vi-VN", engine="google", sample_rate=None,
                 whisper_model=None):
        self.recognizer = sr.Recognizer()
        # CHỐNG TREO: giới hạn thời gian gọi dịch vụ nhận dạng (Google). Mặc định
        # recognize_google KHÔNG có timeout -> mạng chập là cả vòng agent đứng vĩnh
        # viễn. operation_timeout khiến nó ném lỗi (bắt được) thay vì treo.
        self.recognizer.operation_timeout = config.STT_TIMEOUT
        self.language = language
        self.engine = engine
        self.sample_rate = sample_rate or config.SAMPLE_RATE
        self.whisper_lang = whisper_lang_code(language)
        self.whisper_model_name = whisper_model or config.WHISPER_MODEL
        self._fw_model = None          # model faster-whisper (nạp một lần)

        if self.engine == "whisper":
            self._load_whisper()

    def _load_whisper(self):
        """Nạp faster-whisper nếu có. Lỗi thì để None -> tự lùi engine khác."""
        try:
            from faster_whisper import WhisperModel
            logger.info("Đang tải model Whisper (faster-whisper, cỡ '%s')...",
                        self.whisper_model_name)
            self._fw_model = WhisperModel(self.whisper_model_name,
                                          device="cpu", compute_type="int8")
        except ImportError:
            logger.info("Chưa có faster-whisper; sẽ thử openai-whisper khi nhận dạng.")
        except Exception as e:
            logger.warning("Không tải được faster-whisper (%s); sẽ thử openai-whisper.", e)

    def recognize_speech_from_data(self, audio_data):
        """Nhận dạng từ bytes âm thanh của recorder.
        Trả về văn bản (đã qua lớp sửa lỗi) nếu nhận dạng được, ngược lại None.
        Phân biệt: không nghe rõ (debug) vs lỗi mạng/dịch vụ (warning).
        """
        try:
            if self.engine == "whisper":
                text = self._whisper_from_data(audio_data)
            else:
                audio = sr.AudioData(audio_data, sample_rate=self.sample_rate, sample_width=2)
                text = self.recognizer.recognize_google(audio, language=self.language)

            text = (text or "").strip()
            if not text:
                logger.debug("Không nghe rõ nội dung")
                return None
            return correct_transcript(text)
        except sr.UnknownValueError:
            logger.debug("Không nghe rõ nội dung")
            return None
        except sr.RequestError as e:
            logger.warning("Lỗi gọi dịch vụ nhận dạng (kiểm tra mạng): %s", e)
            return None
        except Exception as e:  # phòng lỗi lạ từ backend whisper
            logger.error("Lỗi nhận dạng không mong đợi: %s", e)
            return None

    def _whisper_from_data(self, audio_data):
        """Chạy Whisper trên bytes PCM 16-bit. faster-whisper trước, rồi openai-whisper."""
        if self._fw_model is not None:
            import numpy as np
            # PCM int16 -> float32 [-1, 1], đúng định dạng faster-whisper cần (16kHz mono).
            samples = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _ = self._fw_model.transcribe(samples, language=self.whisper_lang)
            return " ".join(seg.text for seg in segments).strip()

        # Không có faster-whisper: dùng openai-whisper qua speech_recognition.
        audio = sr.AudioData(audio_data, sample_rate=self.sample_rate, sample_width=2)
        return self.recognizer.recognize_whisper(
            audio, model=self.whisper_model_name, language=self.whisper_lang)
