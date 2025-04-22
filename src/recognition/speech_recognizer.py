import speech_recognition as sr
import os

class SpeechRecognizer:
    def __init__(self, language="vi-VN", engine="google"):
        self.recognizer = sr.Recognizer()
        self.language = language
        self.engine = engine
        self.whisper_model = None
        
        # load Whisper 
        if self.engine == "whisper":
            try:
                # First try the faster-whisper implementation
                from faster_whisper import WhisperModel
                print("Loading Whisper model (faster-whisper)...")
                self.whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            except ImportError:
                try:
                    # Fall back to original whisper
                    import whisper
                    print("Loading Whisper model (openai-whisper)...")
                    self.whisper_model = whisper.load_model("base")
                except (ImportError, TypeError):
                    print("Could not load Whisper. Falling back to Google Speech Recognition.")
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
                print(f"Whisper error: {e}")
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
        """
        Nhận dạng giọng nói từ dữ liệu âm thanh
        
        Args:
            audio_data: Dữ liệu âm thanh bytes từ recorder
            
        Returns:
            str: Văn bản đã nhận dạng hoặc thông báo lỗi
        """
        try:
            # Sử dụng Google Speech Recognition
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            
            # Chuyển đổi bytes thành AudioData
            audio = sr.AudioData(audio_data, sample_rate=16000, sample_width=2)
            
            # Sử dụng engine phù hợp
            if self.engine == "google":
                text = recognizer.recognize_google(audio, language=self.language)
            elif self.engine == "whisper":
                text = recognizer.recognize_whisper(audio, language=self.language)
            else:
                return "Could not understand audio: unsupported engine"
                
            return text
        except Exception as e:
            return f"Could not understand audio: {str(e)}"