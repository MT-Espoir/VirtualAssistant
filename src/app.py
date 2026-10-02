"""
Điểm vào hợp nhất — khởi chạy toàn bộ hệ thống trong một lần:
agent (LLM tool-calling) + avatar cảm xúc (Tkinter) + TTS (kèm giọng robot
tùy chọn) + lịch nhắc (scheduler). Đầu vào dùng micro nếu có, tự động chuyển
sang gõ phím nếu không có/lỗi (xem INPUT_MODE trong .env.example).

Chạy:  cd src && python app.py
"""

import sys
import re
import threading
import time

from agent.agent import Agent
from agent.actions_facade import AssistantActions
from agent.tools import NeedsConfirmation, ActionRefused
from features.contract import FeatureContext
from features.activity_insights import ActivityInsightsService
from features.camera.service import CameraService
from features.camera.commands import extract_camera_off_command, turn_off_webcam
from features.camera.return_coordinator import WorkstationReturnCoordinator
from features.camera.visual_confirmation import VisualConfirmationArbiter
from features.camera.welcome import CameraReturnWelcome, build_camera_welcome_client
from features.iot.alerts import VoiceAlertPoller
from features.iot.client import IoTClient
from features.iot.fast import describe_ac_result, describe_automation_result
from features.registry import build_registry
from features.places.service import PlacesService
from features.salm import InterventionGate, ProactiveDispatcher, SalmRuntime
from features.salm.app_identity import display_app_name
from features.salm.intervention import Intervention
from features.salm.welcome import (STARTUP_GREETING_TEXT, WelcomeDialogue,
                                   welcome_fallback)
from services.location import LocationStore
from memory.habits import HabitLog
from memory.outcomes import OutcomeLog
from memory.profile import UserProfile
from persistence import LocalDatabase
from features.salm.storage import SalmStorage
from agent.persona import PersonaState, MoodState
from services.tasks import TaskStore
from services.routines import RoutineStore
from services.contacts import ContactStore
from services.proactive import ProactiveMonitor, muc_sang_khi_pin_yeu
from actions.system.system_control import read_brightness
from services.mcp_bridge import MCPClient
from llm.client import build_default_llm_client
from utils.events import AssistantBus
from voice.wake_word import (in_follow_up_window, match_wake_word, parse_wake_words,
                             wake_words_not_in)
from voice.recovery import VoiceUtterance, assess_voice_utterance
from features import fast as feature_fast
from voice.fast_commands import (explicit_ui_target, match_avatar_command,
                                 match_hud_command, match_mode_command,
                                 match_confirmation, match_persona_command,
                                 match_routine_command)
from services.scheduler import ReminderScheduler
from services.control_panel import SystemControls
from utils.control_settings import controls
from voice.fast_commands import match_control_panel_command
from ui.avatar import AvatarWindow
from ui.avatar_face import guess_emotion
from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)
_NO_INPUT = object()
MAX_INPUT_FAILS = 5
# Chỉ là trần số mẫu ĐÃ buffer được phép dọn, không phải thời gian chờ mù.
SPEAK_BUFFER_FLUSH_MAX_S = 5.0
STARTUP_GREETING_VOICE_TIMEOUT_S = 90.0


class _VoiceTurnCoordinator:
    """Nhường mic cho TTS chủ động mà không để hai luồng tự nghe/đè lên nhau."""

    def __init__(self):
        self._turn = threading.Lock()
        self._state_lock = threading.Lock()
        self._proactive_requested = threading.Event()
        self._user_input_at = None
        self._cancelled = set()

    def next_input(self, producer):
        """Chạy một lượt nghe; request TTS đã tới sẽ được ưu tiên ở biên lượt."""
        while True:
            while self._proactive_requested.is_set():
                time.sleep(0.02)
            with self._turn:
                if self._proactive_requested.is_set():
                    continue
                value = producer()
                if value is not None and value is not _NO_INPUT and bool(value):
                    with self._state_lock:
                        self._user_input_at = time.monotonic()
                return value

    def present(self, token, callback):
        """Chờ lượt nghe hiện tại xong; nếu người dùng vừa nói thì nhường và bỏ cue."""
        self._proactive_requested.set()
        try:
            with self._turn:
                with self._state_lock:
                    if token in self._cancelled:
                        return False
                    if (self._user_input_at is not None
                            and time.monotonic() - self._user_input_at <= 2.0):
                        return False
                callback()
                return True
        finally:
            with self._state_lock:
                self._cancelled.discard(token)
            self._proactive_requested.clear()

    def cancel(self, token, callback=None):
        with self._state_lock:
            self._cancelled.add(token)
        if callback is not None:
            callback()

def _make_speaker():
    """Tạo bộ tổng hợp giọng nói (TTS); lỗi thì trả None (hệ thống vẫn chạy, mất giọng)."""
    try:
        from voice import config as voice_config, piper_voice, vieneu_voice
        from voice.speech_synthesizer import SpeechSynthesizer

        # Mọi tham số giọng nói gom ở `voice/config.py` — xem docstring ở đó.
        vc = voice_config.from_config(config)
        # Giọng riêng, theo TTS_ENGINE. Mỗi hàm `tao()` tự trả None nếu không phải phần
        # của mình, hoặc nếu thiếu file/thư viện (kèm log nói RÕ thiếu gì). Thiếu thì
        # chạy tiếp bằng giọng mặc định — không bao giờ để trợ lý câm.
        giong = vieneu_voice.tao(vc.noi) or piper_voice.tao(vc.noi)
        return SpeechSynthesizer(
            engine=vc.noi.engine, language=vc.noi.language,
            robot=vc.noi.robot, robot_carrier=vc.noi.robot_carrier,
            speed=vc.noi.speed, giong_rieng=giong)
    except Exception as e:
        logger.warning("TTS không khả dụng (%s) — chạy không có giọng nói.", e)
        return None


def _make_voice_input():
    """Dựng recorder + recognizer cho đầu vào micro.

    Trả về None nếu INPUT_MODE=text, hoặc nếu micro/thư viện lỗi và
    INPUT_MODE=auto (sẽ chuyển sang gõ phím). Với INPUT_MODE=voice, lỗi sẽ ném ra.
    """
    if config.INPUT_MODE == "text":
        return None
    try:
        from voice.recorder import Recorder
        from voice.speech_recognizer import SpeechRecognizer
        recorder = Recorder(
            channels=config.CHANNELS, rate=config.SAMPLE_RATE,
            chunk=config.CHUNK_SIZE, speech_threshold_ratio=config.SPEECH_THRESHOLD_RATIO,
            silence_duration=config.SILENCE_DURATION,
            max_utterance_s=config.MAX_UTTERANCE_SECONDS,
            speech_start_timeout_s=config.SPEECH_START_TIMEOUT_SECONDS,
            pre_roll_s=config.SPEECH_PRE_ROLL_SECONDS)
        recognizer = SpeechRecognizer(language=config.STT_LANGUAGE, engine=config.STT_ENGINE)
        return recorder, recognizer
    except Exception as e:
        if config.INPUT_MODE == "voice":
            raise
        logger.warning("Không dùng được micro (%s) — chuyển sang gõ phím.", e)
        return None


def _emit_tts_input(bus, text, emotion, proactive=False, mode="sync"):
    """Log exact speech input on one line so blank lines remain visible as escapes."""
    raw_text = str(text or "")
    visible = (raw_text.replace("\\", "\\\\").replace("\r", "\\r")
               .replace("\n", "\\n").replace("\t", "\\t"))
    bus.emit_debug("assistant", f"Văn bản đưa vào TTS: {visible}",
                   {"emotion": emotion, "proactive": proactive,
                    "mode": mode,
                    "characters": len(raw_text),
                    "line_breaks": raw_text.count("\n"),
                    "blank_line_boundaries": len(re.findall(
                        r"(?:\r?\n)[ \t]*(?:\r?\n)", raw_text))})
    return raw_text


def _say(synth, bus, text, emotion, proactive=False):
    """Phát trạng thái 'speaking' rồi NÓI ĐỒNG BỘ — chặn tới khi phát xong.

    Đây là chốt chặn half-duplex: vì hàm chạy trong chính thread của vòng nghe và
    speak_sync() chặn tới khi loa im, mic sẽ KHÔNG mở lại giữa lúc AI đang nói —
    loại bỏ vòng vọng âm (AI tự nghe lại giọng mình rồi tự trả lời).
    """
    raw_text = _emit_tts_input(bus, text, emotion, proactive, mode="sync")
    bus.emit(state="speaking", emotion=emotion, text=text, proactive=proactive)
    if synth:
        started = time.perf_counter()
        try:
            synth.speak_sync(text)     # chặn tới khi phát xong
        except Exception as e:
            logger.error("Lỗi khi phát giọng nói: %s", e)
        finally:
            bus.emit_debug(
                "assistant", "TTS hoàn tất",
                {"duration_ms": round((time.perf_counter() - started) * 1000, 1),
                 "characters": len(raw_text), "mode": "sync",
                 "interrupted": False}, level="SUCCESS")


def _reply_and_idle(synth, bus, voice_io, text, emotion="happy"):
    """Nói MỘT câu xen giữa vòng lặp (hỏi lại, đổi chế độ, xác nhận...) rồi mở lại vòng
    nghe. Trả về mốc nói xong — chính là lúc CỬA SỔ NỐI LỜI bắt đầu tính.

    Bốn chỗ trong `_assistant_loop` từng lặp y hệt ba dòng này; gom lại để mốc thời gian
    ấy không thể quên ở một nhánh nào (quên = lượt sau lại đòi gọi tên).
    """
    _say(synth, bus, text, emotion)
    if voice_io:
        _flush_mic_after_speaking(voice_io[0])
    bus.emit(state="idle")
    return time.monotonic()


def _flush_mic_after_speaking(recorder):
    """Bỏ audio TTS đã tồn đọng nhưng không tạo thêm khoảng mù sau khi nói xong."""
    recorder.discard_buffered(SPEAK_BUFFER_FLUSH_MAX_S)
    recorder.reset()


# Mỗi lượt nghe khi AI đang nói chỉ kéo dài ngần này (giây) rồi kiểm lại xem TTS còn chạy
# không. Khai báo bằng GIÂY chứ không phải số chunk vì số chunk đổi nghĩa theo sample rate.
BARGE_IN_LISTEN_SECONDS = 1.6


def _tts_active(synth):
    """TTS còn đang phát (đang nói hoặc còn câu trong hàng đợi)."""
    try:
        return synth.is_speaking or not synth.voice_queue.empty()
    except Exception:
        return False


def _speak_and_watch(synth, bus, text, emotion, voice_io, wake_words):
    """Nói KHÔNG chặn, đồng thời nghe wake word để NGẮT LỜI (barge-in nhẹ, không AEC).

    Trả câu lệnh mới (phần sau wake word) nếu người dùng ngắt lời; None nếu nói xong
    bình thường. Vì không có AEC, mic vẫn nghe cả giọng TTS — nên loại các wake word
    có trong chính câu trả lời (tránh AI tự ngắt lời mình khi đọc trúng từ khoá).
    """
    recorder, recognizer = voice_io
    raw_text = _emit_tts_input(bus, text, emotion, mode="async_barge_in")
    bus.emit(state="speaking", emotion=emotion, text=text)

    bargein_words = wake_words_not_in(text, wake_words)   # bỏ từ khoá trùng câu trả lời
    started = time.perf_counter()
    interrupted = False

    try:
        synth.speak(text)                                 # phát bất đồng bộ
        while _tts_active(synth):
            audio = recorder.listen_once(
                max_seconds=BARGE_IN_LISTEN_SECONDS,
                start_timeout_s=BARGE_IN_LISTEN_SECONDS)
            recorder.reset()
            active = _tts_active(synth)
            # Audio thu đúng lúc TTS kết thúc vẫn phải được nhận dạng; bản cũ break trước
            # bước này nên nuốt trọn wake word/câu lệnh của người dùng.
            if audio is not None and bargein_words:
                heard = recognizer.recognize_speech_from_data(audio)
                if heard:
                    matched, remainder = match_wake_word(heard, bargein_words)
                    if matched:
                        interrupted = active
                        if active:
                            synth.stop()                 # ngắt lời AI ngay
                        print(f"⏸ Ngắt lời (barge-in): {heard}")
                        return remainder or None
            if not active:
                break
    except Exception as e:
        logger.error("Lỗi khi nghe ngắt lời: %s", e)
    finally:
        bus.emit_debug(
            "assistant", "TTS hoàn tất",
            {"duration_ms": round((time.perf_counter() - started) * 1000, 1),
             "characters": len(raw_text), "mode": "async_barge_in",
             "interrupted": interrupted}, level="SUCCESS")
    return None


def _listen_voice(recorder, recognizer, bus):
    """Ghi một lượt nói và nhận dạng.

    Trả về câu đã nghe, hoặc _NO_INPUT nếu lượt này không nghe được gì (phải
    nghe tiếp, KHÔNG phải tín hiệu thoát).
    """
    bus.emit(state="listening", text="Đang lắng nghe...")
    print("\n--- Đang lắng nghe... ---")
    audio_data = recorder.listen_once()
    recorder.reset()
    if audio_data is None:
        print("Không phát hiện giọng nói.")
        return _NO_INPUT

    text = recognizer.recognize_speech_from_data(audio_data)
    if not text:
        print("Không nghe rõ, vui lòng thử lại.")
        return _NO_INPUT
    result = getattr(recognizer, "last_result", None)
    capture = getattr(recorder, "last_capture", None)
    capture_data = (capture.to_dict() if hasattr(capture, "to_dict") else {})
    utterance = VoiceUtterance(
        text,
        confidence=getattr(result, "confidence", None),
        alternatives=getattr(result, "alternatives", (text,)),
        capture=capture_data,
        engine=getattr(result, "engine", getattr(recognizer, "engine", None)))
    print(f"🎤 Đã nghe: {text}")
    bus.emit_debug(
        "voice", f"Người dùng: {text}",
        {"source": "microphone", "stt_engine": utterance.engine,
         "stt_confidence": utterance.confidence,
         "alternative_count": len(utterance.alternatives),
         "capture": utterance.capture})
    return utterance


def _next_input(voice_io, bus):
    """Lấy câu tiếp theo từ micro (nếu có) hoặc bàn phím.

    Trả về None CHỈ khi người dùng muốn thoát (EOF/Ctrl+C); _NO_INPUT khi lượt
    này không có gì để xử lý nhưng vẫn tiếp tục.
    """
    if voice_io:
        recorder, recognizer = voice_io
        return _listen_voice(recorder, recognizer, bus)
    try:
        text = input("Bạn: ").strip()
        if text:
            bus.emit_debug("voice", f"Người dùng: {text}", {"source": "keyboard"})
        return text
    except (EOFError, KeyboardInterrupt):
        return None


# Tuần tự hoá agent.run: vòng lặp chính VÀ lịch (thread nền) đều dùng chung -> không bao
# giờ 2 agent.run chạy song song (tránh hỏng bộ nhớ ngắn hạn / tâm trạng).
_AGENT_LOCK = threading.Lock()


def _dispatch(agent, text, bus, fast_match=None, proactive=False):
    """Xử lý MỘT câu lệnh -> (response, emotion). KHÔNG tự nói (người gọi lo phần NÓI).

    Cùng đường với lượt thường: fast-path giao diện/cuộn/chụp, hoặc agent. Tách ra để
    routine + lịch 'do' tái dùng ĐÚNG pipeline này.
    """
    bus.emit_debug("agent", f"Xử lý yêu cầu: {text}", {"proactive": proactive})
    control_action = match_control_panel_command(text)
    if control_action is not None and not proactive:
        bus.emit_control(control_action)
        return ("Đã mở bảng điều khiển." if control_action == "show" else "Đã đóng bảng điều khiển."), "neutral"
    # Scheduled action vẫn được thực thi trong DND, nhưng không được lộ trạng thái UI
    # trước gate. Phần thông báo kết quả sẽ đi qua ProactiveDispatcher sau đó.
    if not proactive:
        bus.emit(state="thinking", text="")
    # Lệnh TOOL tất định (âm lượng/media/cuộn/chụp) ưu tiên TRƯỚC lệnh giao diện avatar:
    # cụm cỡ chữ chung ("to lên/nhỏ hơn") vừa là chỉnh avatar vừa xuất hiện trong "âm lượng
    # video to lên" -> phải để fast_command (đòi từ khoá đặc thù 'âm lượng') giành trước.
    fast = fast_match(text) if (fast_match and config.FAST_COMMANDS) else None
    ui_cmd = None
    ui_resolution = None
    if config.FAST_COMMANDS and fast is None:
        named_target = explicit_ui_target(text)
        current_target = (bus.current_ui_target()
                          if hasattr(bus, "current_ui_target") else "avatar")
        # Tên đích rõ ràng luôn thắng lịch sử. Nếu câu chỉ còn "phóng to nó lên",
        # bề mặt gần nhất/đang mở quyết định trước khi luật avatar chung được xét.
        if named_target == "hud":
            ui_cmd = match_hud_command(text)
            ui_resolution = "explicit_hud"
        elif named_target == "avatar":
            ui_cmd = match_avatar_command(text)
            ui_resolution = "explicit_avatar"
        else:
            ui_cmd = (match_hud_command(text, contextual_target=current_target == "hud")
                      or match_avatar_command(text))
            ui_resolution = ("active_hud_surface" if current_target == "hud" and
                             ui_cmd and ui_cmd.get("target") == "hud"
                             else "default_avatar")
    if fast is not None and agent.registry.has(fast[0]):
        noi = _run_fast(agent, fast)
        if noi is not None:                     # None = tool cần duyệt -> để agent đi hỏi
            return noi, "happy"
    if ui_cmd is not None:
        bus.emit_ui(**ui_cmd)
        bus.emit_debug("ui", "Áp lệnh giao diện không qua LLM",
                       dict(ui_cmd, resolved_by=ui_resolution),
                       level="SUCCESS")
        print(f"⚡ (giao diện, không qua LLM) {ui_cmd}")
        return _ui_ack(ui_cmd), "happy"
    try:
        with _AGENT_LOCK:                       # chống 2 agent.run song song
            reply = agent.run(text)
        return reply.text, reply.emotion
    except Exception as e:
        logger.error("Lỗi khi chạy agent: %s", e)
        return "Xin lỗi, có lỗi khi xử lý yêu cầu.", "sad"


def _run_routine(agent, routines, name, bus, synth, voice_io, fast_match=None):
    """Chạy một routine: lặp từng bước qua _dispatch, ĐỌC kết quả mỗi bước. Bước lỗi -> tiếp
    tục (đếm lỗi). Bỏ qua bước 'chạy routine ...' để chống đệ quy (v1)."""
    r = routines.get(name)
    if r is None:
        _say(synth, bus, f"Chưa có routine tên {name}.", "sad")
        return
    errors = 0
    for step in r["steps"]:
        if match_routine_command(step):        # chống đệ quy: không cho routine gọi routine
            continue
        try:
            response, emotion = _dispatch(agent, step, bus, fast_match)
        except Exception as e:                 # phòng fast-path ném lỗi -> không vỡ cả routine
            logger.error("Bước routine lỗi (%s): %s", step, e)
            errors += 1
            continue
        _say(synth, bus, response, emotion or guess_emotion(response))
        if voice_io:
            _flush_mic_after_speaking(voice_io[0])
    tail = f"Đã chạy xong routine {r['name']}."
    if errors:
        tail += f" Có {errors} bước gặp lỗi."
    _say(synth, bus, tail, "happy")


def _assistant_loop(agent, bus, synth, voice_io, routines=None, fast_match=None,
                    intervention_gate=None, voice_turn=None, salm_care_response=None,
                    salm_style_command=None, salm_late_night_command=None, camera=None,
                    stop_event=None):
    """Vòng xử lý (thread nền): nghe/gõ -> agent -> phát trạng thái cho avatar + nói.

    Chu trình half-duplex nghiêm ngặt cho từng lượt: NGHE -> NGHĨ -> NÓI (chặn) ->
    lặng đệm -> mới NGHE lại. Không bao giờ nghe và nói cùng lúc.

    Khi nhập bằng giọng nói và bật REQUIRE_WAKE_WORD: chỉ hành động với câu có chứa
    từ khoá kích hoạt — bỏ qua lời nhạc/clip lọt vào mic (không tự trả lời loạn).

    NGOẠI LỆ — cửa sổ NỐI LỜI: FOLLOW_UP_SECONDS giây ngay sau khi trợ lý trả lời xong,
    câu tiếp theo được nhận thẳng, khỏi gọi tên. Người ta hỏi lại ("thế còn ngày mai?")
    trong vài giây sau câu trả lời, và bắt xưng tên ở đúng nhịp đó nghe như nói với máy.
    Hết cửa sổ, từ khoá bắt buộc trở lại.
    """
    hint = "Đang lắng nghe micro..." if voice_io else "Gõ yêu cầu ở cửa sổ terminal."
    # Wake word chỉ áp dụng cho đầu vào giọng nói (gõ phím là chủ đích rõ ràng rồi).
    gate_wake = bool(voice_io) and config.REQUIRE_WAKE_WORD
    wake_words = parse_wake_words(config.WAKE_WORDS)
    # Barge-in cần: giọng nói + có TTS + có wake word để phân biệt câu ngắt lời.
    bargein = bool(voice_io) and synth is not None and gate_wake and bool(wake_words) \
        and config.BARGE_IN
    # Cửa sổ nối lời chỉ có nghĩa khi từ khoá đang gác cổng; chế độ làm việc đã bỏ gác
    # rồi nên không liên quan.
    follow_up_s = config.FOLLOW_UP_SECONDS if gate_wake else 0
    if gate_wake and wake_words:
        hint += f' (nói "{wake_words[0]}" trước yêu cầu'
        if follow_up_s > 0:
            hint += f'; trong {follow_up_s:g}s sau câu trả lời thì nói thẳng'
        hint += '; hoặc "chế độ làm việc" để khỏi cần gọi tên)'
    bus.emit(state="idle", emotion="neutral", text=hint)

    pending = None          # câu lệnh có sẵn từ barge-in -> bỏ qua bước NGHE ở đầu vòng
    # Chế độ làm việc: TẠM tắt wake word (ra lệnh trực tiếp, không cần gọi tên). Chỉ có
    # nghĩa khi wake word đang được dùng (gate_wake). Đổi bằng giọng nói, không lưu file.
    work_mode = False
    # Mốc trợ lý nói xong lượt gần nhất — gốc tính cửa sổ nối lời. None = chưa nói câu nào.
    answered_at = None
    fails = 0
    while stop_event is None or not stop_event.is_set():
        # 1) Lấy câu lệnh
        if pending is not None:
            text = pending
            pending = None
        else:
            try:
                if voice_io and voice_turn is not None:
                    raw = voice_turn.next_input(lambda: _next_input(voice_io, bus))
                else:
                    raw = _next_input(voice_io, bus)
                if stop_event is not None and stop_event.is_set():
                    break
                fails = 0
            except Exception as e:   # lỗi thiết bị/mạng: thử lại, không quay vô hạn
                fails += 1
                logger.error("Lỗi khi lấy đầu vào (%d/%d): %s", fails, MAX_INPUT_FAILS, e)
                if fails >= MAX_INPUT_FAILS:
                    print("\nĐầu vào lỗi liên tiếp — dừng nhận lệnh.")
                    break
                time.sleep(1)
                continue
            if raw is None:                     # EOF/Ctrl+C -> thoát
                break
            if raw is _NO_INPUT or not raw:     # không nghe/gõ được gì -> nghe tiếp
                bus.emit(state="idle")
                continue

            # Tính assessment sớm để giữ nguyên metadata STT/VAD, nhưng CHƯA được phát
            # lời hỏi lại. Recovery chỉ có quyền lên tiếng sau khi lượt nói đã vượt qua
            # wake-word gate (hoặc thuộc một ngoại lệ chủ đích như work/follow-up/
            # confirmation). Nếu không, tiếng nền dài chạm max duration sẽ vô tình tạo
            # một đường vòng qua wake word.
            awaiting_confirm = (agent.pending is not None
                                and match_confirmation(raw) is not None)
            assessment = assess_voice_utterance(
                raw, allow_short_confirmation=awaiting_confirm)
            if raw.lower() in ("thoát", "exit", "quit"):
                break

            # SALM-1.1 chỉ nhận phản hồi thuộc check-in đang mở (cùng escape hatch bật
            # lại DND). Chỉ đưa transcript đủ chắc vào matcher vì handler có thể commit
            # state; câu không chắc sẽ fail-closed và tiếp tục qua cổng chủ đích bên dưới.
            # unrelated/fail-closed trả None nên câu gốc vẫn đi Agent pipeline.
            if salm_care_response is not None and not assessment.retry:
                care_reply = salm_care_response(raw)
                if care_reply:
                    answered_at = _reply_and_idle(
                        synth, bus, voice_io, care_reply, "happy")
                    continue

            # Đang CHỜ xác nhận một hành động khó hoàn tác + câu là 'có'/'không' -> nhận
            # trực tiếp, không cần gọi tên (đối thoại tự nhiên). Câu KHÁC vẫn cần wake word
            # nên không nới lỏng an toàn chung.
            # Mốc BẮT ĐẦU nói, không phải lúc nhận dạng xong: một câu dài (hoặc STT
            # chậm) không được ăn mất cửa sổ nối lời của chính nó.
            onset = voice_io[0].speech_started_at if voice_io else None
            follow_up = in_follow_up_window(answered_at, onset or time.monotonic(),
                                            follow_up_s)

            # Ba đường được miễn từ khoá: chế độ làm việc, câu 'có/không' đang chờ xác
            # nhận, và cửa sổ nối lời ngay sau câu trả lời trước.
            if gate_wake and not work_mode and not awaiting_confirm and not follow_up:
                matched, remainder = match_wake_word(raw, wake_words)
                if not matched:
                    print(f"(bỏ qua — không có từ khoá kích hoạt): {raw}")
                    bus.emit_debug("voice", "Bỏ qua câu không có từ khoá kích hoạt",
                                   {"text": raw}, level="DEBUG")
                    bus.emit(state="idle")
                    continue
                if not remainder:               # chỉ gọi tên, chưa có yêu cầu cụ thể
                    answered_at = _reply_and_idle(synth, bus, voice_io, "Dạ, bạn cần gì?")
                    continue
                text = remainder
            else:
                if follow_up and not work_mode:      # follow_up chỉ bật khi có gác cổng
                    print("↩ (nối lời — trong cửa sổ sau câu trả lời, khỏi gọi tên)")
                text = raw

            # Đến đây lượt nói đã được xác lập là có chủ đích. Recovery được phép hỏi
            # lại, nhưng không bao giờ có thể tự mở wake-word gate chỉ vì VAD/STT báo
            # câu bị cắt hoặc confidence thấp.
            if assessment.retry:
                bus.emit_debug(
                    "voice", "Yêu cầu nói lại vì STT không chắc",
                    {"reason_codes": list(assessment.reason_codes)},
                    level="WARNING")
                answered_at = _reply_and_idle(
                    synth, bus, voice_io, assessment.prompt, "neutral")
                continue

        # Camera privacy control stays local, including when FAST_COMMANDS is disabled.
        # It runs only after the same wake-word and STT certainty gates as normal input.
        camera_off, remaining_request = extract_camera_off_command(text, wake_words)
        if camera_off:
            try:
                camera_reply = turn_off_webcam(camera)
            except Exception as exc:
                bus.emit_debug("camera", "Không thể tắt webcam bằng giọng nói", {
                    "error": type(exc).__name__}, level="ERROR")
                camera_reply = "Tôi chưa tắt được webcam. Bạn thử lại giúp tôi."
            answered_at = _reply_and_idle(synth, bus, voice_io, camera_reply, "neutral")
            if not remaining_request:
                continue
            bus.emit_debug("camera", "Đã xử lý vế tắt webcam trong câu ghép", {
                "has_remaining_request": True})
            text = remaining_request

        # 1b) CHUYỂN CHẾ ĐỘ nghe (chỉ khi wake word đang được dùng): "chế độ làm việc"
        # tắt wake word để ra lệnh trực tiếp; "chế độ bình thường" bật lại.
        if gate_wake:
            mode = match_mode_command(text)
            if mode is not None:
                work_mode = (mode == "work")
                if intervention_gate is not None:
                    intervention_gate.set_work_mode(work_mode)
                msg = ("Đã bật chế độ làm việc. Bạn ra lệnh trực tiếp, không cần gọi tên tôi nữa."
                       if work_mode else
                       "Đã trở lại chế độ bình thường. Hãy gọi tên tôi trước mỗi yêu cầu.")
                answered_at = _reply_and_idle(synth, bus, voice_io, msg)
                continue

        # SALM-2 chỉ nhận lệnh chỉnh phong cách SAU wake-word gate. Ngoại lệ duy nhất
        # là response window của check-in, đã được runtime xử lý ở try_care_response.
        if salm_style_command is not None:
            style_reply = salm_style_command(text)
            if style_reply:
                answered_at = _reply_and_idle(
                    synth, bus, voice_io, style_reply, "happy")
                continue

        # Late-night Care là policy tường minh, cùng đi qua wake-word gate như các lệnh
        # SALM khác. Matcher hẹp để câu kể "hôm nay làm việc khuya" vẫn đến Agent.
        if salm_late_night_command is not None:
            late_reply = salm_late_night_command(text)
            if late_reply:
                answered_at = _reply_and_idle(
                    synth, bus, voice_io, late_reply, "happy")
                continue

        # 1c) CHỈNH TÍNH CÁCH bằng lời (học tường minh): "vui tính hơn", "nghiêm túc hơn",
        # "reset tính cách". Áp thẳng lên núm (có biên) + cập nhật baseline tâm trạng.
        if agent.persona is not None:
            pcmd = match_persona_command(text)
            if pcmd is not None:
                if pcmd.get("reset"):
                    agent.persona.reset_traits()
                else:
                    agent.persona.adjust(pcmd["trait"], pcmd["delta"])
                if agent.mood is not None:
                    agent.mood.set_baseline(agent.persona.baseline_valence(),
                                            agent.persona.baseline_arousal())
                answered_at = _reply_and_idle(synth, bus, voice_io, pcmd["say"])
                continue

        # 1d) CHẠY ROUTINE bằng lời: "chạy routine X" -> lặp từng bước qua _dispatch.
        if routines is not None:
            rname = match_routine_command(text)
            if rname is not None:
                if not controls.get("feature.task", True):
                    answered_at = _reply_and_idle(synth, bus, voice_io, "Routine đang tắt trong bảng điều khiển.")
                    continue
                _run_routine(agent, routines, rname, bus, synth, voice_io, fast_match)
                answered_at = time.monotonic()
                bus.emit(state="idle")
                continue

        # 2) NGHĨ — qua _dispatch (fast-path giao diện/cuộn/chụp, hoặc agent)
        response, emotion = _dispatch(agent, text, bus, fast_match)

        # 3) NÓI — có barge-in (vừa nói vừa nghe wake word) hoặc chặn như cũ
        print(f"Trợ lý: {response}\n")
        emo = emotion or guess_emotion(response)
        if bargein:
            pending = _speak_and_watch(synth, bus, response, emo, voice_io, wake_words)
        else:
            _say(synth, bus, response, emo)     # chặn tới khi nói xong

        # Chỉ sau khi nói/ngắt xong mới dọn mic + mở lại vòng nghe (chống vọng âm).
        if voice_io:
            _flush_mic_after_speaking(voice_io[0])
        answered_at = time.monotonic()      # mở cửa sổ nối lời cho lượt kế
        bus.emit(state="idle")

    if voice_io:
        voice_io[0].close()
    if intervention_gate is not None:
        intervention_gate.set_work_mode(False)
    bus.emit(state="idle", text="Đã dừng nhận lệnh.")
    print("\n(Đã dừng nhận lệnh. Đóng cửa sổ avatar để thoát hẳn.)")


def _make_browser_bridge():
    """Dựng + khởi động cầu nối Chrome nếu bật (BROWSER_BRIDGE_ENABLED). Lỗi/thiếu
    'websockets' -> trả None (agent chạy bình thường, chỉ thiếu điều khiển Chrome)."""
    if not config.BROWSER_BRIDGE_ENABLED:
        return None
    try:
        from services.browser_bridge import BrowserBridge
        bridge = BrowserBridge(host=config.BROWSER_BRIDGE_HOST,
                               port=config.BROWSER_BRIDGE_PORT,
                               token=config.BROWSER_BRIDGE_TOKEN)
        if bridge.start():
            print(f"🌐 Cầu nối Chrome bật ở ws://{config.BROWSER_BRIDGE_HOST}:"
                  f"{config.BROWSER_BRIDGE_PORT} (chờ extension).")
            return bridge
    except Exception as e:
        logger.warning("Không bật được cầu nối Chrome: %s", e)
    return None


def _ui_ack(ui):
    """Câu xác nhận ngắn cho lệnh chỉnh giao diện, không qua LLM."""
    if ui.get("target") == "hud":
        if "scale" in ui and ui.get("scale") == 1.0:
            return "Đã đưa bảng thông tin về kích thước mặc định."
        if ui.get("scale_delta", 0) < 0:
            return "Đã thu nhỏ bảng thông tin."
        if ui.get("scale_delta", 0) > 0:
            return "Đã phóng to bảng thông tin."
        return "Đã điều chỉnh kích thước bảng thông tin."
    if ui.get("scale_delta", 0) < 0:
        return "Đã thu nhỏ avatar."
    if ui.get("scale_delta", 0) > 0:
        return "Đã phóng to avatar."
    if ui.get("opacity_delta", 0) < 0:
        return "Đã làm mờ hơn."
    if ui.get("opacity_delta", 0) > 0:
        return "Đã làm rõ hơn."
    return "Đã cập nhật giao diện."


def _run_fast(agent, fast):
    """Chạy thẳng một tool (fast-path), không qua LLM. Trả câu kết quả để nói.

    Trả None nếu tool cần người dùng duyệt: fast-path không có chỗ để hỏi, nên nhường lượt
    cho đường LLM — ở đó agent hoãn hành động và hỏi đúng luồng xác nhận. Không luật nào
    hiện nay khớp ra tool cần duyệt, nhưng chỉ cần thêm một luật khớp ra `close_app` là
    tình huống này thành thật; chặn ở đây thì nó không bao giờ thành lỗ hổng.
    """
    tool_name, tool_args = fast
    try:
        out = str(agent.registry.run(tool_name, tool_args))
    except NeedsConfirmation:
        logger.info("Fast-path %s cần xác nhận -> nhường cho đường LLM.", tool_name)
        return None
    except ActionRefused as exc:
        return exc.ly_do
    except Exception as e:
        logger.error("Lỗi chạy nhanh %s: %s", tool_name, e)
        return "Xin lỗi, có lỗi khi thực hiện."
    print(f"⚡ (chạy nhanh, không qua LLM) {tool_name} → {out}")
    if tool_name == "control_room_ac":
        return describe_ac_result(out, tool_args)
    if tool_name == "configure_climate_automation":
        return describe_automation_result(out)
    return out


def _make_screen_controller():
    """Dựng ScreenController nếu bật + LLM local. Trả None nếu tắt hoặc LLM online.

    BẢO MẬT: nội dung màn hình (chữ OCR) sẽ được đưa cho LLM. Chỉ cho phép khi LLM
    là local (ollama) để nội dung KHÔNG rời máy; dùng LLM online -> từ chối bật.
    """
    if not config.SCREEN_CONTROL_ENABLED:
        return None
    if (config.LLM_PROVIDER or "").lower() != "ollama":
        msg = ("⚠ Điều khiển màn hình cần LLM LOCAL (ollama) để nội dung không rời máy "
               f"— đã BỎ QUA (LLM_PROVIDER={config.LLM_PROVIDER}).")
        logger.warning(msg)
        print(msg)
        return None
    try:
        from actions.screen_control import ScreenController
        sc = ScreenController(save_dir=config.SCREEN_CAPTURE_DIR or None,
                              tesseract_cmd=config.TESSERACT_CMD or None)
        print("🖥 Điều khiển màn hình: BẬT (local, offline).")
        return sc
    except Exception as e:
        logger.warning("Không bật được điều khiển màn hình: %s", e)
        return None


def _frame_reminder(message):
    """Bọc nội dung nhắc thành câu RÕ RÀNG là 'lời nhắc' — để không nghe như trợ lý đang
    tự thực thi lệnh hay báo lỗi (vd nội dung 'mở Claude' đọc trơn dễ hiểu nhầm)."""
    msg = (message or "").strip().rstrip(".!?").strip()
    if not msg:
        return "Đến giờ rồi, bạn có một lời nhắc."
    return f"Đến giờ rồi, bạn nhờ tôi nhắc: {msg}."


def _compose_brief(profile, tasks):
    """Soạn nội dung bản tin sáng: chào + thời tiết + việc hôm nay. (Không qua agent/LLM.)"""
    parts = ["Chào buổi sáng!"]
    try:
        loc = (profile.get_default_location() if profile else None) or config.WEATHER_DEFAULT_LOCATION
        from actions.weather import get_weather
        parts.append(get_weather(loc))
    except Exception as e:
        logger.warning("Bản tin sáng: không lấy được thời tiết: %s", e)
    items = tasks.list() if tasks else []
    if items:
        parts.append(f"Hôm nay bạn có {len(items)} việc cần làm: "
                     + "; ".join(t["text"] for t in items) + ".")
    else:
        parts.append("Hôm nay bạn chưa có việc nào cần làm.")
    return " ".join(parts)


def _global_proactive_blocked(dispatcher):
    gate = getattr(dispatcher, "gate", None)
    return bool(gate is not None and gate.reasons("global"))


def _submit_proactive_speech(dispatcher, synth, bus, text, emotion, kind):
    """Đưa một lời chủ động qua gate duy nhất; gate đóng thì bỏ, không xếp backlog."""
    cancelled = threading.Event()

    def present():
        if cancelled.is_set() or _global_proactive_blocked(dispatcher):
            return
        resolved = text() if callable(text) else text
        # LLM có thể trả sau khi work-mode/meeting/direct reply đã đóng gate.
        if cancelled.is_set() or _global_proactive_blocked(dispatcher):
            return
        _say(synth, bus, resolved, emotion, proactive=True)
        bus.emit(state="idle", proactive=True)

    def cancel():
        cancelled.set()
        if synth is not None:
            synth.stop()

    return dispatcher.submit(Intervention(
        kind=kind,
        scope="global",
        present=present,
        cancel=cancel,
    ))


def _start_with_greeting(dispatcher, synth, bus, on_complete,
                         welcome_dialogue=None):
    """Đợi giọng chính sẵn sàng, chào xong mới mở input để tránh mic tự thu lời chào.

    Gate chặn hoặc item bị drop giữa queue vẫn phải gọi ``on_complete`` đúng một lần;
    lời chào không bao giờ được biến thành blocker khiến trợ lý không nhận lệnh. VieNeu
    nạp ở nền; chờ xảy ra trong dispatcher thread, không chặn Tk mainloop.
    """
    completed = threading.Event()
    cancelled = threading.Event()
    complete_lock = threading.Lock()

    def complete_once():
        with complete_lock:
            if completed.is_set():
                return
            completed.set()
        on_complete()

    def present():
        try:
            if synth is None:
                logger.warning("Bỏ lời chào khởi động: TTS không khả dụng.")
                return
            waiter = getattr(synth, "wait_until_voice_ready", None) if synth else None
            if waiter is not None and not waiter(STARTUP_GREETING_VOICE_TIMEOUT_S):
                logger.warning("Bỏ lời chào khởi động: giọng chính nạp lỗi hoặc chưa "
                               "sẵn sàng trong %.0fs.",
                               STARTUP_GREETING_VOICE_TIMEOUT_S)
                return
            if cancelled.is_set():
                return
            text = (welcome_dialogue.generate("startup")
                    if welcome_dialogue is not None else STARTUP_GREETING_TEXT)
            if cancelled.is_set() or _global_proactive_blocked(dispatcher):
                return
            _say(synth, bus, text, "happy", proactive=True)
            bus.emit(state="idle", proactive=True)
        finally:
            complete_once()

    def cancel():
        cancelled.set()
        if synth is not None:
            synth.stop()

    accepted = dispatcher.submit(Intervention(
        kind="startup_greeting", scope="global", present=present,
        cancel=cancel,
        on_drop=complete_once))
    if not accepted:
        complete_once()
    return accepted


def _run_scheduled(bus, synth, agent, dispatcher, message, kind, fast_match=None):
    """Callback khi một mục lịch tới hạn. kind='do' -> THỰC THI lệnh qua _dispatch (có khoá
    trong _dispatch chống chạy song song vòng lặp chính); 'remind' -> chỉ đọc lời nhắc."""
    if kind == "do":
        print(f"\n⏰ Thực thi theo lịch: {message}")
        response, emotion = _dispatch(agent, message, bus, fast_match, proactive=True)
        _submit_proactive_speech(dispatcher, synth, bus, response,
                                 emotion or guess_emotion(response), "scheduled_result")
    else:
        print(f"\n🔔 Nhắc: {message}")
        _submit_proactive_speech(dispatcher, synth, bus, _frame_reminder(message),
                                 "happy", "scheduled_reminder")


def main():
    print("=== Trợ lý AI: agent + avatar + giọng nói (khởi chạy hợp nhất) ===")

    bus = AssistantBus()
    # Debug is session-only: a prior control setting must not reopen its
    # diagnostic window or image preview on the next ordinary launch.
    debug_enabled = config.DEBUG_PANEL_ENABLED or "--debug-panel" in sys.argv[1:]
    config.DEBUG_PANEL_ENABLED = bool(debug_enabled)
    bus.set_debug_enabled(debug_enabled)
    debug_state = threading.Event()
    if debug_enabled:
        debug_state.set()

    def emit_debug_if_enabled(category, message, data=None, level="INFO"):
        if debug_state.is_set():
            bus.emit_debug(category, message, data, level=level)

    debug_log_handler = None
    if debug_enabled:
        from utils.debug import install_bus_log_handler
        debug_log_handler = install_bus_log_handler(bus)
        bus.emit_debug("system", "Khởi động trợ lý với panel debug", {
            "python": sys.version.split()[0],
            "input_mode": config.INPUT_MODE,
            "llm_provider": config.LLM_PROVIDER,
        })

    try:
        llm = build_default_llm_client()
    except RuntimeError as e:
        print(f"Không khởi tạo được LLM: {e}")
        if debug_log_handler is not None:
            from utils.debug import uninstall_bus_log_handler
            uninstall_bus_log_handler(debug_log_handler)
        return

    database = None
    if config.DATA_DATABASE_ENABLED and config.DATA_DATABASE_PATH:
        try:
            database = LocalDatabase(config.DATA_DATABASE_PATH)
            logger.info("SQLite local data store sẵn sàng: %s", config.DATA_DATABASE_PATH)
        except Exception as e:
            logger.warning("Không mở được SQLite; tạm dùng kho file cũ: %s", e)

    profile = UserProfile(config.USER_PROFILE_PATH or None, database=database)
    # Persona là nguồn giọng CHUNG cho Agent lẫn mọi lane phát lời SALM. Khởi tạo trước
    # SALM để greeting/check-in không dựng một nhân cách thứ hai bằng prompt riêng.
    persona = mood = None
    if config.PERSONA_ENABLED:
        persona = PersonaState(config.PERSONA_PATH or None, provider=config.LLM_PROVIDER)
        mood = MoodState(baseline_valence=persona.baseline_valence(),
                         baseline_arousal=persona.baseline_arousal())
    synth = _make_speaker()
    voice_turn = _VoiceTurnCoordinator()
    app_closing = threading.Event()
    camera = None
    welcome_dialogue = WelcomeDialogue(
        llm if config.SALM_LIFECYCLE_GREETING_LLM_ENABLED else None,
        timeout_seconds=config.SALM_WELCOME_LLM_TIMEOUT_SECONDS,
        address_form_provider=profile.get_address_form,
        persona_context_provider=(persona.render if persona is not None else None),
        proactive_text_provider=(persona.proactive_text if persona is not None else None))

    camera_return_mode = (config.CAMERA_WORKSTATION_RETURN_MODE.strip().lower()
                          if config.SALM_ENABLED and config.SALM_WELCOME_BACK_ENABLED and config.CAMERA_RETURN_ENABLED
                          else "shadow")
    camera_welcome_dialogue = None
    if camera_return_mode == "llm":
        try:
            camera_welcome_client = build_camera_welcome_client(config)
        except Exception as exc:
            camera_welcome_client = None
            if debug_state.is_set():
                bus.emit_debug("camera", "Camera welcome LLM unavailable", {
                    "error": type(exc).__name__}, level="WARNING")
        camera_welcome_dialogue = CameraReturnWelcome(
            camera_welcome_client,
            budget_path=config.CAMERA_WELCOME_LLM_BUDGET_PATH,
            timeout_seconds=config.CAMERA_WELCOME_LLM_TIMEOUT_SECONDS,
            min_interval_seconds=config.CAMERA_WELCOME_LLM_MIN_INTERVAL_SECONDS,
            max_per_hour=config.CAMERA_WELCOME_LLM_MAX_PER_HOUR,
            max_per_day=config.CAMERA_WELCOME_LLM_MAX_PER_DAY,
            address_form_provider=profile.get_address_form,
            persona_context_provider=(persona.render if persona is not None else None),
            proactive_text_provider=(persona.proactive_text if persona is not None else None),
            debug=emit_debug_if_enabled)

    # Mọi output KHÔNG do người dùng vừa yêu cầu đều đi qua đúng một cổng. Trạng thái
    # thinking/speaking của luồng trực tiếp đóng cổng; event do dispatcher tự phát được
    # đánh dấu proactive để không tự triệt tiêu chính mình.
    intervention_gate = InterventionGate(salm_enabled=config.SALM_ENABLED)
    bus.subscribe_state(intervention_gate.set_assistant_state)
    proactive_dispatcher = ProactiveDispatcher(intervention_gate)
    proactive_dispatcher.start()

    scheduler = ReminderScheduler()      # notify + start() đặt SAU khi có agent (lịch 'do' cần agent)

    browser = _make_browser_bridge()
    screen = _make_screen_controller()

    # SALM là feature nền (không phải LLM tool): ownership nằm trọn trong
    # `features/salm`, app.py chỉ làm composition root và quản lý start/stop.
    def _desktop_return_welcome(_event):
        _submit_proactive_speech(
            proactive_dispatcher, synth, bus,
            lambda: welcome_dialogue.generate("return"),
            "happy", "welcome_back")

    def _camera_return_welcome(request):
        # Submit only a callback here: presence inference never waits for I/O or TTS.
        cancelled = threading.Event()
        token = ("camera_return", request.absence_episode_id)

        def report(message, reason=None):
            if debug_state.is_set():
                data = {"episode_id": request.absence_episode_id}
                if reason is not None:
                    data["reason"] = reason
                bus.emit_debug("camera", message, data)

        def eligible():
            return (not cancelled.is_set() and not app_closing.is_set() and
                    not _global_proactive_blocked(proactive_dispatcher) and
                    camera is not None and camera.camera_role == "workstation_facing" and
                    camera.visual_input_active() and
                    return_coordinator.camera_request_current(request))

        def deliver():
            if not eligible():
                report("Camera welcome dropped", "stale_or_cancelled")
                return
            text = (camera_welcome_dialogue.generate(request, is_allowed=eligible)
                    if camera_welcome_dialogue is not None else
                    welcome_fallback("return", profile.get_address_form()))
            if not text or not eligible():
                report("Camera welcome output dropped", "stale_cancelled_or_duplicate")
                return
            report("Camera welcome submitted to speech")
            _say(synth, bus, text, "happy", proactive=True)
            bus.emit(state="idle", proactive=True)

        def present():
            if not eligible():
                report("Camera welcome dropped", "stale_or_cancelled")
                return
            if voice_io:
                if not voice_turn.present(token, deliver):
                    report("Camera welcome dropped", "user_input_priority")
            else:
                deliver()

        def cancel():
            cancelled.set()
            if synth is not None:
                synth.stop()

        def drop():
            cancelled.set()
            report("Camera welcome dropped", "dispatcher_gate")

        submitted = proactive_dispatcher.submit(Intervention(
            kind="camera_welcome_back", scope="global", present=present,
            cancel=cancel, on_drop=drop))
        if not submitted:
            report("Camera welcome not submitted", "dispatcher_gate")
        return submitted

    return_coordinator = WorkstationReturnCoordinator(
        mode=camera_return_mode,
        on_camera_welcome=_camera_return_welcome,
        on_desktop_welcome=_desktop_return_welcome,
        debug=emit_debug_if_enabled)
    salm = None
    if config.SALM_ENABLED:
        try:
            def on_return(_event):
                return_coordinator.on_desktop_return(_event)

            def on_checkin(action, decision, text):
                token = decision.candidate_id
                if action == "cancel":
                    voice_turn.cancel(
                        token, (lambda: synth.stop()) if synth is not None else None)
                    bus.emit(state="idle", proactive=True)
                    return True
                if synth is None:
                    return False

                def speak():
                    _say(synth, bus, text, "happy", proactive=True)
                    bus.emit(state="idle", proactive=True)

                return voice_turn.present(token, speak)

            def on_late_night(action, signal, text):
                token = signal.candidate_id
                if action == "cancel":
                    voice_turn.cancel(
                        token, (lambda: synth.stop()) if synth is not None else None)
                    bus.emit(state="idle", proactive=True)
                    return True
                if synth is None:
                    return False

                def speak():
                    _say(synth, bus, text, "happy", proactive=True)
                    bus.emit(state="idle", proactive=True)

                return voice_turn.present(token, speak)

            salm_storage = SalmStorage(
                config.SALM_DATA_DIR, ttl_days=14, daily_ttl_days=90,
                database=database)
            salm = SalmRuntime(
                data_dir=config.SALM_DATA_DIR,
                storage=salm_storage,
                browser=browser,
                poll_seconds=config.SALM_POLL_SECONDS,
                wasapi_fallback=config.SALM_WASAPI_MEDIA_FALLBACK,
                ttl_days=14,
                gate=intervention_gate,
                dispatcher=proactive_dispatcher,
                policy_shadow=config.SALM_POLICY_SHADOW_ENABLED,
                silent_care=config.SALM_SILENT_CARE_ENABLED,
                on_care=bus.emit_care,
                on_return=(on_return if config.SALM_WELCOME_BACK_ENABLED else None),
                on_activity=return_coordinator.observe_activity,
                gentle_checkin=config.SALM_GENTLE_CHECKIN_ENABLED,
                on_checkin=on_checkin,
                care_llm=llm,
                care_llm_intent=config.SALM_CARE_LLM_INTENT_ENABLED,
                care_llm_language=config.SALM_CARE_LLM_LANGUAGE_ENABLED,
                care_language_timeout=config.SALM_CARE_LLM_TIMEOUT_SECONDS,
                address_form_provider=profile.get_address_form,
                persona_context_provider=(persona.render if persona is not None else None),
                proactive_text_provider=(persona.proactive_text
                                         if persona is not None else None),
                user_dnd=config.SALM_USER_DND_ENABLED,
                care_style_enabled=config.SALM_CARE_STYLE_LEARNING_ENABLED,
                on_care_style=bus.emit_care_style,
                on_debug=emit_debug_if_enabled,
                late_night_enabled=config.SALM_LATE_NIGHT_ENABLED,
                late_night_language_enabled=(
                    config.SALM_LATE_NIGHT_LLM_LANGUAGE_ENABLED),
                late_night_min_active_seconds=(
                    config.SALM_LATE_NIGHT_MIN_ACTIVE_MINUTES * 60.0),
                on_late_night=on_late_night,
            )
            salm.start()
        except Exception as e:
            logger.warning("Không bật được SALM-0A shadow: %s", e)
            salm = None

    # MCP client (lịch/email qua server ngoài) — opt-in; cần server + OAuth do người dùng dựng.
    mcp = None
    if config.MCP_ENABLED and config.MCP_COMMAND:
        mcp = MCPClient(config.MCP_COMMAND, args=config.MCP_ARGS.split())
        if not mcp.start():
            logger.warning("MCP không kết nối được — bỏ qua (kiểm tra MCP_COMMAND/server/OAuth).")
            mcp = None

    habits = HabitLog(database=database) if config.HABITS_ENABLED else None
    # Nhật ký kết quả: chỉ QUAN SÁT, không đổi hành vi lượt nào. Phải chạy thật một thời
    # gian mới có mốc nền để về sau biết trợ lý có khá lên không.
    outcomes = OutcomeLog(config.OUTCOMES_FILE, config.OUTCOMES_MAX_BYTES,
                          database=database)
    tasks = TaskStore(config.TASKS_PATH or None)
    routines = RoutineStore(config.ROUTINES_PATH or None)
    contacts = ContactStore(config.CONTACTS_PATH or None)
    # Vị trí: kho RUNTIME giữ toạ độ chính xác, tách khỏi hồ sơ (hồ sơ đi lên LLM).
    location = LocationStore(config.LOCATION_PATH or None)
    places = PlacesService(bridge=browser, source=config.PLACES_SOURCE,
                           radius_km=config.PLACES_RADIUS_KM,
                           area_radius_km=config.AREA_RADIUS_KM,
                           limit=config.PLACES_KEEP,
                           weights={"distance": config.PLACES_W_DISTANCE,
                                    "quality": config.PLACES_W_QUALITY,
                                    "open": config.PLACES_W_OPEN,
                                    "evidence": config.PLACES_W_EVIDENCE})

    # Analytics đọc daily aggregate trong SQLite; preference chỉ đổi từ yêu cầu rõ ràng.
    # Khi database tắt/lỗi, feature tự vắng mặt thay vì giả dữ liệu từ raw fallback.
    activity_insights = (ActivityInsightsService(
        database,
        clear_history=(salm.clear_activity_history
                       if salm is not None else database.clear_salm_activity))
                         if database is not None else None)

    iot_client = IoTClient()
    camera = CameraService(iot_client, room_id=config.IOT_CAMERA_ROOM_ID,
                            camera_index=config.IOT_CAMERA_INDEX,
                            camera_id=config.CAMERA_SOURCE_ID,
                            camera_label=config.CAMERA_SOURCE_LABEL,
                            camera_role=config.CAMERA_SOURCE_ROLE,
                            proximity_calibration_path=(
                                config.CAMERA_PROXIMITY_CALIBRATION_PATH),
                            proximity_handler=return_coordinator.observe_camera,
                            debug_sink=emit_debug_if_enabled,
                            preview_enabled=False)
    iot_voice_alerts = (VoiceAlertPoller(
        iot_client,
        lambda message: (_submit_proactive_speech(
            proactive_dispatcher, synth, bus, message, "sad", "iot_temperature_alert")
                         if config.IOT_ENABLED and config.IOT_VOICE_ALERTS_ENABLED else None))
                        if iot_client is not None else None)

    # Toàn bộ tool đến từ danh mục feature — xem `features/catalog.py`.
    actions = AssistantActions()
    feature_ctx = FeatureContext(actions=actions, activity_insights=activity_insights,
                                 bus=bus, browser=browser, camera=camera, iot=iot_client,
                                 contacts=contacts, habits=habits, location=location, mcp=mcp,
                                 places=places, profile=profile, routines=routines,
                                 scheduler=scheduler, screen=screen, tasks=tasks)
    registry, report = build_registry(feature_ctx)
    registry.set_feature_gate(lambda group: (
        controls.get("feature." + group, True) and
        (group != "iot" or config.IOT_ENABLED) and
        (group != "camera" or config.CAMERA_ENABLED)) if group else True)
    registry.set_debug_sink(emit_debug_if_enabled)
    if debug_state.is_set():
        bus.emit_debug("system", "Đã nạp danh mục công cụ", {
            "tool_count": len(registry.names()),
            "tools": registry.names(),
        }, level="SUCCESS")

    # Fast-path (tầng 0, không tốn lượt LLM nào) gom từ chính các feature ĐÃ nạp —
    # feature bị bỏ qua thì luật của nó cũng vắng mặt. Xem `features/fast.py`.
    def fast_match(text):
        return feature_fast.match(text, report)

    # BỀ MẶT TOOL (`agent/surface.py`): lượt này model thấy prompt gì + tool nào.
    # Router thu hẹp prompt+tool bằng 1 lượt LLM phân loại. Provider mạnh không cần (đo
    # được: bỏ router vẫn 100% chọn đúng tool, bớt 1 call/lượt) -> ROUTER_MODE=auto tắt,
    # và Agent tự rơi về `AllTools` (gửi hết).
    # Khi TẮT phải dùng prompt GỘP: không có ai chọn fragment theo case nữa, dùng base
    # trần sẽ mất sạch chỉ dẫn riêng (đọc nguyên văn kết quả web, tra danh bạ, ...).
    #
    # Dựng SAU registry vì bảng case->tool nay suy ra từ `report` chứ không còn là hằng
    # số chép tay — router không thể biết case nào tồn tại trước khi feature nạp xong.
    from llm import prompts
    surface, system_prompt = None, None
    che_do = config.surface_mode()
    if che_do == "router":
        from agent.router import Router
        surface = Router.from_report(llm, report, mcp_prefix=config.MCP_TOOL_PREFIX)
    elif che_do == "indexed":
        from agent.surface import IndexedTools
        # `base()` chứ KHÔNG phải `merged()`: `IndexedTools` tự gửi sẵn chỉ dẫn của nhóm
        # có tool lõi, còn nhóm khác nhận chỉ dẫn lúc gọi `mo_nhom`. Gửi sẵn cả 10 bộ ở
        # đây vừa trùng vừa phá phần tiết kiệm — xem docstring `IndexedTools`.
        surface = IndexedTools(prompts.base(), report)
    else:
        system_prompt = prompts.merged(report)
    logger.info("🧭 bề mặt tool: %s", che_do)

    agent = Agent(llm=llm,
                  registry=registry,
                  **({"system": system_prompt} if system_prompt else {}),
                  max_history_turns=config.MAX_HISTORY_TURNS,
                  memory_path=config.MEMORY_PATH or None, surface=surface, profile=profile,
                  auto_extract=config.LTM_AUTO_EXTRACT,
                  consolidate_every=config.LTM_CONSOLIDATE_EVERY,
                  persona=persona, mood=mood, habits=habits, outcomes=outcomes,
                  auto_tune=config.PERSONA_AUTO_TUNE,
                  skip_respond_for_speakable=config.SKIP_RESPOND_FOR_SPEAKABLE,
                  # Hành động chờ xác nhận mà có nội dung đáng NHÌN (thân thư email) ->
                  # trưng lên panel thay vì bắt tai nghe TTS đọc cả lá thư.
                  on_pending=bus.emit_draft)

    # Giờ đã có agent -> nối callback lịch (remind đọc / do thực thi) rồi chạy scheduler.
    scheduler.notify = lambda msg, kind="remind": _run_scheduled(
        bus, synth, agent, proactive_dispatcher, msg, kind, fast_match)

    # Chủ động: bản tin sáng + theo dõi pin (vòng nền).
    monitor = None
    if config.PROACTIVE_ENABLED:
        try:
            _bh, _bm = (int(x) for x in config.MORNING_BRIEF_TIME.split(":"))
        except (ValueError, AttributeError):
            _bh, _bm = 7, 0

        def _on_brief():
            print("\n☀️ Bản tin sáng")
            _submit_proactive_speech(proactive_dispatcher, synth, bus,
                                     _compose_brief(profile, tasks), "happy",
                                     "morning_brief")

        def _on_battery(pct):
            # Quản trị pin: BÁO rồi LÀM. Hạ sáng là việc duy nhất trợ lý được tự làm ở đây
            # (`Tool.tu_dong`) — nó tiết kiệm pin thật và hoàn tác được bằng một câu nói,
            # nên luôn nói ra là đã hạ để người dùng biết đường bảo sáng lại.
            def present_battery_alert():
                cau = f"Pin còn khoảng {int(pct)} phần trăm, bạn nên cắm sạc nhé."
                muc = muc_sang_khi_pin_yeu(read_brightness())
                if muc is not None:
                    try:
                        agent.registry.run("set_brightness", {"level": muc}, tu_dong=True)
                        cau += (f" Tôi hạ độ sáng xuống {muc} phần trăm cho đỡ tốn, "
                                "muốn sáng lại thì bảo tôi.")
                    except Exception as e:  # không hạ được thì vẫn phải báo pin
                        logger.warning("Không hạ được độ sáng khi pin yếu: %s", e)
                _say(synth, bus, cau, "sad", proactive=True)
                bus.emit(state="idle", proactive=True)

            proactive_dispatcher.submit(Intervention(
                kind="battery_alert", scope="global", present=present_battery_alert,
                cancel=(lambda: synth.stop()) if synth is not None else None))

        monitor = ProactiveMonitor(on_brief=_on_brief, on_battery=_on_battery,
                                   brief_time=(_bh, _bm),
                                   battery_threshold=config.BATTERY_ALERT_THRESHOLD)

    voice_io = _make_voice_input()

    worker = threading.Thread(target=_assistant_loop,
                              args=(agent, bus, synth, voice_io, routines, fast_match,
                                    intervention_gate, voice_turn,
                                    (salm.try_care_response if salm is not None else None),
                                    (salm.try_style_command if salm is not None else None),
                                    (salm.try_late_night_command
                                     if salm is not None else None)),
                              kwargs={"camera": camera, "stop_event": app_closing},
                              daemon=True)

    # Persona bật -> tâm trạng dẫn khuôn mặt: tắt tự reset về neutral (emotion_hold_ms=0).
    # Bấm một thẻ trên panel = gọi đúng tool `open_place_result`, không dựng đường mở
    # thứ hai. Panel chỉ là bề mặt hiển thị, luật nằm ở tool.
    def _open_place_from_panel(index):
        try:
            agent.registry.run("open_place_result", {"index": index})
        except Exception as e:
            print(f"(không mở được chỗ số {index}: {e})")

    # Bấm một thư trên panel danh sách = đúng tool `show_email`, để bấm và nói ("mở thư thứ
    # hai") đi chung một đường. Tool không có (chưa bật MCP) thì bỏ qua lặng lẽ — panel
    # thư cũng không bao giờ hiện ra trong trường hợp đó.
    def _open_mail_from_panel(index):
        if not agent.registry.has("show_email"):
            return
        try:
            agent.registry.run("show_email", {"index": index})
        except Exception as e:
            print(f"(không mở được thư số {index}: {e})")

    # Bấm Gửi/Huỷ trên panel nháp = ĐÚNG đường xác nhận bằng giọng (agent.confirm_pending),
    # không dựng đường gửi thứ hai. Chạy trên main thread Tk nên phải lấy _AGENT_LOCK để
    # không đụng agent.run của vòng lặp nền; lấy không được thì nói ra chứ không im lặng
    # nuốt cú bấm — người dùng sẽ tưởng đã gửi.
    def _decide_draft(decision):
        if not _AGENT_LOCK.acquire(timeout=5):
            _say(synth, bus, "Tôi đang bận một việc khác, bạn bấm lại giúp tôi nhé.", "sad")
            return
        try:
            result = agent.confirm_pending(decision)
        except Exception as e:
            logger.error("Lỗi khi chốt bản nháp: %s", e)
            result = "Xin lỗi, tôi gặp lỗi khi gửi."
        finally:
            _AGENT_LOCK.release()
        if result:
            _say(synth, bus, result, "happy" if decision == "yes" else "neutral")
            bus.emit(state="idle")

    _gesture_speech_lock = threading.Lock()

    def _present_visual_result(result, modality, label, decision):
        pose = "happy" if decision == "yes" else "neutral"

        def present_result():
            try:
                def speak():
                    _say(synth, bus, result, pose)
                    bus.emit(state="idle")

                if voice_io:
                    token = ("visual_confirmation", time.monotonic())
                    if not voice_turn.present(token, speak):
                        bus.emit(text=result, emotion=pose)
                else:
                    speak()
            finally:
                _gesture_speech_lock.release()

        if _gesture_speech_lock.acquire(blocking=False):
            threading.Thread(target=present_result,
                             name="alice-visual-response", daemon=True).start()
        else:
            bus.emit(text=result, emotion=pose)

    def _visual_input_allowed():
        if (app_closing.is_set() or camera is None or
                camera.camera_role != "workstation_facing" or
                not camera.visual_input_active()):
            return False
        state = intervention_gate.snapshot()
        return (not state.session_locked and
                getattr(state.presence, "value", state.presence) != "suspended" and
                getattr(state.display, "value", state.display) != "off")

    visual_arbiter = VisualConfirmationArbiter(
        agent, _AGENT_LOCK, on_result=_present_visual_result,
        debug=emit_debug_if_enabled,
        conflict_window=(0.8 if config.CAMERA_HEAD_CONFIRMATION_ENABLED else 0.4),
        is_active=_visual_input_allowed)

    def _on_camera_gesture(label, pose_started_at):
        if label not in ("ok", "thumbs_up") or not _visual_input_allowed():
            return
        if label == "thumbs_up" and _AGENT_LOCK.acquire(timeout=1):
            try:
                if agent.mood is not None:
                    agent.mood.update(user_valence=1.0, outcome=0.0, fluster=0.45)
                    bus.emit(emotion=agent.mood.to_pose())
                else:
                    bus.emit(emotion="happy")
            finally:
                _AGENT_LOCK.release()
        queued = visual_arbiter.submit("hand", "yes", pose_started_at, label)
        bus.emit_debug("camera", "Hand gesture observed", {
            "gesture": label, "confirmation_candidate": queued,
            "compliment": label == "thumbs_up"})

    def _on_head_motion(label, pose_started_at):
        visual_arbiter.submit("head", label, pose_started_at, label)

    if camera is not None:
        camera.set_gesture_handler(_on_camera_gesture)
        camera.set_visual_cancel_handler(visual_arbiter.cancel)
        if (config.CAMERA_HEAD_CONFIRMATION_ENABLED and
                camera.camera_role == "workstation_facing"):
            camera.set_head_handler(_on_head_motion)

    def _apply_control(key, enabled):
        nonlocal debug_log_handler
        if key == "DEBUG_PANEL_ENABLED":
            if enabled:
                bus.set_debug_enabled(True)
                debug_state.set()
                try:
                    if debug_log_handler is None:
                        from utils.debug import install_bus_log_handler
                        debug_log_handler = install_bus_log_handler(bus)
                    win.set_debug_enabled(True)
                except Exception:
                    debug_state.clear()
                    bus.set_debug_enabled(False)
                    if debug_log_handler is not None:
                        from utils.debug import uninstall_bus_log_handler
                        uninstall_bus_log_handler(debug_log_handler)
                        debug_log_handler = None
                    raise
                emit_debug_if_enabled("system", "Bật bảng chẩn đoán")
            else:
                win.set_debug_enabled(False)
                debug_state.clear()
                bus.set_debug_enabled(False)
                if debug_log_handler is not None:
                    from utils.debug import uninstall_bus_log_handler
                    uninstall_bus_log_handler(debug_log_handler)
                    debug_log_handler = None
        elif key == "CAMERA_ENABLED":
            if enabled:
                camera.start()
                camera.resume()
            else:
                camera.pause()
        elif key == "CAMERA_FACE_ENABLED":
            camera.set_face_enabled(enabled)
        elif key == "CAMERA_GESTURE_ENABLED":
            camera.set_gesture_enabled(enabled)
        elif key == "CAMERA_HEAD_CONFIRMATION_ENABLED":
            if enabled and camera.camera_role != "workstation_facing":
                raise RuntimeError("Xác nhận bằng đầu cần webcam hướng về người dùng")
            camera.set_head_handler(_on_head_motion if enabled else None)
        elif key == "CAMERA_EMOTION_ENABLED":
            camera.set_emotion_control_visible(True)
            camera.set_emotion_enabled(enabled)
        elif key == "feature.schedule":
            (scheduler.start if enabled else scheduler.stop)()

    system_controls = SystemControls(report, camera, apply_live=_apply_control, iot=iot_client)
    restart_requested = threading.Event()

    def _restart_from_control():
        if agent.pending is not None or _AGENT_LOCK.locked():
            raise RuntimeError("Hãy hoàn tất hoặc hủy yêu cầu hiện tại trước khi khởi động lại")
        restart_requested.set()
        app_closing.set()
        if synth is not None:
            synth.stop()
        win.root.quit()

    def _care_style_from_panel(action):
        if action == "reset" and salm is not None:
            salm.reset_care_style()

    def _activity_from_panel(request):
        if activity_insights is None:
            return None
        period = request.get("period", "7_days")
        view = request.get("view", "overview")
        try:
            result = activity_insights.apply_setting(
                request.get("action"), app_id=request.get("app_id"),
                category=request.get("category"))
            snapshot = activity_insights.snapshot(period, view)
            preference = result.get("preference") or {}
            app_name = display_app_name(preference.get("app_id"))
            notices = {
                "classify": f"Đã cập nhật nhóm cho {app_name}.",
                "exclude": f"Đã loại {app_name} khỏi thống kê.",
                "include": f"Đã đưa {app_name} lại vào thống kê.",
                "reset": f"Đã đặt lại phân loại của {app_name}.",
            }
            snapshot["preference_notice"] = notices.get(result.get("action"),
                                                         "Đã cập nhật.")
            bus.emit_debug("activity", "Cập nhật phân loại ứng dụng", result,
                           level="SUCCESS")
            return snapshot
        except Exception as exc:
            logger.error("Không cập nhật được Activity Insights: %s", exc)
            try:
                snapshot = activity_insights.snapshot(period, view)
            except Exception:
                snapshot = {
                    "period": period, "view": view, "range": {}, "totals": {},
                    "top_apps": [], "trend": [], "classification_apps": [],
                    "data_quality": {"valid_days": 0},
                }
            snapshot["preference_error"] = f"Không lưu được thay đổi: {exc}"
            bus.emit_debug("activity", "Không cập nhật được phân loại ứng dụng",
                           {"error": f"{type(exc).__name__}: {exc}"}, level="ERROR")
            return snapshot

    win = AvatarWindow(bus=bus, title="Trợ lý AI",
                       emotion_hold_ms=0 if config.PERSONA_ENABLED else None,
                       on_open_place=_open_place_from_panel,
                       on_draft_decision=_decide_draft,
                       on_open_mail=_open_mail_from_panel,
                       on_care_style_action=_care_style_from_panel,
                       on_activity_action=_activity_from_panel,
                       debug_panel=debug_enabled, camera_service=camera,
                       system_controls=system_controls, on_restart=_restart_from_control)
    camera.set_face_enabled(config.CAMERA_FACE_ENABLED)
    camera.set_gesture_enabled(config.CAMERA_GESTURE_ENABLED)
    if config.CAMERA_EMOTION_ENABLED:
        camera.set_emotion_control_visible(True)
        camera.set_emotion_enabled(True)
    if camera is not None and config.CAMERA_ENABLED:
        camera.start()
    else:
        camera.pause()
    system_controls.start()

    def start_background_and_input():
        # Chỉ mở các producer khác và micro SAU câu chào khởi động. Nếu không, brief
        # buổi sáng có thể chen trước hoặc mic thu lại chính giọng của trợ lý.
        if app_closing.is_set():
            return
        try:
            if controls.get("feature.schedule", True):
                scheduler.start()
        except Exception:
            logger.warning("Không khởi động được scheduler", exc_info=True)
        if iot_voice_alerts is not None:
            iot_voice_alerts.start()
        if monitor is not None:
            try:
                monitor.start()
            except Exception:
                logger.warning("Không khởi động được proactive monitor", exc_info=True)
        worker.start()  # greeting/producer phụ lỗi vẫn không được chặn input chính

    if config.STARTUP_GREETING_ENABLED:
        win.root.after(250, lambda: _start_with_greeting(
            proactive_dispatcher, synth, bus, start_background_and_input,
            welcome_dialogue=welcome_dialogue))
    else:
        win.root.after(250, start_background_and_input)
    try:
        win.run()          # Tk mainloop (main thread) — chặn tới khi đóng cửa sổ
    finally:
        app_closing.set()
        # Trích nốt điều đáng nhớ TRƯỚC khi tắt: phiên ngắn thì đệm củng cố không bao giờ
        # đầy, không có bước này là mọi thứ vừa nghe được bay sạch (xem Agent.flush_memory).
        try:
            agent.flush_memory()
        except Exception as e:
            logger.warning("Không củng cố được trí nhớ lúc đóng phiên: %s", e)
        scheduler.stop()
        system_controls.stop()
        if iot_voice_alerts is not None:
            iot_voice_alerts.stop()
        if camera is not None:
            camera.stop()
        if monitor is not None:
            monitor.stop()
        if mcp is not None:
            mcp.stop()
        if salm is not None:
            salm.stop()
        proactive_dispatcher.stop()
        if browser is not None:
            browser.stop()
        if debug_log_handler is not None:
            from utils.debug import uninstall_bus_log_handler
            uninstall_bus_log_handler(debug_log_handler)

    if restart_requested.is_set():
        import os
        import subprocess
        subprocess.Popen([sys.executable, *sys.argv], cwd=os.getcwd(),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


if __name__ == "__main__":
    main()
