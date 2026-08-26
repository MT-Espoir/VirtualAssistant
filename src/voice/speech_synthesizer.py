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


# Dọn markdown trước khi đọc: TTS phát âm cả '*' hoặc khựng lại ở chúng, nghe rất kỳ.
# CỐ Ý GIỮ danh sách ĐÁNH SỐ ("1. ...") vì người dùng cần nghe số để chọn kết quả tìm web.
_MD_RULES = [
    (re.compile(r"```.*?```", re.S), " "),          # khối code
    (re.compile(r"`([^`]*)`"), r"\1"),              # `code`
    (re.compile(r"!?\[([^\]]*)\]\([^)]*\)"), r"\1"),  # [chữ](link) -> chữ
    (re.compile(r"\*\*\*([^*]+)\*\*\*"), r"\1"),    # ***đậm nghiêng***
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),        # **đậm**
    (re.compile(r"(?<!\w)\*([^*\n]+)\*(?!\w)"), r"\1"),   # *nghiêng*
    (re.compile(r"(?<!\w)__([^_\n]+)__(?!\w)"), r"\1"),   # __đậm__
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),   # # tiêu đề
    (re.compile(r"^\s*[-*+]\s+", re.M), ""),        # gạch đầu dòng (KHÔNG đụng '1.')
    (re.compile(r"^\s*>\s?", re.M), ""),            # trích dẫn
    (re.compile(r"^\s*[-*_]{3,}\s*$", re.M), ""),   # đường kẻ ---
]


def clean_for_speech(text):
    """Bỏ ký hiệu markdown để TTS không đọc/khựng ở chúng. Hàm THUẦN.

    Cũng gộp dòng trống liên tiếp: mỗi lần xuống dòng là một ranh giới đoạn -> thêm một
    lần gọi mạng -> nghe thành khoảng lặng. Ít ranh giới = câu trả lời liền mạch hơn.
    """
    t = text or ""
    for pattern, repl in _MD_RULES:
        t = pattern.sub(repl, t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)               # bỏ dòng trống
    return "\n".join(line.strip() for line in t.splitlines() if line.strip()).strip()


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
                 robot=False, robot_carrier=80, speed=1.0, giong_rieng=None):
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
            giong_rieng: `voice.piper_voice.PiperVoice` đã kiểm dùng được, hoặc None.
                Có thì mọi câu đi qua giọng này; nó hỏng thì tự rơi về gtts.
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
        self._giong_rieng = giong_rieng

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
        # `piper` (giọng riêng) dùng CHUNG đường phát này: nó cũng sinh ra file rồi phát,
        # chỉ khác chỗ sinh. Nhờ vậy barge-in, hiệu ứng robot, chỉnh tốc độ dùng lại được hết.
        elif self.engine_type in ("gtts", "piper"):
            pygame.mixer.init()
            
        # Start the speaking thread
        self._start_speaking_thread()
    
    @property
    def _phat_qua_file(self):
        """Engine này có sinh ra FILE rồi phát không? (gtts và giọng riêng đều vậy.)

        Dùng thuộc tính thay vì so `engine_type == "gtts"` ở 6 chỗ: thêm một engine sinh
        file nữa thì chỉ sửa đúng đây. Trước khi có nó, cắm `piper` vào phải sờ 6 nhánh —
        đúng kiểu rải rác mà đợt refactor feature-module vừa dọn.
        """
        return self.engine_type in ("gtts", "piper")

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
                    elif self._phat_qua_file:
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
        """Phát text (có thể DÀI) qua gTTS: dọn markdown, chia đoạn, phát nối nhau.

        Đoạn KẾ được tổng hợp SONG SONG trong lúc đoạn hiện tại đang phát — nếu chờ tuần
        tự thì giữa hai đoạn có một vòng gọi mạng, nghe thành khoảng lặng dài giữa câu.
        Mỗi đoạn tự retry 1 lần; một đoạn hỏng KHÔNG chặn các đoạn còn lại. stop() giữa
        chừng (barge-in) huỷ cả phần còn lại nhờ đối chiếu token thế hệ phát.
        """
        gen = self._speak_gen
        chunks = split_text_for_tts(clean_for_speech(text))
        if not chunks:
            return

        path = self._gtts_synth(chunks[0], gen)
        for i in range(len(chunks)):
            if self._speak_gen != gen:            # đã bị stop() -> bỏ phần còn lại
                self._discard(path)
                return

            ahead = {}
            worker = None
            if i + 1 < len(chunks):               # dựng sẵn đoạn kế trong lúc phát đoạn này
                nxt = chunks[i + 1]
                worker = threading.Thread(
                    target=lambda: ahead.update(path=self._gtts_synth(nxt, gen)),
                    daemon=True)
                worker.start()

            if path:
                self._play_mp3(path, gen)
            if worker is not None:
                worker.join()
                path = ahead.get("path")

    def _giong_rieng_synth(self, text):
        """Tổng hợp bằng GIỌNG RIÊNG đã fine-tune. Trả đường dẫn wav, None nếu không dùng được.

        Trả None là đường lui hợp lệ: người gọi tự chuyển sang gtts. Giọng riêng hỏng chỉ
        nên làm trợ lý đổi giọng, không được làm nó câm.
        """
        if self._giong_rieng is None:
            return None
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            path = f.name
        if self._giong_rieng.synth_wav(text, path):
            return path
        self._discard(path)
        self._giong_rieng = None          # hỏng một lần thì thôi, khỏi thử lại mỗi câu
        return None

    def _gtts_synth(self, text, gen):
        """Tổng hợp MỘT đoạn thành file mp3 tạm. Trả đường dẫn, hoặc None nếu lỗi cả 2 lần."""
        rieng = self._giong_rieng_synth(text)
        if rieng is not None:
            return rieng

        for attempt in (1, 2):
            if self._speak_gen != gen:            # đã bị cắt lời -> khỏi tốn thêm request
                return None
            temp_filename = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
                    temp_filename = temp_file.name
                gTTS(text=text, lang=self.language, slow=False).save(temp_filename)
                return temp_filename
            except Exception as e:
                logger.warning("gTTS lỗi một đoạn (thử %d/2): %s", attempt, e)
                self._discard(temp_filename)
                time.sleep(0.4)
        logger.error("Lỗi gTTS (kiểm tra mạng) — bỏ qua một đoạn.")
        return None

    def _play_mp3(self, path, gen):
        """Phát một file mp3 rồi xoá. Dừng ngay giữa chừng nếu bị cắt lời."""
        try:
            needs_processing = self.robot or self.speed != 1.0
            if not (needs_processing and self._play_processed(path)):
                pygame.mixer.music.load(path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    if self._speak_gen != gen:            # barge-in giữa lúc phát
                        pygame.mixer.music.stop()
                        break
                    time.sleep(0.1)
        except Exception as e:
            logger.warning("Không phát được một đoạn: %s", e)
        finally:
            self._discard(path)

    @staticmethod
    def _discard(path):
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
    
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
        elif self._phat_qua_file:
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
        elif self._phat_qua_file:
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
        
        elif self._phat_qua_file and language:
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
        elif self._phat_qua_file:
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