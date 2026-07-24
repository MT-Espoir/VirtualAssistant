"""
Điểm vào của trợ lý ảo — lớp I/O (micro/loa) quanh Agent tool-calling.

Luồng: ghi âm -> nhận dạng giọng nói (STT) -> Agent (LLM tự gọi tool) -> nói lại.
Toàn bộ "hiểu lệnh -> hành động" nằm ở core.agent.Agent (LLM + tools), tách khỏi
phần cứng và tách khỏi nhà cung cấp LLM. Xem docs/ARCHITECTURE.md.

Cần: cài 'anthropic' và đặt ANTHROPIC_API_KEY (xem .env.example). Muốn thử nhanh
bằng bàn phím, không cần micro: chạy `python agent_cli.py`.
"""

import time
import numpy as np

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
    print("\n🎤 Recognized:", text)
    try:
        response = agent.run(text)
    except Exception as e:  # lỗi mạng/LLM không được làm sập vòng lặp
        logger.error("Lỗi khi chạy agent: %s", e)
        response = "Xin lỗi, có lỗi khi xử lý yêu cầu."
    print(f"✅ Response: {response}")
    speech_synthesizer.speak(response)


def main():
    sample_rate = config.SAMPLE_RATE

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
        rate=sample_rate,
        chunk=config.CHUNK_SIZE,
        speech_threshold_ratio=config.SPEECH_THRESHOLD_RATIO,
    )

    welcome = "Xin chào! Tôi là trợ lý ảo của bạn. Tôi đang lắng nghe."
    print(f"\n{welcome}")
    speech_synthesizer.speak(welcome)

    try:
        while True:
            print("\n--- Listening for command... ---")
            recorder.start_recording()

            speech_detected = False
            max_duration = 100
            silence_counter = 0
            speech_level_detected = 0

            for i in range(max_duration):
                if recorder.stream:
                    try:
                        data = recorder.stream.read(recorder.chunk)
                        recorder.frames.append(data)

                        if i % 30 == 0:
                            audio_data = np.frombuffer(data, dtype=np.int16)
                            level = np.sqrt(np.mean(np.square(audio_data)))
                            speech_level_detected = max(speech_level_detected, level)

                        if not recorder.is_silent(data):
                            if not speech_detected:
                                print("Speech detected!")
                            speech_detected = True
                            silence_counter = 0
                        elif speech_detected:
                            silence_counter += 1

                        if speech_detected and silence_counter > 15:
                            print("End of speech detected")
                            break

                    except (IOError, OSError) as e:
                        logger.error("Error reading audio: %s", e)
                        break

                time.sleep(0.1)

            if speech_detected:
                print(f"Processing speech... (max level: {speech_level_detected:.0f})")
                audio_data = recorder.get_audio_data()

                if audio_data:
                    text = recognizer.recognize_speech_from_data(audio_data)
                    if text and not text.startswith("Could not understand"):
                        handle_recognized_text(agent, text)
                    else:
                        print("\nCouldn't understand speech")
            else:
                print(f"No significant speech detected (max level: {speech_level_detected:.0f})")

            recorder.reset()

    except KeyboardInterrupt:
        print("\nStopping voice assistant...")
        recorder.close()
        print("Program terminated.")


if __name__ == "__main__":
    main()
