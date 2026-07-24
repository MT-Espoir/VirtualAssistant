#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Pure AI Reasoning Test - Phi-2 Intelligence Test
Tests the pure AI approach (100% AI, 0% rule-based) for intelligent reasoning capabilities.

Features tested:
- Contextual understanding
- Personality adaptation
- Emotional intelligence
- Reasoning capabilities
- Vietnamese response quality

Hardware: Dell Inspiron 5415 (AMD Ryzen 7 5500U, 16GB RAM)
Model: Microsoft Phi-2 (2.7B parameters)
Approach: Pure AI reasoning (no rule-based fallback)
"""

import sys
import os
import time
import json
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__)))

try:
    from components.personality.lightweight_ai_enhancer import create_ai_enhancer
    print("✅ Successfully imported AI enhancer")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

def create_test_personality():
    """Create test personality profile for AI reasoning tests"""
    return {
        'communication_styles': {
            'formal': 0.3,
            'informal': 0.7,
            'enthusiastic': 0.8,
            'professional': 0.4
        },
        'emotional_patterns': {
            'happy': 0.6,
            'curious': 0.8,
            'excited': 0.7,
            'calm': 0.5,
            'supportive': 0.9
        },
        'interests': {
            'technology': 0.9,
            'learning': 0.8,
            'conversation': 0.7,
            'helping': 0.9,
            'Vietnamese_culture': 0.6
        },
        'response_preferences': {
            'detailed': 0.8,
            'encouraging': 0.9,
            'empathetic': 0.8,
            'intelligent': 0.9
        }
    }

def run_reasoning_tests():
    """Run comprehensive AI reasoning tests"""
    
    print("🧠 Pure AI Reasoning Test - Phi-2 Intelligence")
    print("=" * 60)
    print(f"⏰ Starting test at: {datetime.now().strftime('%H:%M:%S')}")
    print(f"🖥️  Hardware: Dell Inspiron 5415 (AMD Ryzen 7 5500U, 16GB RAM)")
    print(f"🤖 Model: Microsoft Phi-2 (2.7B parameters)")
    print(f"🎯 Approach: Pure AI reasoning (100% AI, 0% rule-based)")
    print("=" * 60)
    
    # Initialize AI enhancer with pure AI mode (ai_frequency=1.0)
    print("\n🚀 Initializing Pure AI Reasoning System...")
    start_init = time.time()
    
    try:
        ai_enhancer = create_ai_enhancer(
            model_tier="phi2_optimized",
            ai_frequency=1.0  # 100% AI, 0% rule-based
        )
        
        init_time = time.time() - start_init
        print(f"✅ AI system initialized in {init_time:.2f}s")
        
    except Exception as e:
        print(f"❌ Failed to initialize AI system: {e}")
        return
    
    # Create test personality
    personality = create_test_personality()
    
    # Test scenarios focusing on reasoning and intelligence
    test_scenarios = [
        {
            'name': 'Greeting Intelligence',
            'input': 'Xin chào! Bạn có thể giúp tôi không?',
            'expected_reasoning': ['greeting detection', 'help request', 'polite response']
        },
        {
            'name': 'Emotional Understanding',
            'input': 'Hôm nay tôi rất vui vì được học về AI!',
            'expected_reasoning': ['emotion detection', 'enthusiasm matching', 'topic engagement']
        },
        {
            'name': 'Problem Solving',
            'input': 'Tôi đang gặp khó khăn trong việc học lập trình. Bạn có lời khuyên nào không?',
            'expected_reasoning': ['problem analysis', 'supportive response', 'practical advice']
        },
        {
            'name': 'Complex Question',
            'input': 'Tại sao AI lại quan trọng trong tương lai? Bạn nghĩ sao về điều này?',
            'expected_reasoning': ['analytical thinking', 'opinion formation', 'thoughtful explanation']
        },
        {
            'name': 'Cultural Context',
            'input': 'Chúc mừng năm mới! Bạn có hiểu về văn hóa Việt Nam không?',
            'expected_reasoning': ['cultural awareness', 'appropriate response', 'context understanding']
        },
        {
            'name': 'Gratitude Expression',
            'input': 'Cảm ơn bạn rất nhiều! Bạn đã giúp tôi hiểu rõ hơn.',
            'expected_reasoning': ['gratitude recognition', 'acknowledgment', 'relationship building']
        },
        {
            'name': 'Creative Thinking',
            'input': 'Nếu bạn là con người, bạn sẽ muốn làm gì đầu tiên?',
            'expected_reasoning': ['hypothetical thinking', 'creativity', 'philosophical response']
        },
        {
            'name': 'Technical Discussion',
            'input': 'Machine learning và deep learning khác nhau như thế nào?',
            'expected_reasoning': ['technical knowledge', 'clear explanation', 'educational approach']
        }
    ]
    
    results = []
    total_response_time = 0
    successful_responses = 0
    
    print(f"\n🧪 Running {len(test_scenarios)} reasoning test scenarios...")
    print("-" * 60)
    
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n[Test {i}/{len(test_scenarios)}] {scenario['name']}")
        print(f"💬 Input: {scenario['input']}")
        
        # Generate AI response
        start_time = time.time()
        
        try:
            response = ai_enhancer.generate_personality_response(
                scenario['input'], 
                personality
            )
            
            response_time = time.time() - start_time
            total_response_time += response_time
            
            print(f"🤖 AI Response: {response}")
            print(f"⏱️  Response time: {response_time:.2f}s")
            
            # Analyze response quality
            quality_score = analyze_response_quality(
                response, 
                scenario['input'], 
                scenario['expected_reasoning']
            )
            
            print(f"📊 Quality Score: {quality_score}/10")
            
            if response and len(response.strip()) > 10:
                successful_responses += 1
                print("✅ Response generated successfully")
            else:
                print("❌ Response failed or too short")
            
            results.append({
                'scenario': scenario['name'],
                'input': scenario['input'],
                'response': response,
                'response_time': response_time,
                'quality_score': quality_score,
                'success': len(response.strip()) > 10 if response else False
            })
            
        except Exception as e:
            print(f"❌ Error generating response: {e}")
            results.append({
                'scenario': scenario['name'],
                'input': scenario['input'],
                'response': None,
                'response_time': 0,
                'quality_score': 0,
                'success': False,
                'error': str(e)
            })
        
        print("-" * 40)
    
    # Calculate statistics
    if len(results) > 0:
        avg_response_time = total_response_time / len(results)
        success_rate = (successful_responses / len(results)) * 100
        avg_quality = sum(r.get('quality_score', 0) for r in results) / len(results)
        
        print(f"\n📈 PURE AI REASONING RESULTS:")
        print("=" * 60)
        print(f"🎯 Success Rate: {success_rate:.1f}% ({successful_responses}/{len(results)})")
        print(f"⚡ Average Response Time: {avg_response_time:.2f}s")
        print(f"🌟 Average Quality Score: {avg_quality:.1f}/10")
        print(f"🧠 AI Reasoning Mode: Pure AI (100% intelligent responses)")
        
        # Show AI system statistics
        ai_stats = ai_enhancer.get_stats()
        print(f"\n🔍 AI System Statistics:")
        print(f"   - Total AI requests: {ai_stats['total_requests']}")
        print(f"   - AI success rate: {ai_stats['ai_successes']}/{ai_stats['total_requests']} ({(ai_stats['ai_successes']/max(1,ai_stats['total_requests']))*100:.1f}%)")
        print(f"   - Average AI response time: {ai_stats['avg_response_time']:.2f}s")
        print(f"   - AI frequency setting: {ai_enhancer.ai_frequency*100:.0f}% (Pure AI mode)")
        
        # Performance assessment
        print(f"\n🎖️  PERFORMANCE ASSESSMENT:")
        if success_rate >= 80 and avg_quality >= 7:
            print("🏆 EXCELLENT: Pure AI reasoning system performing very well!")
        elif success_rate >= 60 and avg_quality >= 6:
            print("✅ GOOD: Pure AI system working well with room for improvement")
        elif success_rate >= 40:
            print("⚠️  ACCEPTABLE: Pure AI system functional but needs optimization")
        else:
            print("❌ NEEDS IMPROVEMENT: Pure AI system requires significant optimization")
        
        # Save detailed results
        save_results(results, ai_stats)
        
    else:
        print("❌ No results to analyze")
    
    # Cleanup
    try:
        ai_enhancer.cleanup()
        print("\n🧹 AI resources cleaned up")
    except Exception:
        pass

def analyze_response_quality(response, user_input, expected_reasoning):
    """Analyze the quality of AI reasoning response"""
    if not response:
        return 0
    
    score = 0
    response_lower = response.lower()
    input_lower = user_input.lower()
    
    # Basic response criteria (4 points)
    if len(response.strip()) > 15:
        score += 1  # Adequate length
    if response != user_input:
        score += 1  # Not just echoing input
    if any(char in response for char in ['!', '?', '.']):
        score += 1  # Proper punctuation
    if len(response.split()) >= 5:
        score += 1  # Multiple words
    
    # Intelligence indicators (3 points)
    intelligence_markers = [
        'hiểu', 'nghĩ', 'suy nghĩ', 'phân tích', 'đánh giá',
        'understand', 'think', 'analyze', 'consider', 'believe'
    ]
    if any(marker in response_lower for marker in intelligence_markers):
        score += 1  # Shows thinking
    
    if '?' in response:
        score += 1  # Asks questions (engagement)
    
    if any(word in response_lower for word in ['tại sao', 'như thế nào', 'why', 'how']):
        score += 1  # Shows curiosity/reasoning
    
    # Contextual relevance (2 points)
    if 'xin chào' in input_lower and any(greeting in response_lower for greeting in ['chào', 'hello', 'vui']):
        score += 1
    elif 'cảm ơn' in input_lower and any(thanks in response_lower for thanks in ['không có gì', 'welcome', 'vui']):
        score += 1
    elif 'khó khăn' in input_lower and any(support in response_lower for support in ['giúp', 'hỗ trợ', 'support']):
        score += 1
    elif '?' in user_input and any(explain in response_lower for explain in ['là', 'có thể', 'nghĩa là']):
        score += 1
    
    # Personality matching (1 point)
    if any(personal in response_lower for personal in ['tôi', 'mình', 'bạn', 'chúng ta']):
        score += 1  # Personal engagement
    
    return min(score, 10)  # Cap at 10

def save_results(results, ai_stats):
    """Save test results to file"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"pure_ai_reasoning_test_{timestamp}.json"
        
        test_data = {
            'timestamp': datetime.now().isoformat(),
            'test_type': 'pure_ai_reasoning',
            'model': 'Microsoft Phi-2 (2.7B)',
            'hardware': 'Dell Inspiron 5415 (AMD Ryzen 7 5500U, 16GB RAM)',
            'ai_frequency': 1.0,  # Pure AI mode
            'results': results,
            'ai_stats': ai_stats,
            'summary': {
                'total_tests': len(results),
                'successful_responses': sum(1 for r in results if r.get('success', False)),
                'avg_response_time': sum(r.get('response_time', 0) for r in results) / len(results),
                'avg_quality_score': sum(r.get('quality_score', 0) for r in results) / len(results)
            }
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(test_data, f, ensure_ascii=False, indent=2)
        
        print(f"💾 Results saved to: {filename}")
        
    except Exception as e:
        print(f"⚠️  Could not save results: {e}")

if __name__ == "__main__":
    print("🧠 Pure AI Reasoning Test for Dell Inspiron 5415")
    print("Testing Phi-2 with 100% AI intelligence (no rule-based fallback)")
    print("Focus: Reasoning, understanding, and intelligent responses")
    
    try:
        run_reasoning_tests()
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
