import pyaudio
import os
import numpy as np
import time
from io import BytesIO

class Recorder:
    def __init__(self, channels=1, rate=44100, chunk=1024, format=pyaudio.paInt16, 
                 speech_threshold_ratio=1.2, calibration_duration=1.0,
                 recalibration_interval=60):  # Thêm tham số recalibration_interval - giây
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
        """
        self.channels = channels
        self.rate = rate
        self.chunk = chunk
        self.format = format
        self.frames = []
        self.stream = None
        self.audio = pyaudio.PyAudio()
        
        # Silence detection parameters
        self.speech_threshold_ratio = speech_threshold_ratio  # Multiplier for noise threshold
        self.calibration_duration = calibration_duration  # Time to calibrate in seconds
        self.noise_level = 200  # Default noise level if calibration fails
        self.silence_threshold = 1000  # Default threshold
        
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
            print("Calibrating noise levels... (please be silent)")
            
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
            
            print(f"Noise calibration complete. Ambient noise: {self.noise_level:.0f}, Threshold: {self.silence_threshold}")
            
        except Exception as e:
            # Use default values if calibration fails
            self.noise_level = 500
            self.silence_threshold = 1000
            print(f"Noise calibration failed: {e}. Using default threshold: {self.silence_threshold}")

    def start_recording(self):
        # Chỉ hiệu chỉnh nếu đã đến thời điểm cần hiệu chỉnh lại
        current_time = time.time()
        if current_time - self.last_calibration_time >= self.recalibration_interval:
            self.calibrate_noise()
            
        self.frames = []
        try:
            self.stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk
            )
            print("Recording started successfully")
        except Exception as e:
            print(f"Error opening audio stream: {e}")
            self.stream = None
    
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
        except Exception as e:
            print(f"Error processing audio in is_silent: {e}")
            return True
            
    def get_audio_data(self):
        """Return the recorded audio as bytes data for recognition"""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
            
        if not self.frames:
            print("No audio frames captured")
            return None
            
        # Return the combined audio frames data
        return b''.join(self.frames)
            
    def reset(self):
        """Reset recorder and prepare for a new recording"""
        try:
            # Dừng và đóng stream một cách an toàn
            if hasattr(self, 'stream') and self.stream:
                try:
                    # Chỉ kiểm tra is_active() nếu stream còn tồn tại
                    if self.stream._stream and self.stream.is_active():
                        self.stream.stop_stream()
                except (OSError, AttributeError):
                    # Bỏ qua lỗi nếu stream đã bị đóng
                    pass
                
                # Đóng stream nếu chưa đóng
                try:
                    self.stream.close()
                except (OSError, AttributeError):
                    pass
                    
                self.stream = None
                
            # Reset các thuộc tính khác
            self.frames = []
            self.is_recording = False
            
        except Exception as e:
            print(f"Error in reset: {e}")
            
    def close(self):
        """Close resources"""
        if self.stream:
            self.stream.close()
        self.audio.terminate()
            
    def __del__(self):
        if hasattr(self, 'stream') and self.stream:
            self.stream.close()
        if hasattr(self, 'audio'):
            self.audio.terminate()