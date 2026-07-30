"""
Điểm vào của trợ lý ảo — lớp I/O (micro/loa) quanh Agent tool-calling.

Luồng: ghi âm (recorder.listen_once) -> nhận dạng giọng nói (STT) -> Agent (LLM tự
gọi tool) -> nói lại. Toàn bộ "hiểu lệnh -> hành động" nằm ở agent.agent.Agent,
tách khỏi phần cứng và khỏi nhà cung cấp LLM. Xem docs/ARCHITECTURE.md.
"""

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

# I/O
from voice.recorder import Recorder
from voice.speech_synthesizer import SpeechSynthesizer
from voice.speech_recognizer import SpeechRecognizer

# Agent core (LLM tool-calling)
from agent.agent import Agent
from agent.actions_facade import AssistantActions
from agent.tools import build_default_registry
from llm.client import build_default_llm_client
from services.scheduler import ReminderScheduler

# Cấu hình tập trung & logging
from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)

# TTS luôn dùng được (không phụ thuộc LLM)
speech_synthesizer = SpeechSynthesizer(
    engine=config.TTS_ENGINE, language=config.TTS_LANGUAGE,
    robot=config.TTS_ROBOT, robot_carrier=config.TTS_ROBOT_CARRIER,
    speed=config.TTS_SPEED)


def _notify_reminder(message):
    """Callback khi tới giờ nhắc: hiện màn hình + nói."""
    print(f"\n🔔 Nhắc: {message}")
    speech_synthesizer.speak(f"Nhắc bạn: {message}")


def build_agent(scheduler):
    """Dựng Agent; trả về None nếu chưa cấu hình được LLM (thiếu SDK/API key)."""
    try:
        llm = build_default_llm_client()
    except RuntimeError as e:
        logger.error("Không khởi tạo được LLM: %s", e)
        return None
    registry = build_default_registry(AssistantActions(), scheduler=scheduler)
    return Agent(llm=llm, registry=registry,
                 max_history_turns=config.MAX_HISTORY_TURNS,
                 memory_path=config.MEMORY_PATH or None)


def handle_recognized_text(agent, text):
    """Xử lý một câu đã nhận dạng: agent -> nói phản hồi."""
    print("\n🎤 Đã nghe:", text)
    try:
        response = agent.run(text).text
    except Exception as e:  # lỗi mạng/LLM không được làm sập vòng lặp
        logger.error("Lỗi khi chạy agent: %s", e)
        response = "Xin lỗi, có lỗi khi xử lý yêu cầu."
    print(f"✅ Trả lời: {response}")
    speech_synthesizer.speak(response)


def main():
    print("=== Trợ lý AI điều khiển máy tính (agent) ===")
    print("Nói yêu cầu bằng tiếng Việt. Nhấn Ctrl+C để thoát.")

    scheduler = ReminderScheduler(notify=_notify_reminder)
    scheduler.start()

    agent = build_agent(scheduler)
    if agent is None:
        print("\n⚠ Chưa cấu hình được LLM. Với Ollama: cài app Ollama + "
              "`ollama pull qwen2.5:3b-instruct`. Với Claude: đặt ANTHROPIC_API_KEY. "
              "Xem .env.example. Tạm dừng.")
        scheduler.stop()
        return

    recognizer = SpeechRecognizer(language=config.STT_LANGUAGE, engine=config.STT_ENGINE)
    recorder = Recorder(
        channels=config.CHANNELS,
        rate=config.SAMPLE_RATE,
        chunk=config.CHUNK_SIZE,
        speech_threshold_ratio=config.SPEECH_THRESHOLD_RATIO,
    )

    welcome = "Xin chào! Tôi là trợ lý ảo của bạn. Tôi đang lắng nghe."
    print(f"\n{welcome}")
    speech_synthesizer.speak(welcome)

    try:
        while True:
            print("\n--- Đang lắng nghe... ---")
            audio_data = recorder.listen_once()

            if audio_data is None:
                print("Không phát hiện giọng nói.")
            else:
                text = recognizer.recognize_speech_from_data(audio_data)
                if text:
                    handle_recognized_text(agent, text)
                else:
                    print("Không nghe rõ, vui lòng thử lại.")

            recorder.reset()

    except KeyboardInterrupt:
        print("\nĐang dừng trợ lý...")
        scheduler.stop()
        recorder.close()
        print("Đã thoát.")


if __name__ == "__main__":
    main()
