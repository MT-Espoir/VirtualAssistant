"""
Test script for Phase 1 Conversation System
Test the conversation capabilities without requiring microphone
"""

import sys
import os

# Add src directory to path
sys.path.append(os.path.dirname(__file__))

from main import execute_command, get_conversation_status, test_conversation_system, conversation_engine

def interactive_test():
    """Interactive test mode for conversation system"""
    print("=" * 60)
    print("PHASE 1 CONVERSATION SYSTEM TEST")
    print("=" * 60)
    print("Commands:")
    print("- Type your message to test conversation")
    print("- Type 'status' to see conversation status")
    print("- Type 'clear' to clear conversation context")
    print("- Type 'test' to run automated tests")
    print("- Type 'quit' to exit")
    print("=" * 60)
    
    # Show initial status
    get_conversation_status()
    print()
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if user_input.lower() == 'quit':
                break
            elif user_input.lower() == 'status':
                get_conversation_status()
            elif user_input.lower() == 'clear':
                conversation_engine.clear_context()
            elif user_input.lower() == 'test':
                test_conversation_system()
            elif user_input:
                response = execute_command(user_input)
                print(f"Assistant: {response}")
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
    
    print("\nTest session ended.")

def automated_test():
    """Run automated tests for conversation system"""
    print("=" * 60)
    print("AUTOMATED CONVERSATION TESTS")
    print("=" * 60)
    
    test_cases = [
        # Test conversation intents
        ("xin chào", "greeting"),
        ("hello", "greeting"),
        ("bạn có khỏe không", "small_talk"),
        ("hôm nay trời đẹp nhỉ", "conversation"),
        ("kể cho tôi nghe về AI", "conversation"),
        ("thời tiết hôm nay thế nào", "question_answering"),
        ("mấy giờ rồi", "question_answering"),
        ("cảm ơn bạn", "thanks"),
        ("tạm biệt", "goodbye"),
        
        # Test command intents
        ("mở chrome", "open_app"),
        ("tìm kiếm google", "web_search"),
        ("tăng âm lượng", "system_volume"),
        
        # Test mixed/unknown intents
        ("tôi thích màu xanh", "unknown"),
        ("câu này không rõ ràng lắm", "unknown"),
    ]
    
    for i, (text, expected_intent) in enumerate(test_cases, 1):
        print(f"\nTest {i}/{len(test_cases)}: '{text}'")
        print(f"Expected intent: {expected_intent}")
        
        try:
            response = execute_command(text)
            print(f"Response: {response}")
            
            # Check conversation status after each test
            summary = conversation_engine.get_conversation_summary()
            print(f"Conversation mode: {summary['current_context']['conversation_mode']}")
            
        except Exception as e:
            print(f"Error: {e}")
        
        print("-" * 40)
    
    print("\nAutomated tests completed!")

def test_pattern_matching():
    """Test pattern matching fallback"""
    print("=" * 60)
    print("PATTERN MATCHING TEST")
    print("=" * 60)
    
    # Test without LLM (force pattern matching)
    original_client = conversation_engine.llm_client
    conversation_engine.llm_client = None  # Disable LLM
    
    pattern_tests = [
        "xin chào",
        "bạn là ai",
        "giúp tôi",
        "cảm ơn",
        "tạm biệt",
        "hôm nay trời đẹp",
        "mấy giờ rồi",
        "bạn thế nào"
    ]
    
    print("Testing with pattern matching only (LLM disabled):")
    for test in pattern_tests:
        print(f"\nInput: {test}")
        response = execute_command(test)
        print(f"Response: {response}")
    
    # Restore LLM client
    conversation_engine.llm_client = original_client
    print("\nPattern matching tests completed!")

def main():
    """Main test function"""
    print("Phase 1 Conversation System Test Suite")
    print("Choose test mode:")
    print("1. Interactive test")
    print("2. Automated test")
    print("3. Pattern matching test")
    print("4. All tests")
    
    choice = input("\nEnter choice (1-4): ").strip()
    
    if choice == "1":
        interactive_test()
    elif choice == "2":
        automated_test()
    elif choice == "3":
        test_pattern_matching()
    elif choice == "4":
        automated_test()
        print("\n" + "=" * 60)
        test_pattern_matching()
        print("\n" + "=" * 60)
        print("All tests completed. Starting interactive mode...")
        interactive_test()
    else:
        print("Invalid choice. Starting interactive mode...")
        interactive_test()

if __name__ == "__main__":
    main()
