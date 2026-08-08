import pyaudio
import numpy as np
import time

from utils.logger import get_logger

logger = get_logger(__name__)


def chunks_for_seconds(seconds, rate, chunk):
    """Đổi GIÂY -> số chunk audio. Hàm thuần.

    Mọi ngưỡng thời gian phải khai báo bằng giây rồi quy đổi ở đây: một "số chunk" cố định
    mang ý nghĩa KHÁC NHAU tuỳ rate (1024 chunk @44.1kHz = 23ms, @16kHz = 64ms) nên đặt
    thẳng số chunk rất dễ sai âm thầm khi đổi rate.
    """
    return max(1, int(float(seconds) * rate / chunk))


class Recorder:
    def __init__(self, channels=1, rate=44100, chunk=1024, format=pyaudio.paInt16,
                 speech_threshold_ratio=1.2, calibration_duration=1.0,
                 recalibration_interval=60,  # Thêm tham số recalibration_interval - giây
                 silence_duration=1.5, max_utterance_s=15.0):
        """
        Initialize recorder with audio settings
        
        Args:
            channels: Number of audio channels (1 for mono, 2 for stereo)
            rate: Sampling rate in Hz
            chunk: Size of audio chunks to read
            format: Audio format (from pyaudio)
            speech_threshold_ratio: Multiplier for noise level to determine speech
            calibration_duration: Duration in seconds to calibrate noise levels
            recalibration_interval: How often to recalibrate noise (in seconds)
            silence_duration: Im lặng bao nhiêu GIÂY thì coi là người dùng đã nói xong.
                Quá ngắn -> cắt ngang lúc người ta ngắt hơi/nghĩ giữa câu; quá dài ->
                trợ lý đáp chậm. 1.5s đủ cho khoảng ngắt tự nhiên trong tiếng Việt.
            max_utterance_s: Độ dài TỐI ĐA một lượt nói (giây) — chặn treo nếu VAD kẹt.
        """
        self.channels = channels
        self.rate = rate
        self.chunk = chunk
        self.format = format
        self.frames = []
        self.stream = None
        self.is_recording = False
        self.audio = pyaudio.PyAudio()
        
        # Silence detection parameters
        self.speech_threshold_ratio = speech_threshold_ratio  # Multiplier for noise threshold
        self.calibration_duration = calibration_duration  # Time to calibrate in seconds
        self.noise_level = 200  # Default noise level if calibration fails
        self.silence_threshold = 1000  # Default threshold
        self.silence_duration = silence_duration      # giây im lặng = hết câu
        self.max_utterance_s = max_utterance_s        # giây tối đa một lượt nói
        
        # Recalibration tracking
        self.last_calibration_time = 0
        self.recalibration_interval = recalibration_interval  # seconds
        
        # Initial calibration
        self.calibrate_noise()

    def calibrate_noise(self, force=False):
        """
        Measure ambient noise levels to set silence threshold
        
        Args:
            force: If True, calibrate regardless of time since last calibration
        """
        current_time = time.time()
        
        # Kiểm tra xem đã đến thời điểm cần hiệu chỉnh lại chưa
        if not force and (current_time - self.last_calibration_time < self.recalibration_interval):
            # Chưa đến lúc hiệu chỉnh, sử dụng giá trị cũ
            return
            
        try:
            logger.info("Calibrating noise levels... (please be silent)")

            # Start a stream temporarily to measure noise
            temp_stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )
            
            # Collect audio data for calibration duration
            noise_frames = []
            for _ in range(0, int(self.rate / self.chunk * self.calibration_duration)):
                data = temp_stream.read(self.chunk)
                noise_frames.append(data)
            
            # Close temporary stream
            temp_stream.stop_stream()
            temp_stream.close()
            
            # Calculate average noise level
            if noise_frames:
                levels = []
                for frame in noise_frames:
                    try:
                        audio_data = np.frombuffer(frame, dtype=np.int16)
                        level = np.sqrt(np.mean(np.square(audio_data)))
                        levels.append(level)
                    except (ValueError, TypeError):
                        pass
                
                if levels:
                    self.noise_level = sum(levels) / len(levels)
                else:
                    self.noise_level = 500  # Default if processing failed
            else:
                self.noise_level = 500  # Default if no frames recorded
            
            # Ensure noise level is not zero to prevent calculation issues
            if self.noise_level < 30:
                self.noise_level = 500
                
            # Set silence threshold based on noise level
            self.silence_threshold = max(500, int(self.noise_level * self.speech_threshold_ratio))
            
            # Cập nhật thời gian hiệu chỉnh cuối cùng
            self.last_calibration_time = current_time
            
            logger.info("Noise calibration complete. Ambient: %.0f, threshold: %d",
                        self.noise_level, self.silence_threshold)

        except Exception as e:
            # Use default values if calibration fails
            self.noise_level = 500
            self.silence_threshold = 1000
            logger.warning("Noise calibration failed: %s. Dùng ngưỡng mặc định %d",
                           e, self.silence_threshold)

    def start_recording(self):
        """Đảm bảo stream đang mở, sẵn sàng ghi. Stream được GIỮ MỞ LIÊN TỤC giữa
        các lượt nghe (không đóng/mở lại) — tránh độ trễ khởi động phần cứng mic
        làm mất vài trăm ms đầu câu nói (bug: mất từ đầu như "mở", wake word...).
        Chỉ tái hiệu chỉnh khi stream CHƯA mở (mở song song 2 stream không an toàn
        trên nhiều driver); khi đang nghe liên tục, is_silent() đã tự thích nghi
        noise_level theo các đoạn im lặng thật.
        """
        self.frames = []
        if self.stream is not None:
            self.is_recording = True
            return

        current_time = time.time()
        if current_time - self.last_calibration_time >= self.recalibration_interval:
            self.calibrate_noise()

        try:
            self.stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )
            self.is_recording = True
            logger.debug("Recording started")
        except OSError as e:
            logger.error("Error opening audio stream: %s", e)
            self.stream = None
            self.is_recording = False

    def listen_once(self, max_chunks=None, silence_limit=None, max_seconds=None):
        """Ghi một lượt nói: chờ có tiếng, dừng khi im lặng đủ lâu.

        Mặc định lấy theo `silence_duration`/`max_utterance_s` (giây) đã cấu hình. Nơi gọi
        có thể ép bằng `max_seconds` (giây, nên dùng) hoặc `max_chunks` (số chunk, thô).

        Trả về audio bytes nếu phát hiện giọng nói, ngược lại None.
        (stream.read() đã tự chặn theo nhịp chunk nên không cần sleep.)
        """
        if max_chunks is None:
            secs = max_seconds if max_seconds is not None else self.max_utterance_s
            max_chunks = chunks_for_seconds(secs, self.rate, self.chunk)
        if silence_limit is None:
            silence_limit = chunks_for_seconds(self.silence_duration, self.rate, self.chunk)

        self.start_recording()
        if not self.stream:
            return None

        speech_detected = False
        silence_counter = 0
        for _ in range(max_chunks):
            try:
                data = self.stream.read(self.chunk, exception_on_overflow=False)
            except (IOError, OSError) as e:
                logger.error("Error reading audio: %s", e)
                # Stream có thể đã hỏng — bỏ đi để lần sau start_recording() mở lại.
                try:
                    self.stream.close()
                except (OSError, AttributeError):
                    pass
                self.stream = None
                break

            self.frames.append(data)

            if not self.is_silent(data):
                if not speech_detected:
                    logger.debug("Speech detected")
                speech_detected = True
                silence_counter = 0
            elif speech_detected:
                silence_counter += 1
                if silence_counter > silence_limit:
                    logger.debug("End of speech")
                    break

        return self.get_audio_data() if speech_detected else None

    def is_silent(self, data):
        """Determine if an audio chunk is silence based on volume level"""
        try:
            # Chuyển đổi dữ liệu âm thanh thành mảng numpy
            audio_data = np.frombuffer(data, dtype=np.int16)
            
            # Xử lý trường hợp mảng trống hoặc có giá trị không hợp lệ
            if len(audio_data) == 0:
                return True
                
            # Tính toán root mean square (RMS) của âm thanh với xử lý an toàn
            squared = np.square(audio_data.astype(np.float32))  # Chuyển sang float32 trước khi tính bình phương
            mean_squared = np.mean(squared) if squared.size > 0 else 0
            
            # Tránh lỗi sqrt với giá trị âm
            if mean_squared < 0:
                mean_squared = 0
                
            rms = np.sqrt(mean_squared)
                  
            # Update noise level if this is quiet
            if rms < self.silence_threshold * 0.8:
                self.noise_level = 0.95 * self.noise_level + 0.05 * rms
                new_threshold = max(500, int(self.noise_level * self.speech_threshold_ratio))
                if abs(new_threshold - self.silence_threshold) > 50:
                    self.silence_threshold = new_threshold
                    
            return rms < self.silence_threshold
        except (ValueError, TypeError) as e:
            logger.debug("Lỗi xử lý âm thanh trong is_silent: %s", e)
            return True
            
    def get_audio_data(self):
        """Return the recorded audio as bytes data for recognition.

        KHÔNG đóng stream — stream được giữ mở liên tục xuyên suốt các lượt nghe
        (xem start_recording()), chỉ đóng thật ở close().
        """
        if not self.frames:
            logger.debug("No audio frames captured")
            return None
            
        # Return the combined audio frames data
        return b''.join(self.frames)
            
    def reset(self):
        """Xoá buffer frame, chuẩn bị cho lượt nghe kế tiếp.

        KHÔNG đóng stream (xem start_recording()) — chỉ close() lúc tắt app mới
        đóng thật. Giữ mic mở liên tục để tránh độ trễ mở lại phần cứng.
        """
        self.frames = []
        self.is_recording = False

    def drain(self, duration_s):
        """Mở stream sớm (nếu chưa mở) rồi đọc-bỏ chunk trong `duration_s` giây.

        Dùng làm "guard" sau khi TTS nói xong: vừa lọc bỏ đuôi vọng âm còn sót lại
        trong stream, vừa làm nóng phần cứng mic trước khi lượt nghe thật bắt đầu
        (thay cho time.sleep mù — nguyên nhân từng làm mất từ đầu câu kế tiếp).
        """
        self.start_recording()
        if not self.stream:
            time.sleep(duration_s)
            return
        end_time = time.time() + duration_s
        while time.time() < end_time:
            try:
                self.stream.read(self.chunk, exception_on_overflow=False)
            except (IOError, OSError):
                try:
                    self.stream.close()
                except (OSError, AttributeError):
                    pass
                self.stream = None
                break
        self.frames = []

    def close(self):
        """Close resources"""
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except (OSError, AttributeError):
                pass
            self.stream = None
        self.audio.terminate()
            
    def __del__(self):
        if hasattr(self, 'stream') and self.stream:
            self.stream.close()
        if hasattr(self, 'audio'):
            self.audio.terminate()