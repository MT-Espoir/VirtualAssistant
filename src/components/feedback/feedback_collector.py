import json
import os
from datetime import datetime


class FeedbackCollector:
    def __init__(self):
        self.data_dir = os.path.join(os.path.dirname(__file__), "feedback_data")
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.feedback_file = os.path.join(self.data_dir, "user_feedback.jsonl")
    
    def collect_feedback(self, command_text, predicted_intent=None, actual_intent=None,
                        predicted_entities=None, actual_entities=None, satisfaction_score=None,
                        comment=None):
        """Thu thập phản hồi từ người dùng"""
        feedback = {
            "timestamp": datetime.now().isoformat(),
            "command_text": command_text,
            "predicted_intent": predicted_intent,
            "actual_intent": actual_intent,
            "predicted_entities": predicted_entities,
            "actual_entities": actual_entities,
            "satisfaction_score": satisfaction_score,
            "comment": comment
        }
        
        # Lưu phản hồi
        with open(self.feedback_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(feedback, ensure_ascii=False) + '\n')
            
        return True