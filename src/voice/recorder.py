import pyaudio
import numpy as np
import time
import math
from collections import deque
from dataclasses import asdict, dataclass

from utils.logger import get_logger

logger = get_logger(__name__)


def chunks_for_seconds(seconds, rate, chunk):
    """Đổi GIÂY -> số chunk audio. Hàm thuần.

    Mọi ngưỡng thời gian phải khai báo bằng giây rồi quy đổi ở đây: một "số chunk" cố định
    mang ý nghĩa KHÁC NHAU tuỳ rate (1024 chunk @44.1kHz = 23ms, @16kHz = 64ms) nên đặt
    thẳng số chunk rất dễ sai âm thầm khi đổi rate.
    """
    return max(1, int(float(seconds) * rate / chunk))


def pcm_rms(data):
    """RMS an toàn cho PCM int16; cast trước khi bình phương để không overflow."""
    samples = np.frombuffer(data, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    float_samples = samples.astype(np.float32)
    return float(np.sqrt(np.mean(np.square(float_samples))))


@dataclass(frozen=True)
class CaptureInfo:
    speech_detected: bool = False
    wait_seconds: float = 0.0
    speech_seconds: float = 0.0
    pre_roll_seconds: float = 0.0
    trailing_silence_seconds: float = 0.0
    hit_start_timeout: bool = False
    hit_max_utterance: bool = False
    ended_by_silence: bool = False
    threshold: int = 0
    end_threshold: int = 0
    peak_rms: int = 0
    tail_quiet_fraction: float = 0.0
    tail_rms_p20: int = 0
    tail_rms_p80: int = 0

    def to_dict(self):
        return asdict(self)


class Recorder:
    def __init__(self, channels=1, rate=44100, chunk=1024, format=pyaudio.paInt16,
                 speech_threshold_ratio=1.2, calibration_duration=1.0,
                 recalibration_interval=60,  # Thêm tham số recalibration_interval - giây
                 silence_duration=1.5, max_utterance_s=15.0,
                 speech_start_timeout_s=15.0, pre_roll_s=0.35):
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
        # Mốc (monotonic) lúc BẮT ĐẦU nghe thấy tiếng của lượt gần nhất; None = lượt đó
        # không có tiếng nào. Dùng monotonic chứ không phải time.time() vì đây là để đo
        # KHOẢNG CÁCH giữa hai sự kiện, mà đồng hồ hệ thống có thể bị chỉnh giữa chừng.
        self.speech_started_at = None
        self.audio = pyaudio.PyAudio()
        
        # Silence detection parameters
        self.speech_threshold_ratio = speech_threshold_ratio  # Multiplier for noise threshold
        self.calibration_duration = calibration_duration  # Time to calibrate in seconds
        self.noise_level = 200  # Default noise level if calibration fails
        self.silence_threshold = 1000  # Default threshold
        self.silence_duration = silence_duration      # giây im lặng = hết câu
        self.max_utterance_s = max_utterance_s        # giây tối đa một lượt nói
        # Chờ người dùng bắt đầu và giới hạn ĐỘ DÀI câu là hai đồng hồ độc lập. Trước
        # đây cùng dùng max_utterance_s nên chờ 14s chỉ còn 1s để nói.
        self.speech_start_timeout_s = max(0.1, float(speech_start_timeout_s))
        # Giữ một đoạn ngắn ngay trước chunk vượt ngưỡng để không mất phụ âm đầu nhẹ.
        self.pre_roll_s = max(0.0, float(pre_roll_s))
        self.last_capture = CaptureInfo(threshold=self.silence_threshold)
        
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
                        level = pcm_rms(frame)
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

    def listen_once(self, max_chunks=None, silence_limit=None, max_seconds=None,
                    start_timeout_s=None):
        """Ghi một lượt nói: chờ có tiếng, dừng khi im lặng đủ lâu.

        Mặc định lấy theo `silence_duration`/`max_utterance_s` (giây) đã cấu hình. Nơi gọi
        có thể ép bằng `max_seconds` (giây, nên dùng) hoặc `max_chunks` (số chunk, thô).

        Trả về audio bytes nếu phát hiện giọng nói, ngược lại None.
        (stream.read() đã tự chặn theo nhịp chunk nên không cần sleep.)
        """
        if max_chunks is None:
            secs = max_seconds if max_seconds is not None else self.max_utterance_s
            max_chunks = chunks_for_seconds(secs, self.rate, self.chunk)
        max_chunks = max(1, int(max_chunks))
        wait_seconds = (self.speech_start_timeout_s if start_timeout_s is None
                        else max(0.1, float(start_timeout_s)))
        wait_limit = chunks_for_seconds(wait_seconds, self.rate, self.chunk)
        if silence_limit is None:
            silence_limit = chunks_for_seconds(self.silence_duration, self.rate, self.chunk)
        silence_limit = max(1, int(silence_limit))
        pre_roll_limit = (chunks_for_seconds(self.pre_roll_s, self.rate, self.chunk)
                          if self.pre_roll_s > 0 else 0)

        self.speech_started_at = None      # mốc của lượt TRƯỚC không được sống sót
        self.start_recording()
        if not self.stream:
            self.last_capture = CaptureInfo(threshold=self.silence_threshold)
            return None

        speech_detected = False
        silence_counter = 0
        wait_chunks = 0
        speech_chunks = 0
        peak_rms = 0.0
        end_threshold = float(self.silence_threshold)
        tail_rms = deque(maxlen=silence_limit)
        quiet_needed = math.ceil(silence_limit * 0.85)
        trailing_quiet_needed = min(silence_limit, chunks_for_seconds(0.2, self.rate, self.chunk))
        tail_p20 = tail_p80 = 0.0
        # +1 là chunk onset hiện tại; ``pre_roll_limit`` chỉ đếm phần đứng TRƯỚC nó.
        pre_roll = deque(maxlen=pre_roll_limit + 1)
        ended_by_silence = False
        hit_max_utterance = False
        stream_failed = False
        while True:
            if not speech_detected and wait_chunks >= wait_limit:
                break
            if speech_detected and speech_chunks >= max_chunks:
                hit_max_utterance = True
                break
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
                stream_failed = True
                break

            try:
                rms = pcm_rms(data)
            except (ValueError, TypeError):
                rms = 0.0
            silent = self.is_silent(data, rms=rms)
            if not speech_detected:
                wait_chunks += 1
                pre_roll.append(data)
            else:
                self.frames.append(data)
                speech_chunks += 1

            if not speech_detected:
                if not silent:
                    logger.debug("Speech detected")
                    self.speech_started_at = time.monotonic()
                    self.frames = list(pre_roll)
                    speech_chunks = 1
                    speech_detected = True
                    peak_rms = rms
            else:
                peak_rms = max(peak_rms, rms)
                # Speech and the quieter fan/room sound often both exceed the
                # onset threshold. Use bounded end-of-speech hysteresis only
                # after a clearly louder voice has been heard; never lower the
                # onset threshold or infer words from a cut transcript.
                end_threshold = float(self.silence_threshold)
                if peak_rms >= max(1000, 2 * self.silence_threshold):
                    end_threshold = max(end_threshold, min(
                        1.8 * self.silence_threshold, 0.45 * peak_rms))
                tail_rms.append(rms)
                if len(tail_rms) == silence_limit:
                    ordered = sorted(tail_rms)
                    tail_p20 = ordered[int(0.2 * (silence_limit - 1))]
                    tail_p80 = ordered[int(0.8 * (silence_limit - 1))]
                    # A fan creates a fairly steady noise plateau. Estimate its
                    # upper energy band from the latest 1.5 s only when that
                    # band is both much quieter than the spoken peak and stable.
                    if (peak_rms >= max(1000, 2 * self.silence_threshold) and
                            tail_p80 <= 0.45 * peak_rms and
                            tail_p80 <= 2.5 * max(tail_p20, 1)):
                        end_threshold = max(end_threshold, min(
                            5 * self.silence_threshold, 0.55 * peak_rms,
                            1.30 * tail_p80))
                quiet_count = sum(level < end_threshold for level in tail_rms)
                silence_counter = 0
                for level in reversed(tail_rms):
                    if level >= end_threshold:
                        break
                    silence_counter += 1
                if (len(tail_rms) == silence_limit and
                        quiet_count >= quiet_needed and
                        silence_counter >= trailing_quiet_needed):
                    logger.debug("End of speech")
                    ended_by_silence = True
                    break

        chunk_seconds = self.chunk / self.rate
        self.last_capture = CaptureInfo(
            speech_detected=speech_detected,
            wait_seconds=round(
                max(0, wait_chunks - (1 if speech_detected else 0)) * chunk_seconds, 3),
            speech_seconds=round(speech_chunks * chunk_seconds, 3),
            pre_roll_seconds=round(
                max(0, len(self.frames) - speech_chunks) * chunk_seconds, 3),
            trailing_silence_seconds=round(silence_counter * chunk_seconds, 3),
            hit_start_timeout=not speech_detected and not stream_failed,
            hit_max_utterance=hit_max_utterance,
            ended_by_silence=ended_by_silence,
            threshold=int(self.silence_threshold),
            end_threshold=round(end_threshold),
            peak_rms=round(peak_rms),
            tail_quiet_fraction=(round(
                sum(level < end_threshold for level in tail_rms) / len(tail_rms), 3)
                                 if tail_rms else 0.0),
            tail_rms_p20=round(tail_p20),
            tail_rms_p80=round(tail_p80),
        )
        return self.get_audio_data() if speech_detected else None

    def is_silent(self, data, rms=None):
        """Determine if an audio chunk is silence based on volume level"""
        try:
            # Chuyển đổi dữ liệu âm thanh thành mảng numpy
            rms = pcm_rms(data) if rms is None else rms
                  
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

    def discard_buffered(self, max_seconds=0.5):
        """Bỏ phần audio ĐÃ nằm trong buffer mà không mở một khoảng mù mới.

        Dùng sau TTS: bản cũ đọc chặn thêm 0.4s nên người dùng đáp nhanh bị mất chữ đầu.
        Hàm này chỉ tiêu thụ số frame PortAudio báo đang có ngay lúc gọi rồi trả về.
        """
        self.start_recording()
        stream = self.stream
        available_fn = getattr(stream, "get_read_available", None) if stream else None
        if not callable(available_fn):
            self.frames = []
            return 0
        budget = max(0, int(float(max_seconds) * self.rate))
        discarded = 0
        try:
            available = max(0, int(available_fn()))
            while available > 0 and discarded < budget:
                count = min(self.chunk, available, budget - discarded)
                if count <= 0:
                    break
                stream.read(count, exception_on_overflow=False)
                discarded += count
                available = max(0, int(available_fn()))
        except (IOError, OSError, ValueError):
            logger.debug("Không dọn được audio buffer sau TTS", exc_info=True)
        self.frames = []
        return discarded

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
            try:
                self.stream.close()
            except (OSError, AttributeError):
                pass
        if hasattr(self, 'audio'):
            try:
                self.audio.terminate()
            except (OSError, AttributeError):
                pass
