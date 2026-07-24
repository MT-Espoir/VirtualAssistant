"""
Ollama Client for Local LLM Inference
Handles communication with Ollama API
"""

import requests
import json
from typing import Dict, Optional

class OllamaClient:
    """
    Client for communicating with Ollama API
    """
    
    def __init__(self, base_url="http://localhost:11434", model="phi3:3.8b"):
        """
        Initialize Ollama client
        
        Args:
            base_url: Ollama API base URL
            model: Model name to use for generation
        """
        self.base_url = base_url
        self.model = model
        self.api_url = f"{base_url}/api/generate"
        
        # Default generation parameters
        self.generation_params = {
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 150,
            "stream": False
        }
    
    def test_connection(self) -> bool:
        """
        Test connection to Ollama API
        
        Returns:
            True if connection is successful, False otherwise
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def generate_response(self, user_input: str, context: str = "", intent: str = None) -> str:
        """
        Generate response using Ollama
        
        Args:
            user_input: User's input message
            context: Conversation context
            intent: Classified intent
            
        Returns:
            Generated response string
        """
        try:
            # Format the prompt
            prompt = self._format_prompt(user_input, context, intent)
            
            # Prepare request payload
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.generation_params["temperature"],
                    "top_p": self.generation_params["top_p"],
                    "num_predict": self.generation_params["max_tokens"]
                }
            }
            
            # Make API request
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return self._clean_response(result.get("response", ""))
            else:
                print(f"Ollama API error: {response.status_code}")
                return self._get_fallback_response(intent)
                
        except requests.exceptions.Timeout:
            print("Ollama request timeout")
            return "Xin lỗi, tôi đang suy nghĩ hơi lâu. Bạn có thể thử lại không?"
            
        except Exception as e:
            print(f"Ollama generation error: {e}")
            return self._get_fallback_response(intent)
    
    def _format_prompt(self, user_input: str, context: str, intent: str) -> str:
        """
        Format prompt for LLM generation
        
        Args:
            user_input: User's input
            context: Conversation context
            intent: Classified intent
            
        Returns:
            Formatted prompt string
        """
        prompt_parts = []
        
        # Add system context if provided
        if context:
            prompt_parts.append(context)
            prompt_parts.append("")
        
        # Add intent-specific instructions
        if intent == "conversation":
            prompt_parts.append("Hãy trò chuyện một cách tự nhiên và thân thiện.")
        elif intent == "question_answering":
            prompt_parts.append("Hãy trả lời câu hỏi một cách chính xác và hữu ích.")
        elif intent == "small_talk":
            prompt_parts.append("Hãy tham gia cuộc trò chuyện nhẹ nhàng và vui vẻ.")
        
        # Add user input
        prompt_parts.append(f"Người dùng: {user_input}")
        prompt_parts.append("Trợ lý:")
        
        return "\\n".join(prompt_parts)
    
    def _clean_response(self, response: str) -> str:
        """
        Clean and format the generated response
        
        Args:
            response: Raw response from LLM
            
        Returns:
            Cleaned response string
        """
        # Remove common artifacts
        response = response.strip()
        
        # Remove "Trợ lý:" prefix if present
        if response.startswith("Trợ lý:"):
            response = response[7:].strip()
        
        # Ensure response is not too long
        if len(response) > 300:
            # Find last complete sentence
            sentences = response.split('. ')
            if len(sentences) > 1:
                response = '. '.join(sentences[:-1]) + '.'
            else:
                response = response[:300] + "..."
        
        # Ensure response is not empty
        if not response:
            response = "Tôi hiểu ý bạn rồi."
        
        return response
    
    def _get_fallback_response(self, intent: str) -> str:
        """
        Get fallback response when LLM fails
        
        Args:
            intent: Intent classification
            
        Returns:
            Fallback response string
        """
        fallback_responses = {
            "conversation": "Điều đó nghe thú vị! Bạn có thể kể thêm không?",
            "question_answering": "Tôi cần suy nghĩ thêm về câu hỏi này.",
            "small_talk": "Đúng vậy! Tôi đồng ý với bạn.",
            "greeting": "Xin chào! Tôi là trợ lý AI của bạn.",
            "goodbye": "Tạm biệt! Hẹn gặp lại bạn sau.",
            "help": "Tôi có thể giúp bạn với nhiều việc. Bạn cần hỗ trợ gì?"
        }
        
        return fallback_responses.get(intent, "Tôi hiểu rồi. Còn gì khác không?")
    
    def update_generation_params(self, **kwargs):
        """
        Update generation parameters
        
        Args:
            **kwargs: Parameters to update (temperature, top_p, max_tokens)
        """
        self.generation_params.update(kwargs)
    
    def list_available_models(self) -> list:
        """
        List available models in Ollama
        
        Returns:
            List of available model names
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [model["name"] for model in data.get("models", [])]
        except Exception as e:
            print(f"Error listing models: {e}")
        
        return []
    
    def set_model(self, model_name: str) -> bool:
        """
        Set the model to use for generation
        
        Args:
            model_name: Name of the model to use
            
        Returns:
            True if model is available, False otherwise
        """
        available_models = self.list_available_models()
        if model_name in available_models:
            self.model = model_name
            print(f"Switched to model: {model_name}")
            return True
        else:
            print(f"Model '{model_name}' not available")
            return False
