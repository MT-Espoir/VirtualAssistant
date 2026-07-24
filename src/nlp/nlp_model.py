import torch
from transformers import AutoTokenizer, AutoModel, pipeline
import os
import json
import numpy as np
import re

class NLPProcessor:
    def __init__(self):
        # Thư mục lưu trữ mô hình (tránh tải lại mỗi lần khởi động)
        self.models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
        os.makedirs(self.models_dir, exist_ok=True)
        
        # Khởi tạo các mô hình
        self.intent_model = None
        self.ner_model = None
        self.tokenizer = None
        
        # Tải mô hình intent classification
        self.load_intent_model()
        
        # Tải mô hình NER
        self.load_ner_model()
    
    def load_intent_model(self):
        """Tải mô hình phân loại ý định"""
        try:
            # Sử dụng PhoBERT hoặc XLM-RoBERTa được fine-tune cho tiếng Việt
            model_name = "vinai/phobert-base" 
            
            print(f"Đang tải mô hình intent classification: {model_name}")
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=self.models_dir)
            self.intent_model = AutoModel.from_pretrained(model_name, cache_dir=self.models_dir)
            
            # Tải ánh xạ intent từ file (để ánh xạ embedding sang intent)
            self.intent_mapping = self.load_intent_mapping()
            print("Đã tải xong mô hình intent classification")
        except Exception as e:
            print(f"Lỗi khi tải mô hình intent: {str(e)}")
            # Fallback to rule-based
            self.intent_model = None
    
    def load_ner_model(self):
        """Tải mô hình trích xuất thực thể"""
        try:
            # Sử dụng NER pipeline từ Hugging Face
            self.ner_model = pipeline("ner", model="Jean-Baptiste/roberta-large-ner-english", 
                                     cache_dir=self.models_dir)
            print("Đã tải xong mô hình NER")
        except Exception as e:
            print(f"Lỗi khi tải mô hình NER: {str(e)}")
            self.ner_model = None
    
    def load_intent_mapping(self):
        """Tải ánh xạ giữa embedding và intent"""
        mapping_file = os.path.join(self.models_dir, "intent_mapping.json")
        
        # Nếu file tồn tại, tải từ file
        if os.path.exists(mapping_file):
            with open(mapping_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # File không tồn tại, tạo mapping cơ bản
        return {
            "open_app": ["mở", "khởi động", "chạy", "bật", "kích hoạt"],
            "close_app": ["đóng", "tắt", "dừng", "ngừng"],
            "system_volume": ["âm lượng", "volume", "tiếng", "loa"],
            "system_brightness": ["độ sáng", "brightness", "màn hình"],
            "system_shutdown": ["tắt máy", "shutdown", "tắt nguồn", "tắt"],
            "system_restart": ["khởi động lại", "restart", "reboot"],
            "web_search": ["tìm kiếm", "search", "google"],
            "open_website": ["mở trang", "mở web", "vào trang"],
            "youtube_search": ["youtube", "tìm video", "xem video"]
        }
    
    # Từ khóa cho các ý định hội thoại (gộp từ intent_classifier cũ)
    CONVERSATION_INTENT_KEYWORDS = {
        "greeting": ["xin chào", "chào", "hello", "hi", "hey",
                     "good morning", "good afternoon", "good evening"],
        "goodbye": ["tạm biệt", "bye", "goodbye", "see you", "chào nhé", "hẹn gặp lại"],
        "thanks": ["cảm ơn", "cám ơn", "thank you", "thanks"],
        "personal": ["bạn là ai", "who are you", "tên bạn", "your name",
                     "bạn từ đâu", "where are you from"],
        "help": ["giúp", "help", "hướng dẫn", "instruction", "làm thế nào",
                 "how to", "có thể", "can you", "bạn làm gì", "what can you do"],
        "question_answering": ["thời tiết", "weather", "mấy giờ", "what time",
                               "ai là", "who is", "gì là", "what is",
                               "tại sao", "why", "như thế nào", "how"],
        "small_talk": ["thú vị", "interesting", "vui", "fun", "buồn", "sad",
                       "hạnh phúc", "happy", "mệt", "tired", "khỏe", "healthy",
                       "bạn có", "do you"],
        "conversation": ["bạn thế nào", "hôm nay", "trời đẹp", "kể cho tôi",
                         "tell me about", "bạn nghĩ gì", "what do you think",
                         "ý kiến", "opinion"],
    }

    def classify_intent(self, text):
        """Phân loại ý định từ văn bản đầu vào"""
        text = text.lower()

        # Ưu tiên nhận diện các ý định hội thoại trước (greeting, goodbye, ...)
        # Từ khóa 1 chữ khớp theo token để tránh khớp nhầm ("hi" trong "chi tiết");
        # cụm nhiều chữ vẫn khớp theo substring.
        words = set(re.findall(r"\w+", text, flags=re.UNICODE))
        for intent, keywords in self.CONVERSATION_INTENT_KEYWORDS.items():
            for keyword in keywords:
                if " " in keyword:
                    if keyword in text:
                        return intent
                elif keyword in words:
                    return intent

        # Thêm phân loại ý định tìm kiếm trên trang web cụ thể
        search_patterns = [
            r"tìm\s+(.+)\s+trên\s+(\w+)",
            r"search\s+(.+)\s+on\s+(\w+)",
            r"tìm kiếm\s+(.+)\s+trên\s+(\w+)",
            r"tìm\s+.*\s+(\w+)\s+cho\s+(.+)"
        ]
        
        for pattern in search_patterns:
            if re.search(pattern, text):
                return "search_on_site"
        
        # Xử lý đặc biệt cho lệnh mở trang web
        text_lower = text.lower()
        web_prefixes = ["mở trang", "mở web", "vào trang", "truy cập", "vào web"]
        
        # Nếu text bắt đầu bằng một trong những prefix mở web
        for prefix in web_prefixes:
            if prefix in text_lower:
                return "open_website"
        
        # Tiếp tục với thuật toán hiện tại cho các trường hợp khác
        best_intent = "unknown"
        highest_score = -1
        
        for intent, keywords in self.intent_mapping.items():
            score = sum(1 for keyword in keywords if keyword in text_lower)
            if score > highest_score:
                highest_score = score
                best_intent = intent
        
        return best_intent
    
    def extract_entities(self, text, intent_type=None):
        """Trích xuất thực thể dựa trên ý định"""
        text = text.lower()
        
        if intent_type == "search_on_site":
            # Trích xuất site và query
            patterns = [
                r"tìm\s+(.+)\s+trên\s+(\w+)",
                r"search\s+(.+)\s+on\s+(\w+)",
                r"tìm kiếm\s+(.+)\s+trên\s+(\w+)",
                r"tìm\s+.*\s+(\w+)\s+cho\s+(.+)"
            ]
            
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    # Đảm bảo thứ tự đúng dựa trên mẫu regex
                    if "cho" in pattern:
                        site = match.group(1)
                        query = match.group(2)
                    else:
                        query = match.group(1)
                        site = match.group(2)
                    
                    return {"site": site, "query": query}
            
            # Nếu không khớp với pattern nào
            words = text.split()
            site_keywords = ["trên", "on", "in", "at", "using"]
            
            for keyword in site_keywords:
                if keyword in words:
                    idx = words.index(keyword)
                    if idx + 1 < len(words):
                        site = words[idx + 1]
                        # Xây dựng query bằng cách loại bỏ từ khóa và site
                        query_words = words.copy()
                        if idx + 1 < len(query_words):
                            del query_words[idx:idx+2]
                        query = " ".join(query_words)
                        query = re.sub(r"tìm\s+|search\s+|looking for\s+", "", query).strip()
                        return {"site": site, "query": query}
            
            return {"site": "", "query": ""}
        
        if intent_type == "website_name":
            # Xử lý đặc biệt cho tên trang web
            text_lower = text.lower()
            web_prefixes = ["mở trang", "mở web", "vào trang", "truy cập", "vào web"]
            
            # Loại bỏ các prefix để lấy tên trang web
            for prefix in web_prefixes:
                if prefix in text_lower:
                    # Lấy phần còn lại sau prefix
                    website = text_lower.split(prefix)[1].strip()
                    # Làm sạch tên trang web
                    website = website.split()[0]  # Lấy từ đầu tiên sau prefix
                    return website
        
        # Xử lý các trường hợp khác bằng phương thức hiện có
        if not self.ner_model:
            from nlp.entity_extractor import extract_entity as rule_based_extract
            return rule_based_extract(text, intent_type)
        
        try:
            # Sử dụng NER model
            entities = self.ner_model(text)
            
            # Xử lý kết quả NER dựa vào intent_type
            if intent_type == "app_name":
                for entity in entities:
                    if entity['entity'] in ['B-ORG', 'I-ORG', 'B-MISC', 'I-MISC']:
                        return entity['word']
            
            elif intent_type == "website_name":
                for entity in entities:
                    if entity['entity'] in ['B-ORG', 'I-ORG', 'B-MISC', 'I-MISC']:
                        return entity['word']
            
            # Fallback to rule-based
            from nlp.entity_extractor import extract_entity as rule_based_extract
            return rule_based_extract(text, intent_type)
            
        except Exception as e:
            print(f"Error in NER model: {str(e)}")
            # Fallback to rule-based
            from nlp.entity_extractor import extract_entity as rule_based_extract
            return rule_based_extract(text, intent_type)
            
    def update_from_feedback(self, text, identified_intent, correct_intent, entities=None):
        """Cập nhật mô hình từ phản hồi của người dùng"""
        # Lưu dữ liệu huấn luyện
        training_data_file = os.path.join(self.models_dir, "training_data.jsonl")
        
        with open(training_data_file, 'a', encoding='utf-8') as f:
            data_point = {
                "text": text,
                "identified_intent": identified_intent,
                "correct_intent": correct_intent,
                "entities": entities
            }
            f.write(json.dumps(data_point, ensure_ascii=False) + '\n')
        
        # Cập nhật intent_mapping
        if correct_intent not in self.intent_mapping:
            self.intent_mapping[correct_intent] = []
            
        # Thêm từ khóa mới từ văn bản (đơn giản hóa)
        words = text.lower().split()
        for word in words:
            if len(word) > 3 and word not in self.intent_mapping[correct_intent]:
                self.intent_mapping[correct_intent].append(word)
                
        # Lưu intent_mapping cập nhật
        mapping_file = os.path.join(self.models_dir, "intent_mapping.json")
        with open(mapping_file, 'w', encoding='utf-8') as f:
            json.dump(self.intent_mapping, f, ensure_ascii=False, indent=2)