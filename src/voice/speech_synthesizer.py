import pyttsx3
import threading
import os
import re
from gtts import gTTS
import tempfile
import pygame
import time
import queue

from utils.logger import get_logger

logger = get_logger(__name__)


def _hard_split(s, max_len):
    """Cắt một câu quá dài thành các mẩu <= max_len theo ranh giới TỪ. Thuần."""
    out, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > max_len:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        out.append(cur)
    return out


def split_text_for_tts(text, max_len=200):
    """Chia text dài thành các đoạn <= max_len ở ranh giới CÂU (hoặc từ nếu câu quá dài).

    gTTS hay lỗi '200 (OK) Probable cause: Unknown' khi text quá dài (nhiều request nối
    tiếp bị chặn); chia nhỏ + phát dần vừa tránh lỗi, vừa cho phép phát được phần đầu dù
    một đoạn sau có hỏng, vừa giúp barge-in phản hồi nhanh. Hàm THUẦN, test được.
    """
    text = (text or "").strip()
    if not text:
        return []
    pieces = re.split(r"(?<=[.!?…])\s+|\n+", text)
    chunks, cur = [], ""
    for p in pieces:
        p = p.strip()
        if not p:
            continue
        if len(p) > max_len:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.extend(_hard_split(p, max_len))
            continue
        if cur and len(cur) + 1 + len(p) > max_len:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        chunks.append(cur)
    return chunks

class SpeechSynthesizer:
    """
    Speech synthesizer class for converting text to speech
    Supports both offline (pyttsx3) and online (gTTS) synthesis
    """
    
    def __init__(self, engine="pyttsx3", language="vi", rate=150, volume=1.0,
                 robot=False, robot_carrier=80, speed=1.0):
        """
        Initialize the speech synthesizer

        Args:
            engine (str): The TTS engine to use ("pyttsx3" or "gtts")
            language (str): The language code (e.g., "vi" for Vietnamese, "en" for English)
            rate (int): Speech rate for pyttsx3 (higher = faster)
            volume (float): Speech volume (0.0 to 1.0)
            robot (bool): Áp hiệu ứng giọng robot (ring modulation) cho gTTS
            robot_carrier (int): Tần số sóng mang (Hz) cho hiệu ứng robot
            speed (float): Hệ số tốc độ nói (>1 nhanh hơn). Với pyttsx3 chỉnh 'rate'
                (giữ cao độ); với gTTS nội suy lại mẫu (nhanh hơn = cao giọng hơn).
        """
        self.engine_type = engine
        self.language = language
        self.rate = rate
        self.volume = volume
        self.robot = robot
        self.robot_carrier = robot_carrier
        self.speed = speed if speed and speed > 0 else 1.0
        self.voice_queue = queue.Queue()
        self.is_speaking = False
        self.stop_requested = False
        # Token thế hệ phát: stop() tăng lên -> đoạn (chunk) đang phát tự huỷ, không phát
        # nốt các đoạn còn lại (giữ barge-in hoạt động khi câu dài bị chia nhiều đoạn).
        self._speak_gen = 0

        # Initialize the appropriate TTS engine
        if self.engine_type == "pyttsx3":
            self.engine = pyttsx3.init()
            # pyttsx3 chỉnh tốc độ đúng nghĩa (không đổi cao độ) qua 'rate'.
            self.engine.setProperty('rate', int(self.rate * self.speed))
            self.engine.setProperty('volume', self.volume)
            
            # Try to set a voice based on the language
            voices = self.engine.getProperty('voices')
            selected_voice = None
            
            for voice in voices:
                if self.language in voice.id.lower():
                    selected_voice = voice.id
                    break
            
            # If we found a matching voice, set it
            if selected_voice:
                self.engine.setProperty('voice', selected_voice)
                
        # Initialize pygame for gtts playback
        elif self.engine_type == "gtts":
            pygame.mixer.init()
            
        # Start the speaking thread
        self._start_speaking_thread()
    
    def _start_speaking_thread(self):
        """Start a background thread to handle speech synthesis"""
        self.speak_thread = threading.Thread(target=self._process_speech_queue, daemon=True)
        self.speak_thread.start()
    
    def _process_speech_queue(self):
        """Process items in the speech queue"""
        while True:
            if not self.stop_requested:
                try:
                    # Get text from queue with a timeout to allow checking stop_requested
                    text = self.voice_queue.get(timeout=0.5)
                    self.is_speaking = True
                    
                    if self.engine_type == "pyttsx3":
                        self.engine.say(text)
                        self.engine.runAndWait()
                    elif self.engine_type == "gtts":
                        self._speak_with_gtts(text)
                    
                    self.is_speaking = False
                    self.voice_queue.task_done()
                except queue.Empty:
                    # Queue is empty, just continue the loop
                    pass
                except Exception as e:
                    logger.error("Lỗi tổng hợp giọng nói: %s", e)
                    self.is_speaking = False
            else:
                time.sleep(0.1)  # Sleep to reduce CPU usage when stopped
                
    def _play_processed(self, mp3_path):
        """Phát file có xử lý mẫu: đổi tốc độ (speed) và/hoặc giọng robot.

        Trả True nếu phát thành công; False để nơi gọi phát giọng thường (fallback).
        """
        try:
            import numpy as np
            import pygame.sndarray
            from voice.robot_effect import ring_modulate, resample_speed

            sound = pygame.mixer.Sound(mp3_path)
            samples = pygame.sndarray.array(sound)          # int16
            init = pygame.mixer.get_init()
            rate = init[0] if init else 22050

            if self.speed != 1.0:
                samples = resample_speed(samples, self.speed)
            if self.robot:
                samples = ring_modulate(samples, rate, self.robot_carrier)

            out = pygame.sndarray.make_sound(np.ascontiguousarray(samples))
            out.play()
            while pygame.mixer.get_busy():
                time.sleep(0.1)
            return True
        except Exception as e:
            logger.warning("Không xử lý được âm thanh (%s) — phát giọng thường.", e)
            return False

    def _speak_with_gtts(self, text):
        """Phát text (có thể DÀI) qua gTTS: chia đoạn ở ranh giới câu rồi phát tuần tự.
        Mỗi đoạn tự retry 1 lần; một đoạn hỏng KHÔNG chặn các đoạn còn lại. Dừng ngay nếu
        stop() được gọi giữa chừng (barge-in) nhờ đối chiếu token thế hệ phát."""
        gen = self._speak_gen
        for chunk in split_text_for_tts(text):
            if self._speak_gen != gen:        # đã bị stop() -> huỷ phần còn lại
                break
            self._gtts_synth_play(chunk, gen)

    def _gtts_synth_play(self, text, gen):
        """Tổng hợp + phát MỘT đoạn ngắn. Trả True nếu phát xong, False nếu lỗi cả 2 lần."""
        for attempt in (1, 2):
            temp_filename = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
                    temp_filename = temp_file.name

                tts = gTTS(text=text, lang=self.language, slow=False)
                tts.save(temp_filename)

                needs_processing = self.robot or self.speed != 1.0
                if not (needs_processing and self._play_processed(temp_filename)):
                    pygame.mixer.music.load(temp_filename)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        if self._speak_gen != gen:      # barge-in giữa lúc phát đoạn này
                            pygame.mixer.music.stop()
                            break
                        time.sleep(0.1)
                return True
            except Exception as e:
                logger.warning("gTTS lỗi một đoạn (thử %d/2): %s", attempt, e)
                if self._speak_gen != gen:
                    return False
                time.sleep(0.4)
            finally:
                if temp_filename:
                    try:
                        os.unlink(temp_filename)
                    except OSError:
                        pass
        logger.error("Lỗi gTTS (kiểm tra mạng) — bỏ qua một đoạn.")
        return False
    
    def speak(self, text):
        """
        Args:
            text (str): Text to be spoken
        """
        if text and not self.stop_requested:
            self.voice_queue.put(text)
            return True
        return False
    
    def speak_sync(self, text):
        """
        Speak the given text synchronously (blocking until speech finishes)
        
        Args:
            text (str): Text to be spoken
        """
        if not text or self.stop_requested:
            return False
            
        if self.engine_type == "pyttsx3":
            self.is_speaking = True
            self.engine.say(text)
            self.engine.runAndWait()
            self.is_speaking = False
            return True
        elif self.engine_type == "gtts":
            self.is_speaking = True
            self._speak_with_gtts(text)
            self.is_speaking = False
            return True
        
        return False
    
    def stop(self):
        """Stop ongoing speech and clear the queue"""
        self.stop_requested = True
        self._speak_gen += 1        # huỷ mọi đoạn đang/sắp phát của lượt nói hiện tại

        # Clear the queue
        while not self.voice_queue.empty():
            try:
                self.voice_queue.get_nowait()
                self.voice_queue.task_done()
            except queue.Empty:
                break
        
        if self.engine_type == "pyttsx3":
            try:
                self.engine.stop()
            except Exception:
                pass  # Ignore errors when stopping
        elif self.engine_type == "gtts":
            try:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
            except pygame.error:
                pass  # Ignore errors when stopping
        
        self.is_speaking = False
        self.stop_requested = False
        
    def change_voice(self, language=None, index=None):
        """
        Change the voice of the speech synthesizer
        
        Args:
            language (str): The language code to switch to
            index (int): Voice index to use (alternative to language)
        """
        if self.engine_type == "pyttsx3":
            voices = self.engine.getProperty('voices')
            
            if index is not None and 0 <= index < len(voices):
                self.engine.setProperty('voice', voices[index].id)
                return True
            
            if language:
                for voice in voices:
                    if language in voice.id.lower():
                        self.engine.setProperty('voice', voice.id)
                        self.language = language
                        return True
            
            return False
        
        elif self.engine_type == "gtts" and language:
            self.language = language
            return True
        
        return False
    
    def adjust_rate(self, rate):
        """
        Adjust the speech rate
        
        Args:
            rate (int): New speech rate (pyttsx3 only)
        """
        if self.engine_type == "pyttsx3":
            self.rate = rate
            self.engine.setProperty('rate', rate)
            return True
        return False
    
    def adjust_volume(self, volume):
        """
        Adjust the speech volume
        
        Args:
            volume (float): New volume level (0.0 to 1.0)
        """
        if volume < 0.0 or volume > 1.0:
            return False
            
        self.volume = volume
        
        if self.engine_type == "pyttsx3":
            self.engine.setProperty('volume', volume)
        elif self.engine_type == "gtts":
            try:
                pygame.mixer.music.set_volume(volume)
            except pygame.error:
                pass
                
        return True
        
    def get_available_voices(self):
        """Get list of available voices (pyttsx3 only)"""
        if self.engine_type == "pyttsx3":
            voices = self.engine.getProperty('voices')
            voice_list = []
            
            for idx, voice in enumerate(voices):
                voice_info = {
                    'id': voice.id,
                    'name': voice.name,
                    'index': idx
                }
                voice_list.append(voice_info)
                
            return voice_list
            
        return []