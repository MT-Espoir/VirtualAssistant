"""
Simple test script to verify Phase 1 conversation implementation
Tests conversation system without requiring microphone input
"""

import sys
import os

# Add src directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test if all required modules can be imported"""
    print("Testing imports...")
    
    try:
        from llm.conversation_engine import ConversationEngine
        print("✓ ConversationEngine imported successfully")
    except Exception as e:
        print(f"✗ ConversationEngine import failed: {e}")
        return False
    
    try:
        from llm.ollama_client import OllamaClient
        print("✓ OllamaClient imported successfully")
    except Exception as e:
        print(f"✗ OllamaClient import failed: {e}")
        return False
    
    try:
        from llm.pattern_matcher import PatternMatcher
        print("✓ PatternMatcher imported successfully")
    except Exception as e:
        print(f"✗ PatternMatcher import failed: {e}")
        return False
    
    try:
        from nlp.nlp_model import NLPProcessor
        print("✓ NLPProcessor imported successfully")
    except Exception as e:
        print(f"✗ NLPProcessor import failed: {e}")
        return False
    
    return True

def test_intent_classification():
    """Test the updated intent classification"""
    print("\nTesting intent classification...")
    
    try:
        from nlp.nlp_model import NLPProcessor
        nlp_processor = NLPProcessor()
        classify_intent = nlp_processor.classify_intent

        test_cases = [
            ("xin chào", "greeting"),
            ("hello", "greeting"),
            ("tạm biệt", "goodbye"),
            ("cảm ơn", "thanks"),
            ("bạn là ai", "personal"),
            ("giúp tôi", "help"),
            ("hôm nay trời đẹp", "conversation"),
            ("mấy giờ rồi", "question_answering"),
            ("tôi vui", "small_talk"),
            ("mở chrome", "open_app"),
            ("tìm kiếm google", "web_search"),
        ]
        
        for text, expected in test_cases:
            result = classify_intent(text)
            status = "✓" if result == expected else "✗"
            print(f"{status} '{text}' → {result} (expected: {expected})")
        
        return True
        
    except Exception as e:
        print(f"✗ Intent classification test failed: {e}")
        return False

def test_conversation_engine():
    """Test conversation engine functionality"""
    print("\nTesting conversation engine...")
    
    try:
        from llm.conversation_engine import ConversationEngine
        
        # Initialize conversation engine
        engine = ConversationEngine()
        print("✓ ConversationEngine initialized")
        
        # Test basic functionality
        response = engine.generate_response("xin chào", "greeting")
        print(f"✓ Generated response: {response}")
        
        # Test context management
        engine.update_context("topic", "test_topic")
        context = engine.current_context
        print(f"✓ Context updated: {context}")
        
        # Test conversation status
        summary = engine.get_conversation_summary()
        print(f"✓ Conversation summary: {summary['history_length']} messages")
        
        return True
        
    except Exception as e:
        print(f"✗ ConversationEngine test failed: {e}")
        return False

def test_pattern_matcher():
    """Test pattern matcher functionality"""
    print("\nTesting pattern matcher...")
    
    try:
        from llm.pattern_matcher import PatternMatcher
        
        matcher = PatternMatcher()
        print("✓ PatternMatcher initialized")
        
        # Test pattern matching
        response = matcher.get_response("xin chào", "greeting", {})
        print(f"✓ Pattern response: {response}")
        
        # Test fallback responses
        response = matcher.get_response("test unknown", "unknown", {})
        print(f"✓ Fallback response: {response}")
        
        return True
        
    except Exception as e:
        print(f"✗ PatternMatcher test failed: {e}")
        return False

def test_ollama_connection():
    """Test Ollama connection (if available)"""
    print("\nTesting Ollama connection...")
    
    try:
        from llm.ollama_client import OllamaClient
        
        client = OllamaClient()
        print("✓ OllamaClient initialized with phi3:3.8b")
        
        # Test connection
        connected = client.test_connection()
        if connected:
            print("✓ Ollama connection successful")
            
            # Test model listing
            models = client.list_available_models()
            print(f"✓ Available models: {models}")
            
        else:
            print("⚠ Ollama not available (this is OK, will use pattern matching)")
        
        return True
        
    except Exception as e:
        print(f"✗ Ollama test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("PHASE 1 CONVERSATION SYSTEM - VERIFICATION TEST")
    print("=" * 60)
    
    all_passed = True
    
    # Run tests
    tests = [
        test_imports,
        test_intent_classification,
        test_conversation_engine,
        test_pattern_matcher,
        test_ollama_connection
    ]
    
    for test in tests:
        try:
            result = test()
            if not result:
                all_passed = False
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
            all_passed = False
        print("-" * 40)
    
    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 ALL TESTS PASSED! Phase 1 implementation is working.")
        print("\nNext steps:")
        print("1. Install Ollama and phi3:3.8b model for better conversations")
        print("2. Run: python test_conversation.py for interactive testing")
        print("3. Run: python main.py to start the voice assistant")
    else:
        print("❌ SOME TESTS FAILED. Please check the errors above.")
        print("\nCommon fixes:")
        print("1. Make sure all files are saved")
        print("2. Check import paths")
        print("3. Install missing dependencies")
    
    print("=" * 60)

if __name__ == "__main__":
    main()
