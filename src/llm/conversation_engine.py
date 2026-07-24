"""
Conversation Engine for Voice Assistant
Handles natural language conversation using LLM
"""

import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

class ConversationEngine:
    """
    Main conversation engine that manages natural language conversations
    """
    
    def __init__(self, max_history_length=10, context_timeout_minutes=30):
        """
        Initialize conversation engine
        
        Args:
            max_history_length: Maximum number of conversation turns to remember
            context_timeout_minutes: Minutes before context expires
        """
        self.max_history_length = max_history_length
        self.context_timeout_minutes = context_timeout_minutes
        
        # Conversation state
        self.conversation_history = []
        self.current_context = {
            "topic": None,
            "last_command": None,
            "user_preferences": {},
            "conversation_mode": False
        }
        self.last_activity = datetime.now()
        
        # Initialize LLM client (will be set based on available service)
        self.llm_client = None
        self._initialize_llm_client()
        
        # Pattern matcher for fallback responses
        from llm.pattern_matcher import PatternMatcher
        self.pattern_matcher = PatternMatcher()
    
    def _initialize_llm_client(self):
        """Initialize the LLM client based on available services"""
        try:
            # Try Ollama first
            from llm.ollama_client import OllamaClient
            self.llm_client = OllamaClient()
            if self.llm_client.test_connection():
                print("Using Ollama for conversations")
                return
        except Exception as e:
            print(f"Ollama not available: {e}")
        
        # Fallback to pattern matching if no LLM available
        print("Using pattern matching for conversations")
        self.llm_client = None
    
    def generate_response(self, user_input: str, intent: str = None) -> str:
        """
        Generate a response to user input
        
        Args:
            user_input: The user's input text
            intent: Classified intent (optional)
            
        Returns:
            Generated response string
        """
        # Update activity timestamp
        self.last_activity = datetime.now()
        
        # Add user input to history
        self._add_to_history("user", user_input)
        
        # Clean expired context
        self._clean_expired_context()
        
        # Generate response based on available method
        if self.llm_client and intent in ["conversation", "question_answering", "small_talk"]:
            response = self._generate_llm_response(user_input, intent)
        else:
            response = self._generate_pattern_response(user_input, intent)
        
        # Add response to history
        self._add_to_history("assistant", response)
        
        return response
    
    def _generate_llm_response(self, user_input: str, intent: str) -> str:
        """Generate response using LLM"""
        try:
            # Prepare conversation context
            context = self._prepare_context_for_llm()
            
            # Generate response
            response = self.llm_client.generate_response(
                user_input=user_input,
                context=context,
                intent=intent
            )
            
            return response
            
        except Exception as e:
            print(f"LLM generation error: {e}")
            # Fallback to pattern matching
            return self._generate_pattern_response(user_input, intent)
    
    def _generate_pattern_response(self, user_input: str, intent: str) -> str:
        """Generate response using pattern matching"""
        return self.pattern_matcher.get_response(user_input, intent, self.current_context)
    
    def _prepare_context_for_llm(self) -> str:
        """Prepare conversation context for LLM"""
        context_parts = []
        
        # Add system context
        context_parts.append("Bạn là một trợ lý AI thông minh và hữu ích.")
        context_parts.append("Bạn có thể trò chuyện tự nhiên bằng tiếng Việt.")
        context_parts.append("Hãy trả lời một cách ngắn gọn và thân thiện.")
        
        # Add current topic if any
        if self.current_context.get("topic"):
            context_parts.append(f"Chủ đề hiện tại: {self.current_context['topic']}")
        
        # Add recent conversation history
        if self.conversation_history:
            context_parts.append("\\nCuộc trò chuyện gần đây:")
            for entry in self.conversation_history[-5:]:  # Last 5 exchanges
                role = "Người dùng" if entry["role"] == "user" else "Trợ lý"
                context_parts.append(f"{role}: {entry['content']}")
        
        return "\\n".join(context_parts)
    
    def _add_to_history(self, role: str, content: str):
        """Add message to conversation history"""
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        }
        
        self.conversation_history.append(entry)
        
        # Maintain history length limit
        if len(self.conversation_history) > self.max_history_length * 2:  # *2 for user+assistant pairs
            self.conversation_history = self.conversation_history[-self.max_history_length * 2:]
    
    def _clean_expired_context(self):
        """Clean expired conversation context"""
        current_time = datetime.now()
        timeout = timedelta(minutes=self.context_timeout_minutes)
        
        if current_time - self.last_activity > timeout:
            self.clear_context()
    
    def update_context(self, key: str, value):
        """Update conversation context"""
        self.current_context[key] = value
        self.last_activity = datetime.now()
    
    def clear_context(self):
        """Clear conversation context"""
        self.conversation_history.clear()
        self.current_context = {
            "topic": None,
            "last_command": None,
            "user_preferences": {},
            "conversation_mode": False
        }
        print("Conversation context cleared due to inactivity")
    
    def get_conversation_summary(self) -> Dict:
        """Get summary of current conversation state"""
        return {
            "history_length": len(self.conversation_history),
            "current_context": self.current_context.copy(),
            "last_activity": self.last_activity.isoformat(),
            "llm_available": self.llm_client is not None
        }
    
    def is_conversation_intent(self, intent: str) -> bool:
        """Check if intent should be handled by conversation engine"""
        conversation_intents = [
            "conversation", 
            "question_answering", 
            "small_talk", 
            "greeting", 
            "goodbye",
            "help"
        ]
        return intent in conversation_intents
    
    def set_conversation_mode(self, enabled: bool):
        """Enable or disable conversation mode"""
        self.current_context["conversation_mode"] = enabled
        if enabled:
            print("Conversation mode enabled")
        else:
            print("Conversation mode disabled")
