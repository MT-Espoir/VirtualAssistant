"""
Điểm vào của trợ lý ảo — lớp I/O (micro/loa) quanh Agent tool-calling.

Luồng: ghi âm (recorder.listen_once) -> nhận dạng giọng nói (STT) -> Agent (LLM tự
gọi tool) -> nói lại. Toàn bộ "hiểu lệnh -> hành động" nằm ở core.agent.Agent,
tách khỏi phần cứng và khỏi nhà cung cấp LLM. Xem docs/ARCHITECTURE.md.

Cần: cài 'anthropic' và đặt ANTHROPIC_API_KEY (xem .env.example). Muốn thử nhanh
bằng bàn phím, không cần micro: chạy `python agent_cli.py`.
"""

# I/O
from audio.recorder import Recorder
from audio.speech_synthesizer import SpeechSynthesizer
from recognition.speech_recognizer import SpeechRecognizer

# Agent core (LLM tool-calling)
from core.agent import Agent
from core.actions_facade import AssistantActions
from core.tools import build_default_registry
from core.llm_client import build_default_llm_client

# Cấu hình tập trung & logging
from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)

# TTS luôn dùng được (không phụ thuộc LLM)
speech_synthesizer = SpeechSynthesizer(engine=config.TTS_ENGINE, language=config.TTS_LANGUAGE)


def build_agent():
    """Dựng Agent; trả về None nếu chưa cấu hình được LLM (thiếu SDK/API key)."""
    try:
        llm = build_default_llm_client()
    except RuntimeError as e:
        logger.error("Không khởi tạo được LLM: %s", e)
        return None
    return Agent(llm=llm, registry=build_default_registry(AssistantActions()))


def handle_recognized_text(agent, text):
    """Xử lý một câu đã nhận dạng: agent -> nói phản hồi."""
    print("\n🎤 Đã nghe:", text)
    try:
        response = agent.run(text)
    except Exception as e:  # lỗi mạng/LLM không được làm sập vòng lặp
        logger.error("Lỗi khi chạy agent: %s", e)
        response = "Xin lỗi, có lỗi khi xử lý yêu cầu."
    print(f"✅ Trả lời: {response}")
    speech_synthesizer.speak(response)


def main():
    print("=== Trợ lý AI điều khiển máy tính (agent) ===")
    print("Nói yêu cầu bằng tiếng Việt. Nhấn Ctrl+C để thoát.")

    agent = build_agent()
    if agent is None:
        print("\n⚠ Chưa cấu hình được LLM. Hãy `pip install anthropic` và đặt "
              "ANTHROPIC_API_KEY (xem .env.example). Tạm dừng.")
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
        recorder.close()
        print("Đã thoát.")


if __name__ == "__main__":
    main()
