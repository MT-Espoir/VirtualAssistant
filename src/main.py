"""
Điểm vào của trợ lý ảo — chỉ chịu trách nhiệm phần I/O (micro/loa) và vòng lặp.

Toàn bộ logic "hiểu lệnh -> hành động" nằm ở core.command_router.CommandRouter,
tách khỏi phần cứng để có thể unit test (xem tests/test_command_router.py).
"""

import time
import numpy as np
from datetime import datetime

# I/O
from audio.recorder import Recorder
from audio.speech_synthesizer import SpeechSynthesizer
from recognition.speech_recognizer import SpeechRecognizer

# NLP & hội thoại
from nlp.nlp_model import NLPProcessor
from llm.conversation_engine import ConversationEngine

# "Bộ não" (tách khỏi I/O)
from core.command_router import CommandRouter
from core.actions_facade import AssistantActions

# Người dùng & phản hồi
from components.user.user_profile import UserProfile
from components.feedback.feedback_collector import FeedbackCollector

# Cấu hình tập trung & logging
from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)

# --- Khởi tạo các thành phần dùng chung ---
nlp_processor = NLPProcessor()
conversation_engine = ConversationEngine()
user_profile = UserProfile()
feedback_collector = FeedbackCollector()
speech_synthesizer = SpeechSynthesizer(engine=config.TTS_ENGINE, language=config.TTS_LANGUAGE)

# Router: nhận text -> trả response (không phụ thuộc micro/loa)
router = CommandRouter(
    nlp_processor=nlp_processor,
    conversation_engine=conversation_engine,
    actions=AssistantActions(),
    user_profile=user_profile,
)


def _maybe_collect_feedback(text):
    """Hỏi mức hài lòng sau mỗi 10 lệnh (không làm phiền liên tục)."""
    daily = user_profile.profile.get("daily_stats", {})
    today = daily.get(datetime.now().strftime("%Y-%m-%d"), {})
    command_count = today.get("total_commands", 0)

    if command_count % 10 != 0:
        return

    print("\nBạn có hài lòng với kết quả không? (1-5, 5 là rất hài lòng)")
    try:
        satisfaction = int(input().strip())
        feedback_collector.collect_feedback(
            command_text=text,
            predicted_intent=nlp_processor.classify_intent(text),
            satisfaction_score=satisfaction,
        )
    except (ValueError, EOFError):
        logger.debug("Bỏ qua thu thập phản hồi (input không hợp lệ)")


def handle_recognized_text(text):
    """Xử lý một câu đã nhận dạng: định tuyến -> nói phản hồi -> hỏi feedback."""
    print("\n🎤 Recognized:", text)
    response = router.route_multi(text)
    print(f"✅ Response: {response}")
    speech_synthesizer.speak(response)
    _maybe_collect_feedback(text)


def main():
    sample_rate = config.SAMPLE_RATE

    print("=== Voice Control Assistant ===")
    print("This program will control your computer with voice commands")
    print("The AI will respond to your commands with voice feedback")

    recognizer = SpeechRecognizer(language=config.STT_LANGUAGE, engine=config.STT_ENGINE)
    recorder = Recorder(
        channels=config.CHANNELS,
        rate=sample_rate,
        chunk=config.CHUNK_SIZE,
        speech_threshold_ratio=config.SPEECH_THRESHOLD_RATIO,
    )

    welcome_message = "Xin chào! Tôi là trợ lý ảo của bạn. Tôi đang lắng nghe lệnh của bạn."
    print(f"\nTesting voice synthesis: '{welcome_message}'")
    speech_synthesizer.speak(welcome_message)

    print("\nVoice recognition started. Speak your command directly.")
    print("Press Ctrl+C to exit the program.")

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
                        handle_recognized_text(text)
                    else:
                        print("\nCouldn't understand speech")
            else:
                print(f"No significant speech detected (max level: {speech_level_detected:.0f})")

            recorder.reset()

    except KeyboardInterrupt:
        print("\nStopping voice assistant...")
        recorder.close()
        print("Program terminated.")


# --- Tiện ích quản lý hội thoại (dùng khi debug/tương tác) ---

def get_conversation_status():
    summary = conversation_engine.get_conversation_summary()
    print("Conversation Status:")
    print(f"- History length: {summary['history_length']}")
    print(f"- Conversation mode: {summary['current_context']['conversation_mode']}")
    print(f"- Current topic: {summary['current_context']['topic']}")
    print(f"- LLM available: {summary['llm_available']}")
    print(f"- Last activity: {summary['last_activity']}")
    return summary


def toggle_conversation_mode():
    current_mode = conversation_engine.current_context.get("conversation_mode", False)
    conversation_engine.set_conversation_mode(not current_mode)
    return not current_mode


def clear_conversation_context():
    conversation_engine.clear_context()
    print("Conversation context cleared")


def test_conversation_system():
    """Chạy thử router với vài câu mẫu."""
    for test_input in ["xin chào", "bạn có khỏe không", "mở chrome", "cảm ơn", "tạm biệt"]:
        print(f"\nInput: {test_input}")
        print(f"Response: {router.route(test_input)}")


if __name__ == "__main__":
    main()
