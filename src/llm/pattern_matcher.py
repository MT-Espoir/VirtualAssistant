"""
Pattern Matcher for Conversation Fallbacks
Provides rule-based responses when LLM is not available
"""

import re
import random
from typing import Dict, List, Optional

class PatternMatcher:
    """
    Pattern-based conversation handler for fallback responses
    """
    
    def __init__(self):
        """Initialize pattern matcher with predefined patterns and responses"""
        self.patterns = self._load_patterns()
        self.fallback_responses = self._load_fallback_responses()
        self.context_patterns = self._load_context_patterns()
    
    def get_response(self, user_input: str, intent: str, context: Dict) -> str:
        """
        Get response based on pattern matching
        
        Args:
            user_input: User's input text
            intent: Classified intent
            context: Current conversation context
            
        Returns:
            Generated response string
        """
        user_input = user_input.lower().strip()
        
        # First, check for specific patterns
        response = self._match_specific_patterns(user_input, intent)
        if response:
            return response
        
        # Then check context-aware patterns
        response = self._match_context_patterns(user_input, context)
        if response:
            return response
        
        # Finally, use intent-based fallback
        return self._get_intent_fallback(intent, user_input)
    
    def _match_specific_patterns(self, user_input: str, intent: str) -> Optional[str]:
        """Match against specific predefined patterns"""
        
        for pattern_group in self.patterns:
            if intent and pattern_group.get("intent") != intent:
                continue
                
            for pattern in pattern_group["patterns"]:
                if re.search(pattern, user_input, re.IGNORECASE):
                    responses = pattern_group["responses"]
                    return random.choice(responses)
        
        return None
    
    def _match_context_patterns(self, user_input: str, context: Dict) -> Optional[str]:
        """Match against context-aware patterns"""
        
        # Check for follow-up questions
        if self._is_followup_question(user_input):
            return random.choice(self.context_patterns["followup"])
        
        # Check for clarification requests
        if self._is_clarification_request(user_input):
            return random.choice(self.context_patterns["clarification"])
        
        # Check for topic change
        if self._is_topic_change(user_input):
            return random.choice(self.context_patterns["topic_change"])
        
        return None
    
    def _is_followup_question(self, text: str) -> bool:
        """Check if input is a follow-up question"""
        followup_indicators = [
            r"còn\\s+(gì|điều\\s+gì|cái\\s+gì)",
            r"what\\s+else",
            r"và\\s+thế",
            r"tiếp\\s+theo",
            r"sau\\s+đó",
            r"then\\s+what"
        ]
        
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in followup_indicators)
    
    def _is_clarification_request(self, text: str) -> bool:
        """Check if input is asking for clarification"""
        clarification_indicators = [
            r"ý\\s+(bạn|anh|chị)\\s+(là|nghĩa)\\s+gì",
            r"what\\s+do\\s+you\\s+mean",
            r"không\\s+hiểu",
            r"explain",
            r"giải\\s+thích",
            r"làm\\s+rõ"
        ]
        
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in clarification_indicators)
    
    def _is_topic_change(self, text: str) -> bool:
        """Check if input indicates a topic change"""
        topic_change_indicators = [
            r"chuyện\\s+khác",
            r"another\\s+topic",
            r"nói\\s+về\\s+việc\\s+khác",
            r"let's\\s+talk\\s+about",
            r"thôi\\s+(nói|bàn)\\s+về"
        ]
        
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in topic_change_indicators)
    
    def _get_intent_fallback(self, intent: str, user_input: str) -> str:
        """Get fallback response based on intent"""
        
        if intent in self.fallback_responses:
            return random.choice(self.fallback_responses[intent])
        
        # Generic fallback responses
        generic_responses = [
            "Tôi hiểu ý bạn rồi.",
            "Điều đó nghe thú vị!",
            "Bạn có thể kể thêm không?",
            "Tôi đang suy nghĩ về điều đó.",
            "Đúng vậy!"
        ]
        
        return random.choice(generic_responses)
    
    def _load_patterns(self) -> List[Dict]:
        """Load predefined conversation patterns"""
        return [
            {
                "intent": "greeting",
                "patterns": [
                    r"^(xin\\s+chào|chào|hello|hi|hey)\\b",
                    r"^(good\\s+(morning|afternoon|evening))",
                    r"^(chào\\s+(buổi\\s+)?(sáng|chiều|tối))"
                ],
                "responses": [
                    "Xin chào! Tôi là trợ lý AI của bạn. Hôm nay tôi có thể giúp gì cho bạn?",
                    "Chào bạn! Rất vui được gặp bạn.",
                    "Hello! Tôi ở đây để hỗ trợ bạn.",
                    "Xin chào! Bạn cần tôi giúp việc gì không?"
                ]
            },
            {
                "intent": "goodbye",
                "patterns": [
                    r"\\b(tạm\\s+biệt|bye|goodbye|see\\s+you)\\b",
                    r"\\b(chào\\s+nhé|hẹn\\s+gặp\\s+lại)\\b"
                ],
                "responses": [
                    "Tạm biệt! Hẹn gặp lại bạn sau nhé!",
                    "Chào bạn! Chúc bạn có một ngày tốt lành!",
                    "Goodbye! Tôi luôn ở đây khi bạn cần.",
                    "Hẹn gặp lại! Take care!"
                ]
            },
            {
                "intent": "small_talk",
                "patterns": [
                    r"\\b(hôm\\s+nay\\s+trời\\s+(đẹp|tốt|xấu))\\b",
                    r"\\b(thời\\s+tiết\\s+(hôm\\s+nay|ngày\\s+hôm\\s+nay))\\b",
                    r"\\b(bạn\\s+(thế\\s+nào|có\\s+khỏe))\\b",
                    r"\\b(how\\s+(are\\s+you|is\\s+the\\s+weather))\\b"
                ],
                "responses": [
                    "Đúng vậy! Trời đẹp là một ngày tuyệt vời để làm việc hiệu quả.",
                    "Tôi khỏe, cảm ơn bạn! Bạn thì sao?",
                    "Thời tiết hôm nay thật tuyệt! Bạn có kế hoạch gì đặc biệt không?",
                    "Tôi luôn sẵn sàng giúp đỡ bạn!"
                ]
            },
            {
                "intent": "thanks",
                "patterns": [
                    r"\\b(cảm\\s+ơn|thank\\s+you|thanks)\\b",
                    r"\\b(cám\\s+ơn\\s+(bạn|anh|chị))\\b"
                ],
                "responses": [
                    "Không có gì! Tôi luôn sẵn sàng giúp đỡ bạn.",
                    "Rất vui được giúp bạn!",
                    "You're welcome!",
                    "Đó là nhiệm vụ của tôi mà!"
                ]
            },
            {
                "intent": "help",
                "patterns": [
                    r"\\b(giúp\\s+(tôi|mình)|help\\s+me)\\b",
                    r"\\b(bạn\\s+có\\s+thể\\s+làm\\s+gì)\\b",
                    r"\\b(hướng\\s+dẫn|instruction)\\b"
                ],
                "responses": [
                    "Tôi có thể giúp bạn mở ứng dụng, tìm kiếm trên web, điều khiển hệ thống, và trò chuyện cùng bạn!",
                    "Bạn có thể yêu cầu tôi mở ứng dụng, tìm kiếm thông tin, hoặc đơn giản là trò chuyện.",
                    "Tôi ở đây để hỗ trợ! Hãy thử nói 'mở Chrome' hoặc 'tìm kiếm thời tiết'.",
                    "Tôi có thể thực hiện lệnh và cũng có thể trò chuyện với bạn. Bạn muốn thử gì?"
                ]
            },
            {
                "intent": "personal",
                "patterns": [
                    r"\\b(bạn\\s+là\\s+ai|who\\s+are\\s+you)\\b",
                    r"\\b(tên\\s+(bạn|của\\s+bạn)\\s+là\\s+gì)\\b",
                    r"\\b(bạn\\s+từ\\s+đâu)\\b"
                ],
                "responses": [
                    "Tôi là trợ lý AI được tạo ra để giúp đỡ bạn trong công việc hàng ngày.",
                    "Tôi là voice assistant - một trợ lý giọng nói thông minh.",
                    "Bạn có thể gọi tôi là AI Assistant. Tôi ở đây để hỗ trợ bạn!",
                    "Tôi là một AI được thiết kế để hiểu và thực hiện các yêu cầu của bạn."
                ]
            },
            {
                "intent": "time",
                "patterns": [
                    r"\\b(mấy\\s+giờ|what\\s+time)\\b",
                    r"\\b(bây\\s+giờ\\s+là\\s+mấy\\s+giờ)\\b",
                    r"\\b(hiện\\s+tại\\s+(là\\s+)?mấy\\s+giờ)\\b"
                ],
                "responses": [
                    "Bạn có thể kiểm tra giờ trên màn hình hoặc yêu cầu tôi mở ứng dụng đồng hồ.",
                    "Tôi không thể xem giờ trực tiếp, nhưng bạn có thể kiểm tra ở góc màn hình.",
                    "Để biết giờ chính xác, bạn hãy nhìn vào thanh taskbar nhé!"
                ]
            }
        ]
    
    def _load_fallback_responses(self) -> Dict[str, List[str]]:
        """Load fallback responses for different intents"""
        return {
            "conversation": [
                "Điều đó nghe thú vị! Bạn có thể kể thêm không?",
                "Tôi hiểu ý bạn rồi. Còn gì nữa không?",
                "Đó là một quan điểm hay!",
                "Bạn nói đúng đấy!",
                "Tôi đồng ý với bạn."
            ],
            "question_answering": [
                "Đó là một câu hỏi hay! Tôi cần suy nghĩ thêm.",
                "Tôi chưa chắc chắn về điều đó. Bạn có thể tìm hiểu thêm không?",
                "Câu hỏi thú vị! Bạn có muốn tôi tìm kiếm thông tin này không?",
                "Để trả lời chính xác, tôi cần tìm hiểu thêm."
            ],
            "small_talk": [
                "Đúng vậy!",
                "Tôi hiểu cảm giác đó.",
                "Nghe hay đấy!",
                "Thú vị nhỉ!",
                "Ồ, thật sao?"
            ],
            "unknown": [
                "Tôi không chắc hiểu ý bạn. Bạn có thể nói rõ hơn không?",
                "Bạn có thể diễn đạt khác cách được không?",
                "Tôi cần thêm thông tin để hiểu yêu cầu của bạn.",
                "Có lẽ bạn nên thử cách khác."
            ]
        }
    
    def _load_context_patterns(self) -> Dict[str, List[str]]:
        """Load context-aware response patterns"""
        return {
            "followup": [
                "Còn nhiều điều thú vị khác nữa!",
                "Bạn muốn biết thêm về điều gì?",
                "Có rất nhiều thứ chúng ta có thể nói về.",
                "Bạn có chủ đề nào khác muốn thảo luận không?"
            ],
            "clarification": [
                "Ý tôi là...",
                "Để tôi giải thích rõ hơn.",
                "Tôi có thể nói cách khác.",
                "Bạn muốn tôi giải thích điều gì cụ thể?"
            ],
            "topic_change": [
                "Được thôi! Chúng ta nói về gì nhỉ?",
                "Chủ đề mới! Tôi sẵn sàng lắng nghe.",
                "OK, chuyển sang chuyện khác nhé!",
                "Thay đổi không khí một chút. Tốt đấy!"
            ]
        }
    
    def add_pattern(self, intent: str, pattern: str, responses: List[str]):
        """Add new pattern dynamically"""
        new_pattern = {
            "intent": intent,
            "patterns": [pattern],
            "responses": responses
        }
        self.patterns.append(new_pattern)
    
    def get_pattern_coverage(self, texts: List[str]) -> Dict:
        """Analyze pattern coverage for given texts"""
        covered = 0
        total = len(texts)
        
        for text in texts:
            if self._match_specific_patterns(text.lower(), None):
                covered += 1
        
        return {
            "coverage_percentage": (covered / total) * 100 if total > 0 else 0,
            "covered_texts": covered,
            "total_texts": total
        }
