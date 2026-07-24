import speech_recognition as sr

from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)


class SpeechRecognizer:
    def __init__(self, language="vi-VN", engine="google", sample_rate=None):
        self.recognizer = sr.Recognizer()
        self.language = language
        self.engine = engine
        self.sample_rate = sample_rate or config.SAMPLE_RATE
        self.whisper_model = None

        # load Whisper
        if self.engine == "whisper":
            try:
                # First try the faster-whisper implementation
                from faster_whisper import WhisperModel
                logger.info("Loading Whisper model (faster-whisper)...")
                self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            except ImportError:
                try:
                    # Fall back to original whisper
                    import whisper
                    logger.info("Loading Whisper model (openai-whisper)...")
                    self.whisper_model = whisper.load_model("base")
                except (ImportError, TypeError):
                    logger.warning("Không tải được Whisper. Chuyển sang Google Speech Recognition.")
                    self.engine = "google"
        
    def recognize_speech(self, audio_file_path):
        if self.engine == "google":
            with sr.AudioFile(audio_file_path) as source:
                audio_data = self.recognizer.record(source)
                
            try:
                self.recognizer.energy_threshold = 300  # Default
                self.recognizer.dynamic_energy_threshold = True
                
                text = self.recognizer.recognize_google(audio_data, language=self.language)
                return text
            except sr.UnknownValueError:
                return "Google Speech Recognition could not understand audio"
            except sr.RequestError as e:
                return f"Could not request results from Google Speech Recognition service; {e}"
        
        elif self.engine == "whisper" and self.whisper_model:
            try:
                if hasattr(self.whisper_model, 'transcribe'):  # Original whisper
                    result = self.whisper_model.transcribe(audio_file_path, language="vi")
                    return result["text"]
                else:  # faster-whisper
                    segments, _ = self.whisper_model.transcribe(audio_file_path, language="vi")
                    text = " ".join([segment.text for segment in segments])
                    return text
            except Exception as e:
                logger.error("Whisper error: %s", e)
                # Google speech recognition
                return self.recognize_speech_with_engine(audio_file_path, "google")
        else:
            # Google if whisper isn't available
            return self.recognize_speech_with_engine(audio_file_path, "google")
    
    def recognize_speech_with_engine(self, audio_file_path, temp_engine):

        old_engine = self.engine
        self.engine = temp_engine
        result = self.recognize_speech(audio_file_path)
        self.engine = old_engine
        return result

    def recognize_speech_from_data(self, audio_data):
        """Nhận dạng giọng nói từ dữ liệu âm thanh (bytes) của recorder.

        Trả về chuỗi văn bản nếu nhận dạng được, ngược lại None (và log lý do).
        Phân biệt rõ: không nghe rõ (debug) vs lỗi mạng/dịch vụ (warning).
        """
        audio = sr.AudioData(audio_data, sample_rate=self.sample_rate, sample_width=2)

        try:
            if self.engine == "whisper":
                return self.recognizer.recognize_whisper(audio, language=self.language)
            return self.recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError:
            logger.debug("Không nghe rõ nội dung")
            return None
        except sr.RequestError as e:
            logger.warning("Lỗi gọi dịch vụ nhận dạng (kiểm tra mạng): %s", e)
            return None
        except Exception as e:  # phòng lỗi lạ từ backend whisper
            logger.error("Lỗi nhận dạng không mong đợi: %s", e)
            return None