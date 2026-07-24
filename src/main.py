import time
import os
import threading
import numpy as np
import re
import nltk
from datetime import datetime
# Import speech recognition modules
from audio.recorder import Recorder
from recognition.speech_recognizer import SpeechRecognizer

# Import NLP modules
from nlp.entity_extractor import extract_entity
from nlp.nlp_model import NLPProcessor

# Import action modules
from actions.app_control import open_application, close_application
from actions.system_control import control_volume, control_brightness, system_shutdown, system_restart
from actions.web_search import search_web, open_website, search_and_play_youtube, search_and_play_youtube_direct, search_on_specific_site

# Thêm import cho hồ sơ người dùng
from components.user.user_profile import UserProfile

# Thêm import cho hệ thống phản hồi
from components.feedback.feedback_collector import FeedbackCollector

# Import speech synthesizer for voice feedback
from audio.speech_synthesizer import SpeechSynthesizer

# Import conversation engine for Phase 1
from llm.conversation_engine import ConversationEngine

# Khởi tạo bộ xử lý NLP
nlp_processor = NLPProcessor()

# Khởi tạo hồ sơ người dùng
user_profile = UserProfile()

# Khởi tạo thu thập phản hồi
feedback_collector = FeedbackCollector()

# Initialize speech synthesizer for voice feedback
speech_synthesizer = SpeechSynthesizer(engine="gtts", language="vi")

# Initialize conversation engine for Phase 1
conversation_engine = ConversationEngine()
speech_synthesizer = SpeechSynthesizer(engine="gtts", language="vi")

def execute_command(text):
    """Execute a command based on recognized speech - Updated for Phase 1"""
    # Convert to lowercase for easier processing
    text = text.lower()
    
    print(f"Processing command: '{text}'")
    
    # Phân loại ý định sử dụng mô hình NLP
    intent = nlp_processor.classify_intent(text)
    print(f"Detected intent: {intent}")
    
    # UPDATE FOR PHASE 1: Check if this is a conversation intent
    if conversation_engine.is_conversation_intent(intent):
        print(f"Handling conversation intent: {intent}")
        response = conversation_engine.generate_response(text, intent)
        
        # Update context for conversation mode
        if intent in ["greeting", "conversation", "small_talk"]:
            conversation_engine.set_conversation_mode(True)
        elif intent == "goodbye":
            conversation_engine.set_conversation_mode(False)
        
        return response
    
    # If not conversation intent, handle as command (existing logic)
    print(f"Handling command intent: {intent}")
    
    # Trích xuất thực thể dựa trên intent
    entities = {}
    
    if intent == "open_app":
        app_name = nlp_processor.extract_entities(text, intent_type="app_name")
        entities["app_name"] = app_name
        
    elif intent == "open_website":
        website_name = nlp_processor.extract_entities(text, intent_type="website_name")
        entities["website_name"] = website_name
    
    # Xử lý theo ý định
    if intent == "open_app":
        app_name = extract_entity(text, intent_type="app_name")
        if app_name:
            result = open_application(app_name)
            # Update conversation context with last command
            conversation_engine.update_context("last_command", f"open_app: {app_name}")
            return f"Opening {app_name}"
    
    elif intent == "close_app":
        app_name = extract_entity(text, intent_type="app_name")
        if app_name:
            result = close_application(app_name)
            return f"Closing {app_name}"
    
    elif intent == "system_volume":
        import re
        # Tìm số phần trăm trong lệnh (vd: "tăng 20%" hoặc "giảm 15%")
        percent_match = re.search(r'(\d+)(\s*)%', text)
        
        if "tăng" in text or "up" in text or "increase" in text:
            # Nếu có chỉ định phần trăm, ví dụ "tăng 20%"
            if percent_match:
                change_amount = int(percent_match.group(1))
                return control_volume(change=change_amount)
            else:
                return control_volume(change=10)
                
        elif "giảm" in text or "down" in text or "decrease" in text:
            # Nếu có chỉ định phần trăm, ví dụ "giảm 20%"
            if percent_match:
                change_amount = int(percent_match.group(1))
                return control_volume(change=-change_amount)  # Giảm nên là số âm
            # Mặc định giảm 10% nếu không chỉ định
            else:
                return control_volume(change=-10)
                
        else:
            # Nếu chỉ có số phần trăm mà không có "tăng/giảm", đặt âm lượng
            if percent_match:
                level = int(percent_match.group(1))
                return control_volume(level=level)
            # Trả về mức hiện tại nếu không có thông tin
            return control_volume(change=0)
    
    elif intent == "system_brightness":
        if "tăng" in text or "up" in text or "increase" in text:
            return control_brightness(change=10)
        elif "giảm" in text or "down" in text or "decrease" in text:
            return control_brightness(change=-10)
        else:
            import re
            percent_match = re.search(r'(\d+)(\s*)%', text)
            if percent_match:
                level = int(percent_match.group(1))
                return control_brightness(level=level)
            return control_brightness(change=0)
    
    elif intent == "system_shutdown":
        # Check if we should save work or just shutdown directly
        if "ngay lập tức" in text or "immediately" in text:
            return system_shutdown(close_apps=False)
        else:
            return system_shutdown(close_apps=True)
    
    elif intent == "system_restart":
        # Check if we should save work or just restart directly
        if "ngay lập tức" in text or "immediately" in text:
            return system_restart(close_apps=False)
        else:
            return system_restart(close_apps=True)
    
    elif intent == "open_website":
        website_name = extract_entity(text, intent_type="website_name")
        if website_name:
            return open_website(website_name)
        return "Không xác định được trang web cần mở"
    
    elif intent == "web_search":
        # Trích xuất truy vấn tìm kiếm
        search_query = text
        for keyword in ["search", "find", "look for", "tìm kiếm", "tìm", "google"]:
            search_query = search_query.replace(keyword, "").strip()
        
        engine = "google"
        if "youtube" in text:
            engine = "youtube"
        elif "bing" in text:
            engine = "bing"
            
        return search_web(search_query, engine)
    
    elif intent == "youtube_search":
        # Trích xuất truy vấn tìm kiếm từ lệnh
        search_query = text
        
        # Loại bỏ các từ khóa không cần thiết
        remove_words = ["tìm", "kiếm", "mở", "phát", "video", "bài hát", "nhạc", 
                      "trên", "youtube", "search", "play", "find", "song", "music"]
        
        for word in remove_words:
            search_query = search_query.replace(word, "").strip()
        
        # Nếu còn lại truy vấn tìm kiếm
        if search_query:
            try:
                # Thử sử dụng phương pháp trực tiếp nếu có pytube
                return search_and_play_youtube_direct(search_query)
            except:
                # Quay lại phương pháp cũ nếu phương pháp mới không hoạt động
                return search_and_play_youtube(search_query)
        else:
            return "Không hiểu bạn muốn tìm gì trên YouTube"
    
    # Thêm xử lý cho ý định tìm kiếm trên trang web cụ thể
    elif intent == "search_on_site":
        search_data = nlp_processor.extract_entities(text, intent_type="search_on_site")
        site = search_data.get("site", "").lower()
        query = search_data.get("query", "")
        
        if site and query:
            # Chuẩn hóa tên trang web
            site_mapping = {
                "fb": "facebook",
                "face": "facebook",
                "yt": "youtube", 
                "tube": "youtube",
                "gg": "google",
                "ig": "instagram",
                "insta": "instagram",
                "tweet": "twitter",
                "tik": "tiktok",
                "tok": "tiktok",
                "git": "github",
                "shop": "shopee"
            }
            
            if site in site_mapping:
                site = site_mapping[site]
                
            return search_on_specific_site(query, site)
        else:
            return "Không hiểu trang web hoặc nội dung cần tìm kiếm"
    
    # Ghi nhận kết quả vào hồ sơ người dùng
    success = True  # Giả sử lệnh thành công
    user_profile.add_command(text, intent, entities, success)
    
    # PHASE 1 UPDATE: Handle unknown commands with conversation engine
    if intent == "unknown" or not intent:
        print("Unknown intent - trying conversation engine")
        # Try to handle as conversation
        response = conversation_engine.generate_response(text, "unknown")
        return response
    
    return "Command not recognized"

def execute_commands(text):
    """Execute multiple commands from a single text input using simple separator detection"""
    # Định nghĩa các từ/cụm từ dùng để phân tách lệnh 
    separators = [" và ", " and ", " sau đó ", " then ", ", ", "; "]
    
    # Tìm các phân tách trong văn bản
    split_points = []
    for separator in separators:
        start = 0
        while True:
            pos = text.find(separator, start)
            if pos == -1:
                break
            split_points.append((pos, pos + len(separator)))
            start = pos + 1
    
    # Sắp xếp các điểm phân tách
    split_points.sort()
    
    # Nếu không tìm thấy phân tách nào, xử lý như một lệnh đơn
    if not split_points:
        return execute_command(text)
    
    # Tách văn bản thành các lệnh riêng biệt
    commands = []
    last_end = 0
    
    for start, end in split_points:
        if start > last_end:  # Chỉ thêm phần không rỗng
            cmd = text[last_end:start].strip()
            if cmd:
                commands.append(cmd)
        last_end = end
    
    # Thêm phần cuối cùng
    if last_end < len(text):
        cmd = text[last_end:].strip()
        if cmd:
            commands.append(cmd)
    
    # Nếu không thể tách thành các lệnh hợp lệ, xử lý như một lệnh đơn
    if not commands:
        return execute_command(text)
    
    # Thực thi từng lệnh và thu thập kết quả
    print(f"Đã phát hiện {len(commands)} lệnh cần thực thi:")
    responses = []
    
    for i, cmd in enumerate(commands):
        print(f"Đang thực thi lệnh {i+1}/{len(commands)}: '{cmd}'")
        response = execute_command(cmd)
        responses.append(f"Lệnh {i+1}: {response}")
    
    # Trả về kết quả tổng hợp
    return " | ".join(responses)

def execute_commands_advanced(text):
    """Execute multiple commands with advanced NLP parsing"""
    try:
        import nltk
        # Tải thư viện cần thiết khi lần đầu chạy
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            print("Đang tải thư viện NLTK punkt...")
            nltk.download('punkt', quiet=True)
        
        from nltk.tokenize import sent_tokenize
        
        # Phân tách câu bằng NLTK
        sentences = sent_tokenize(text)
        
        # Nếu chỉ có một câu, kiểm tra các phân tách thủ công
        if len(sentences) == 1:
            return execute_commands(text)
        
        # Thực hiện từng câu như một lệnh riêng biệt
        print(f"Đã phát hiện {len(sentences)} lệnh cần thực thi:")
        responses = []
        
        for i, sentence in enumerate(sentences):
            print(f"Đang thực thi lệnh {i+1}/{len(sentences)}: '{sentence}'")
            response = execute_command(sentence)
            responses.append(f"Lệnh {i+1}: {response}")
        
        # Trả về kết quả tổng hợp
        return " | ".join(responses)
    except ImportError:
        print("Không tìm thấy thư viện NLTK, sử dụng phân tích đơn giản thay thế.")
        # Nếu không có NLTK, sử dụng phương pháp đơn giản hơn
        return execute_commands(text)

def process_command(recognizer, audio_data):
    text = recognizer.recognize_speech_from_data(audio_data)
    if text and not text.startswith("Could not understand"):
        print("\n🎤 Command recognized:", text)
        
        # Xử lý lệnh
        response = execute_commands_advanced(text)
        print(f"✅ Response: {response}")
        
        # Speak the response using the speech synthesizer
        speech_synthesizer.speak(response)
        
        # Hỏi phản hồi sau mỗi 10 lệnh (để không làm phiền người dùng)
        command_count = user_profile.profile.get("daily_stats", {}).get(datetime.now().strftime("%Y-%m-%d"), {}).get("total_commands", 0)
        
        if command_count % 10 == 0:
            print("\nBạn có hài lòng với kết quả không? (1-5, 5 là rất hài lòng)")
            try:
                satisfaction = int(input().strip())
                feedback_collector.collect_feedback(
                    command_text=text,
                    predicted_intent=nlp_processor.classify_intent(text),
                    satisfaction_score=satisfaction
                )
            except:
                pass
    else:
        print("\nCouldn't understand command")

def main():
    # Set consistent sample rate for both recording and recognition
    sample_rate = 16000  # Standard for voice recognition
    
    print("=== Voice Control Assistant ===")
    print("This program will control your computer with voice commands")
    print("Say 'Hey Assistant' to activate, then speak your command")
    print("The AI will respond to your commands with voice feedback")
    
    # Kiểm tra và cài đặt NLTK nếu cần
    try:
        try:
            nltk.data.find('tokenizers/punkt')
            print("NLTK ready for multi-command processing.")
        except LookupError:
            print("Installing NLTK punkt for better command processing...")
            nltk.download('punkt', quiet=True)
    except ImportError:
        print("NLTK not found. For better multi-command support, install it using: pip install nltk")
    
    # Set Vietnamese 
    recognizer = SpeechRecognizer(language="vi-VN", engine="google")
    
    # Create recorder with precise settings
    recorder = Recorder(
        channels=1,             
        rate=sample_rate,
        chunk=1024,       
        speech_threshold_ratio=1.2, 
    )
    
    # Test voice synthesis
    welcome_message = "Xin chào! Tôi là trợ lý ảo của bạn. Tôi đang lắng nghe lệnh của bạn."
    print(f"\nTesting voice synthesis: '{welcome_message}'")
    speech_synthesizer.speak(welcome_message)
    
    print("\nVoice recognition started. Speak your command directly.")
    print("Press Ctrl+C to exit the program.")
    
    assistant_active = True
    
    try:
        while True:
            print("\n--- Listening for command... ---")
                
            recorder.start_recording()
            
            #automatically detects speech
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
                            
                    except Exception as e:
                        print(f"Error reading audio: {e}")
                        break
                        
                time.sleep(0.1)
            

            if speech_detected:
                print(f"Processing speech... (max level: {speech_level_detected:.0f})")
                audio_data = recorder.get_audio_data()
                
                if audio_data:
                    text = recognizer.recognize_speech_from_data(audio_data)
                    
                    if text and not text.startswith("Could not understand"):
                        print("\n🎤 Recognized:", text)
                        text_lower = text.lower()
                        
                        # Xử lý lệnh
                        response = execute_commands_advanced(text)
                        print(f"✅ Response: {response}")
                        
                        speech_synthesizer.speak(response)
                        
                        # Hỏi phản hồi sau mỗi 10 lệnh (để không làm phiền người dùng)
                        command_count = user_profile.profile.get("daily_stats", {}).get(datetime.now().strftime("%Y-%m-%d"), {}).get("total_commands", 0)
                        
                        if command_count % 10 == 0:
                            print("\nBạn có hài lòng với kết quả không? (1-5, 5 là rất hài lòng)")
                            try:
                                satisfaction = int(input().strip())
                                feedback_collector.collect_feedback(
                                    command_text=text,
                                    predicted_intent=nlp_processor.classify_intent(text),
                                    satisfaction_score=satisfaction
                                )
                            except:
                                pass
                    else:
                        print("\nCouldn't understand speech")
            
            else:
                print(f"No significant speech detected (max level: {speech_level_detected:.0f})")
            
            recorder.reset()
            
    except KeyboardInterrupt:
        print("\nStopping voice assistant...")
        recorder.close()
        print("Program terminated.")

# PHASE 1 ADDITIONS: Helper functions for conversation management

def get_conversation_status():
    """Get current conversation status"""
    summary = conversation_engine.get_conversation_summary()
    print(f"Conversation Status:")
    print(f"- History length: {summary['history_length']}")
    print(f"- Conversation mode: {summary['current_context']['conversation_mode']}")
    print(f"- Current topic: {summary['current_context']['topic']}")
    print(f"- LLM available: {summary['llm_available']}")
    print(f"- Last activity: {summary['last_activity']}")
    return summary

def toggle_conversation_mode():
    """Toggle conversation mode on/off"""
    current_mode = conversation_engine.current_context.get("conversation_mode", False)
    conversation_engine.set_conversation_mode(not current_mode)
    return not current_mode

def clear_conversation_context():
    """Clear conversation context"""
    conversation_engine.clear_context()
    print("Conversation context cleared")

def test_conversation_system():
    """Test conversation system with sample inputs"""
    test_inputs = [
        "xin chào",
        "bạn có khỏe không",
        "mở chrome",
        "cảm ơn",
        "tạm biệt"
    ]
    
    print("Testing conversation system...")
    for test_input in test_inputs:
        print(f"\nInput: {test_input}")
        response = execute_command(test_input)
        print(f"Response: {response}")

if __name__ == "__main__":
    main()