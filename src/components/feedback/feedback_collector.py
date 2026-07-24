import json
import os
from datetime import datetime
from nlp.nlp_model import NLPProcessor
class FeedbackCollector:
    def __init__(self):
        self.data_dir = os.path.join(os.path.dirname(__file__), "feedback_data")
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.feedback_file = os.path.join(self.data_dir, "user_feedback.jsonl")
    
    def collect_feedback(self, command_text, predicted_intent, actual_intent=None, 
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
    
    def ask_for_correction(self, command_text, predicted_intent, predicted_entities=None):
        """Yêu cầu người dùng sửa lỗi (chỉ hiển thị UI)"""
        print(f"\nPhát hiện lệnh: '{command_text}'")
        print(f"Dự đoán ý định: {predicted_intent}")
        if predicted_entities:
            print(f"Dự đoán thực thể: {predicted_entities}")
            
        print("\nLệnh này có đúng không? (Y/n)")
        user_input = input().lower()
        
        if user_input == 'n':
            print("Vui lòng nhập ý định đúng:")
            actual_intent = input().strip()
            
            # Thu thập phản hồi
            self.collect_feedback(
                command_text=command_text,
                predicted_intent=predicted_intent,
                actual_intent=actual_intent,
                predicted_entities=predicted_entities
            )
            
            # Cập nhật mô hình
            NLPProcessor.update_from_feedback(command_text, predicted_intent, actual_intent)
            
            return actual_intent
        
        return predicted_intent