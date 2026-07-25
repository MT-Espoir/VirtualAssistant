"""
Trợ lý AI kèm avatar cảm xúc (Tkinter).

- Cửa sổ avatar chạy trên main thread; agent chạy ở thread nền, gõ lệnh ở terminal.
- Agent phát trạng thái (thinking/speaking/idle) + cảm xúc cho avatar qua AssistantBus.

Chạy:  cd src && python avatar_app.py   (cần Ollama đang chạy để agent hoạt động)
Chỉ xem avatar (không cần Ollama):  python ui/avatar.py
"""

import threading

from core.agent import Agent
from core.actions_facade import AssistantActions
from core.tools import build_default_registry
from core.llm_client import build_default_llm_client
from core.events import AssistantBus
from services.scheduler import ReminderScheduler
from ui.avatar import AvatarWindow
from ui.avatar_face import guess_emotion
from utils.logger import get_logger

logger = get_logger(__name__)


def _assistant_loop(agent, bus, speak=None):
    """Vòng nhập lệnh (thread nền): gõ text -> agent -> phát trạng thái cho avatar."""
    bus.emit(state="idle", emotion="neutral", text="Gõ yêu cầu ở cửa sổ terminal.")
    while True:
        try:
            text = input("Bạn: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in ("thoát", "exit", "quit"):
            break

        bus.emit(state="thinking", text="")
        try:
            response = agent.run(text)
        except Exception as e:
            logger.error("Lỗi khi chạy agent: %s", e)
            response = "Xin lỗi, có lỗi khi xử lý yêu cầu."

        bus.emit(state="speaking", emotion=guess_emotion(response), text=response)
        if speak:
            speak(response)
        bus.emit(state="idle")
        print(f"Trợ lý: {response}\n")


def _make_speaker():
    """Tạo hàm nói (TTS) nếu có; lỗi thì bỏ qua (avatar vẫn chạy)."""
    try:
        from audio.speech_synthesizer import SpeechSynthesizer
        from utils.config import config
        synth = SpeechSynthesizer(engine=config.TTS_ENGINE, language=config.TTS_LANGUAGE)
        return synth.speak
    except Exception as e:
        logger.warning("TTS không khả dụng (%s) — chạy không có giọng nói.", e)
        return None


def main():
    bus = AssistantBus()

    try:
        llm = build_default_llm_client()
    except RuntimeError as e:
        print(f"Không khởi tạo được LLM: {e}")
        return

    scheduler = ReminderScheduler(
        notify=lambda msg: bus.emit(state="speaking", emotion="happy", text=f"🔔 {msg}"))
    scheduler.start()

    agent = Agent(llm=llm,
                  registry=build_default_registry(AssistantActions(), scheduler=scheduler))

    speak = _make_speaker()
    worker = threading.Thread(target=_assistant_loop, args=(agent, bus, speak), daemon=True)
    worker.start()

    win = AvatarWindow(bus=bus, title="Trợ lý AI")
    try:
        win.run()          # Tk mainloop (main thread) — chặn tới khi đóng cửa sổ
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
