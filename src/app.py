"""
Điểm vào hợp nhất — khởi chạy toàn bộ hệ thống trong một lần:
agent (LLM tool-calling) + avatar cảm xúc (Tkinter) + TTS (kèm giọng robot
tùy chọn) + lịch nhắc (scheduler). Đầu vào dùng micro nếu có, tự động chuyển
sang gõ phím nếu không có/lỗi (xem INPUT_MODE trong .env.example).

Chạy:  cd src && python app.py
"""

import threading
import time

from agent.agent import Agent
from agent.actions_facade import AssistantActions
from features.contract import FeatureContext
from features.registry import build_registry
from features.places.service import PlacesService
from services.location import LocationStore
from memory.profile import UserProfile
from agent.persona import PersonaState, MoodState
from services.tasks import TaskStore
from services.routines import RoutineStore
from services.contacts import ContactStore
from services.proactive import ProactiveMonitor
from services.mcp_bridge import MCPClient
from llm.client import build_default_llm_client
from utils.events import AssistantBus
from voice.wake_word import match_wake_word, parse_wake_words, wake_words_not_in
from voice.fast_commands import (match_fast_command, match_avatar_command,
                                 match_mode_command, match_confirmation,
                                 match_persona_command, match_routine_command)
from services.scheduler import ReminderScheduler
from ui.avatar import AvatarWindow
from ui.avatar_face import guess_emotion
from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)
_NO_INPUT = object()
MAX_INPUT_FAILS = 5
SPEAK_TAIL_GUARD_S = 0.4

def _make_speaker():
    """Tạo bộ tổng hợp giọng nói (TTS); lỗi thì trả None (hệ thống vẫn chạy, mất giọng)."""
    try:
        from voice.speech_synthesizer import SpeechSynthesizer
        return SpeechSynthesizer(
            engine=config.TTS_ENGINE, language=config.TTS_LANGUAGE,
            robot=config.TTS_ROBOT, robot_carrier=config.TTS_ROBOT_CARRIER,
            speed=config.TTS_SPEED)
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
            max_utterance_s=config.MAX_UTTERANCE_SECONDS)
        recognizer = SpeechRecognizer(language=config.STT_LANGUAGE, engine=config.STT_ENGINE)
        return recorder, recognizer
    except Exception as e:
        if config.INPUT_MODE == "voice":
            raise
        logger.warning("Không dùng được micro (%s) — chuyển sang gõ phím.", e)
        return None


def _say(synth, bus, text, emotion):
    """Phát trạng thái 'speaking' rồi NÓI ĐỒNG BỘ — chặn tới khi phát xong.

    Đây là chốt chặn half-duplex: vì hàm chạy trong chính thread của vòng nghe và
    speak_sync() chặn tới khi loa im, mic sẽ KHÔNG mở lại giữa lúc AI đang nói —
    loại bỏ vòng vọng âm (AI tự nghe lại giọng mình rồi tự trả lời).
    """
    bus.emit(state="speaking", emotion=emotion, text=text)
    if synth:
        try:
            synth.speak_sync(text)     # chặn tới khi phát xong
        except Exception as e:
            logger.error("Lỗi khi phát giọng nói: %s", e)


def _flush_mic_after_speaking(recorder):
    """Sau khi AI nói xong: đọc-bỏ mic trong lúc đuôi âm loa tắt (vừa lọc vọng âm
    vừa làm nóng phần cứng mic sớm) rồi làm mới recorder trước khi nghe lại."""
    recorder.drain(SPEAK_TAIL_GUARD_S)
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
    bus.emit(state="speaking", emotion=emotion, text=text)

    bargein_words = wake_words_not_in(text, wake_words)   # bỏ từ khoá trùng câu trả lời
    synth.speak(text)                                     # phát bất đồng bộ

    try:
        while _tts_active(synth):
            audio = recorder.listen_once(max_seconds=BARGE_IN_LISTEN_SECONDS)
            recorder.reset()
            if not _tts_active(synth):
                break                                    # TTS vừa xong -> thôi nghe
            if audio is None or not bargein_words:
                continue
            heard = recognizer.recognize_speech_from_data(audio)
            if not heard:
                continue
            matched, remainder = match_wake_word(heard, bargein_words)
            if matched:
                synth.stop()                             # ngắt lời AI ngay
                print(f"⏸ Ngắt lời (barge-in): {heard}")
                return remainder or None
    except Exception as e:
        logger.error("Lỗi khi nghe ngắt lời: %s", e)
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
    print(f"🎤 Đã nghe: {text}")
    return text


def _next_input(voice_io, bus):
    """Lấy câu tiếp theo từ micro (nếu có) hoặc bàn phím.

    Trả về None CHỈ khi người dùng muốn thoát (EOF/Ctrl+C); _NO_INPUT khi lượt
    này không có gì để xử lý nhưng vẫn tiếp tục.
    """
    if voice_io:
        recorder, recognizer = voice_io
        return _listen_voice(recorder, recognizer, bus)
    try:
        return input("Bạn: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None


# Tuần tự hoá agent.run: vòng lặp chính VÀ lịch (thread nền) đều dùng chung -> không bao
# giờ 2 agent.run chạy song song (tránh hỏng bộ nhớ ngắn hạn / tâm trạng).
_AGENT_LOCK = threading.Lock()


def _dispatch(agent, text, bus):
    """Xử lý MỘT câu lệnh -> (response, emotion). KHÔNG tự nói (người gọi lo phần NÓI).

    Cùng đường với lượt thường: fast-path giao diện/cuộn/chụp, hoặc agent. Tách ra để
    routine + lịch 'do' tái dùng ĐÚNG pipeline này.
    """
    bus.emit(state="thinking", text="")
    # Lệnh TOOL tất định (âm lượng/media/cuộn/chụp) ưu tiên TRƯỚC lệnh giao diện avatar:
    # cụm cỡ chữ chung ("to lên/nhỏ hơn") vừa là chỉnh avatar vừa xuất hiện trong "âm lượng
    # video to lên" -> phải để fast_command (đòi từ khoá đặc thù 'âm lượng') giành trước.
    fast = match_fast_command(text) if config.FAST_COMMANDS else None
    ui_cmd = match_avatar_command(text) if (config.FAST_COMMANDS and fast is None) else None
    if fast is not None and agent.registry.has(fast[0]):
        return _run_fast(agent, fast), "happy"
    if ui_cmd is not None:
        bus.emit_ui(**ui_cmd)
        print(f"⚡ (giao diện, không qua LLM) {ui_cmd}")
        return _ui_ack(ui_cmd), "happy"
    try:
        with _AGENT_LOCK:                       # chống 2 agent.run song song
            reply = agent.run(text)
        return reply.text, reply.emotion
    except Exception as e:
        logger.error("Lỗi khi chạy agent: %s", e)
        return "Xin lỗi, có lỗi khi xử lý yêu cầu.", "sad"


def _run_routine(agent, routines, name, bus, synth, voice_io):
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
            response, emotion = _dispatch(agent, step, bus)
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


def _assistant_loop(agent, bus, synth, voice_io, routines=None):
    """Vòng xử lý (thread nền): nghe/gõ -> agent -> phát trạng thái cho avatar + nói.

    Chu trình half-duplex nghiêm ngặt cho từng lượt: NGHE -> NGHĨ -> NÓI (chặn) ->
    lặng đệm -> mới NGHE lại. Không bao giờ nghe và nói cùng lúc.

    Khi nhập bằng giọng nói và bật REQUIRE_WAKE_WORD: chỉ hành động với câu có chứa
    từ khoá kích hoạt — bỏ qua lời nhạc/clip lọt vào mic (không tự trả lời loạn).
    """
    hint = "Đang lắng nghe micro..." if voice_io else "Gõ yêu cầu ở cửa sổ terminal."
    # Wake word chỉ áp dụng cho đầu vào giọng nói (gõ phím là chủ đích rõ ràng rồi).
    gate_wake = bool(voice_io) and config.REQUIRE_WAKE_WORD
    wake_words = parse_wake_words(config.WAKE_WORDS)
    # Barge-in cần: giọng nói + có TTS + có wake word để phân biệt câu ngắt lời.
    bargein = bool(voice_io) and synth is not None and gate_wake and bool(wake_words) \
        and config.BARGE_IN
    if gate_wake and wake_words:
        hint += f' (nói "{wake_words[0]}" trước yêu cầu; hoặc "chế độ làm việc" để khỏi cần gọi tên)'
    bus.emit(state="idle", emotion="neutral", text=hint)

    pending = None          # câu lệnh có sẵn từ barge-in -> bỏ qua bước NGHE ở đầu vòng
    # Chế độ làm việc: TẠM tắt wake word (ra lệnh trực tiếp, không cần gọi tên). Chỉ có
    # nghĩa khi wake word đang được dùng (gate_wake). Đổi bằng giọng nói, không lưu file.
    work_mode = False
    fails = 0
    while True:
        # 1) Lấy câu lệnh
        if pending is not None:
            text = pending
            pending = None
        else:
            try:
                raw = _next_input(voice_io, bus)
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
            if raw.lower() in ("thoát", "exit", "quit"):
                break

            # Đang CHỜ xác nhận một hành động khó hoàn tác + câu là 'có'/'không' -> nhận
            # trực tiếp, không cần gọi tên (đối thoại tự nhiên). Câu KHÁC vẫn cần wake word
            # nên không nới lỏng an toàn chung.
            awaiting_confirm = (agent.pending is not None
                                and match_confirmation(raw) is not None)

            # Chế độ làm việc TẮT wake word tạm thời -> khi bật, bỏ qua bước kiểm từ khoá.
            if gate_wake and not work_mode and not awaiting_confirm:
                matched, remainder = match_wake_word(raw, wake_words)
                if not matched:
                    print(f"(bỏ qua — không có từ khoá kích hoạt): {raw}")
                    bus.emit(state="idle")
                    continue
                if not remainder:               # chỉ gọi tên, chưa có yêu cầu cụ thể
                    _say(synth, bus, "Dạ, bạn cần gì?", "happy")
                    if voice_io:
                        _flush_mic_after_speaking(voice_io[0])
                    bus.emit(state="idle")
                    continue
                text = remainder
            else:
                text = raw

        # 1b) CHUYỂN CHẾ ĐỘ nghe (chỉ khi wake word đang được dùng): "chế độ làm việc"
        # tắt wake word để ra lệnh trực tiếp; "chế độ bình thường" bật lại.
        if gate_wake:
            mode = match_mode_command(text)
            if mode is not None:
                work_mode = (mode == "work")
                msg = ("Đã bật chế độ làm việc. Bạn ra lệnh trực tiếp, không cần gọi tên tôi nữa."
                       if work_mode else
                       "Đã trở lại chế độ bình thường. Hãy gọi tên tôi trước mỗi yêu cầu.")
                _say(synth, bus, msg, "happy")
                if voice_io:
                    _flush_mic_after_speaking(voice_io[0])
                bus.emit(state="idle")
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
                _say(synth, bus, pcmd["say"], "happy")
                if voice_io:
                    _flush_mic_after_speaking(voice_io[0])
                bus.emit(state="idle")
                continue

        # 1d) CHẠY ROUTINE bằng lời: "chạy routine X" -> lặp từng bước qua _dispatch.
        if routines is not None:
            rname = match_routine_command(text)
            if rname is not None:
                _run_routine(agent, routines, rname, bus, synth, voice_io)
                bus.emit(state="idle")
                continue

        # 2) NGHĨ — qua _dispatch (fast-path giao diện/cuộn/chụp, hoặc agent)
        response, emotion = _dispatch(agent, text, bus)

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
        bus.emit(state="idle")

    if voice_io:
        voice_io[0].close()
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
    """Câu xác nhận ngắn cho lệnh chỉnh giao diện avatar."""
    if ui.get("scale_delta", 0) < 0:
        return "Đã thu nhỏ khuôn mặt."
    if ui.get("scale_delta", 0) > 0:
        return "Đã phóng to khuôn mặt."
    if ui.get("opacity_delta", 0) < 0:
        return "Đã làm mờ hơn."
    if ui.get("opacity_delta", 0) > 0:
        return "Đã làm rõ hơn."
    return "Đã cập nhật giao diện."


def _run_fast(agent, fast):
    """Chạy thẳng một tool (fast-path), không qua LLM. Trả câu kết quả để nói."""
    tool_name, tool_args = fast
    try:
        out = str(agent.registry.run(tool_name, tool_args))
    except Exception as e:
        logger.error("Lỗi chạy nhanh %s: %s", tool_name, e)
        return "Xin lỗi, có lỗi khi thực hiện."
    print(f"⚡ (chạy nhanh, không qua LLM) {tool_name} → {out}")
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


def _run_scheduled(bus, synth, agent, message, kind):
    """Callback khi một mục lịch tới hạn. kind='do' -> THỰC THI lệnh qua _dispatch (có khoá
    trong _dispatch chống chạy song song vòng lặp chính); 'remind' -> chỉ đọc lời nhắc."""
    if kind == "do":
        print(f"\n⏰ Thực thi theo lịch: {message}")
        response, emotion = _dispatch(agent, message, bus)
        _say(synth, bus, response, emotion or guess_emotion(response))
    else:
        print(f"\n🔔 Nhắc: {message}")
        _say(synth, bus, _frame_reminder(message), "happy")
    bus.emit(state="idle")


def main():
    print("=== Trợ lý AI: agent + avatar + giọng nói (khởi chạy hợp nhất) ===")

    bus = AssistantBus()

    try:
        llm = build_default_llm_client()
    except RuntimeError as e:
        print(f"Không khởi tạo được LLM: {e}")
        return

    synth = _make_speaker()

    scheduler = ReminderScheduler()      # notify + start() đặt SAU khi có agent (lịch 'do' cần agent)

    browser = _make_browser_bridge()
    screen = _make_screen_controller()

    # MCP client (lịch/email qua server ngoài) — opt-in; cần server + OAuth do người dùng dựng.
    mcp = None
    if config.MCP_ENABLED and config.MCP_COMMAND:
        mcp = MCPClient(config.MCP_COMMAND, args=config.MCP_ARGS.split())
        if not mcp.start():
            logger.warning("MCP không kết nối được — bỏ qua (kiểm tra MCP_COMMAND/server/OAuth).")
            mcp = None

    # Router thu hẹp prompt+tool bằng 1 lượt LLM phân loại. Provider mạnh không cần (đo
    # được: bỏ router vẫn 100% chọn đúng tool, bớt 1 call/lượt) -> ROUTER_MODE=auto tắt.
    # Khi TẮT phải dùng prompt GỘP: không có ai chọn fragment theo case nữa, dùng base
    # trần sẽ mất sạch chỉ dẫn riêng (đọc nguyên văn kết quả web, tra danh bạ, ...).
    router, system_prompt = None, None
    if config.use_router():
        from agent.router import Router
        router = Router(llm, mcp_prefix=config.MCP_TOOL_PREFIX)
    else:
        from llm import prompts
        system_prompt = prompts.merged()
    logger.info("🧭 router: %s", "bật" if router else "tắt (prompt gộp)")

    profile = UserProfile(config.USER_PROFILE_PATH or None)
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

    persona = mood = None
    if config.PERSONA_ENABLED:
        persona = PersonaState(config.PERSONA_PATH or None, provider=config.LLM_PROVIDER)
        mood = MoodState(baseline_valence=persona.baseline_valence(),
                         baseline_arousal=persona.baseline_arousal())

    # Toàn bộ tool đến từ danh mục feature — xem `features/catalog.py`.
    actions = AssistantActions()
    feature_ctx = FeatureContext(actions=actions, bus=bus, browser=browser,
                                 contacts=contacts, location=location, mcp=mcp,
                                 places=places, profile=profile, routines=routines,
                                 scheduler=scheduler, screen=screen, tasks=tasks)
    registry, _ = build_registry(feature_ctx)

    agent = Agent(llm=llm,
                  registry=registry,
                  **({"system": system_prompt} if system_prompt else {}),
                  max_history_turns=config.MAX_HISTORY_TURNS,
                  memory_path=config.MEMORY_PATH or None, router=router, profile=profile,
                  auto_extract=config.LTM_AUTO_EXTRACT,
                  consolidate_every=config.LTM_CONSOLIDATE_EVERY,
                  persona=persona, mood=mood, auto_tune=config.PERSONA_AUTO_TUNE,
                  skip_respond_for_speakable=config.SKIP_RESPOND_FOR_SPEAKABLE,
                  # Hành động chờ xác nhận mà có nội dung đáng NHÌN (thân thư email) ->
                  # trưng lên panel thay vì bắt tai nghe TTS đọc cả lá thư.
                  on_pending=bus.emit_draft)

    # Giờ đã có agent -> nối callback lịch (remind đọc / do thực thi) rồi chạy scheduler.
    scheduler.notify = lambda msg, kind="remind": _run_scheduled(bus, synth, agent, msg, kind)
    scheduler.start()

    # Chủ động: bản tin sáng + theo dõi pin (vòng nền).
    monitor = None
    if config.PROACTIVE_ENABLED:
        try:
            _bh, _bm = (int(x) for x in config.MORNING_BRIEF_TIME.split(":"))
        except (ValueError, AttributeError):
            _bh, _bm = 7, 0

        def _on_brief():
            print("\n☀️ Bản tin sáng")
            _say(synth, bus, _compose_brief(profile, tasks), "happy")
            bus.emit(state="idle")

        def _on_battery(pct):
            _say(synth, bus, f"Pin còn khoảng {int(pct)} phần trăm, bạn nên cắm sạc nhé.", "sad")
            bus.emit(state="idle")

        monitor = ProactiveMonitor(on_brief=_on_brief, on_battery=_on_battery,
                                   brief_time=(_bh, _bm),
                                   battery_threshold=config.BATTERY_ALERT_THRESHOLD)
        monitor.start()

    voice_io = _make_voice_input()

    worker = threading.Thread(target=_assistant_loop,
                              args=(agent, bus, synth, voice_io, routines), daemon=True)
    worker.start()

    # Persona bật -> tâm trạng dẫn khuôn mặt: tắt tự reset về neutral (emotion_hold_ms=0).
    # Bấm một thẻ trên panel = gọi đúng tool `open_place_result`, không dựng đường mở
    # thứ hai. Panel chỉ là bề mặt hiển thị, luật nằm ở tool.
    def _open_place_from_panel(index):
        try:
            agent.registry.run("open_place_result", {"index": index})
        except Exception as e:
            print(f"(không mở được chỗ số {index}: {e})")

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

    win = AvatarWindow(bus=bus, title="Trợ lý AI",
                       emotion_hold_ms=0 if config.PERSONA_ENABLED else None,
                       on_open_place=_open_place_from_panel,
                       on_draft_decision=_decide_draft)
    try:
        win.run()          # Tk mainloop (main thread) — chặn tới khi đóng cửa sổ
    finally:
        scheduler.stop()
        if monitor is not None:
            monitor.stop()
        if mcp is not None:
            mcp.stop()
        if browser is not None:
            browser.stop()


if __name__ == "__main__":
    main()
