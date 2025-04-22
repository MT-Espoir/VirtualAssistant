import os
import json
import time
from datetime import datetime

class UserProfile:
    def __init__(self, user_id="default"):
        self.user_id = user_id
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "user_data")
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.profile_path = os.path.join(self.data_dir, f"{user_id}_profile.json")
        self.command_history_path = os.path.join(self.data_dir, f"{user_id}_commands.json")
        
        # Tải hoặc tạo mới profile
        self.profile = self.load_profile()
        
        # Tải lịch sử lệnh
        self.command_history = self.load_command_history()
        
        # Lưu các cài đặt ưa thích
        self.preferences = self.profile.get("preferences", {})
        
        # Lưu các ứng dụng thường dùng
        self.frequent_apps = self.profile.get("frequent_apps", {})
        
        # Lưu các website thường dùng
        self.frequent_sites = self.profile.get("frequent_sites", {})
        
    def load_profile(self):
        """Tải hồ sơ người dùng"""
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                print("Không thể đọc hồ sơ người dùng, tạo mới...")
        
        # Tạo hồ sơ mới nếu không tồn tại
        profile = {
            "user_id": self.user_id,
            "created_at": datetime.now().isoformat(),
            "preferences": {},
            "frequent_apps": {},
            "frequent_sites": {},
            "language": "vi",
            "daily_stats": {}
        }
        
        # Lưu hồ sơ mới
        self.save_profile(profile)
        return profile
        
    def load_command_history(self):
        """Tải lịch sử lệnh"""
        if os.path.exists(self.command_history_path):
            try:
                with open(self.command_history_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                print("Không thể đọc lịch sử lệnh, tạo mới...")
        
        return []
    
    def save_profile(self, profile=None):
        """Lưu hồ sơ người dùng"""
        if profile is None:
            profile = self.profile
            
        with open(self.profile_path, 'w', encoding='utf-8') as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
    
    def save_command_history(self):
        """Lưu lịch sử lệnh"""
        with open(self.command_history_path, 'w', encoding='utf-8') as f:
            json.dump(self.command_history, f, ensure_ascii=False, indent=2)
    
    def add_command(self, command_text, intent, entities, success):
        """Thêm lệnh vào lịch sử"""
        command = {
            "text": command_text,
            "intent": intent,
            "entities": entities,
            "timestamp": datetime.now().isoformat(),
            "success": success
        }
        
        # Thêm vào lịch sử
        self.command_history.append(command)
        
        # Giới hạn lịch sử tới 1000 lệnh
        if len(self.command_history) > 1000:
            self.command_history = self.command_history[-1000:]
            
        # Cập nhật thống kê
        self.update_stats(command)
        
        # Lưu lịch sử
        self.save_command_history()
        
    def update_stats(self, command):
        """Cập nhật thống kê dựa trên lệnh mới"""
        intent = command.get("intent")
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Cập nhật thống kê hàng ngày
        if today not in self.profile["daily_stats"]:
            self.profile["daily_stats"][today] = {"total_commands": 0, "intents": {}}
            
        self.profile["daily_stats"][today]["total_commands"] += 1
        
        if intent:
            if intent not in self.profile["daily_stats"][today]["intents"]:
                self.profile["daily_stats"][today]["intents"][intent] = 0
            self.profile["daily_stats"][today]["intents"][intent] += 1
        
        # Cập nhật ứng dụng thường dùng
        if intent == "open_app" and "app_name" in command.get("entities", {}):
            app_name = command["entities"]["app_name"]
            if app_name not in self.frequent_apps:
                self.frequent_apps[app_name] = 0
            self.frequent_apps[app_name] += 1
            
        # Cập nhật website thường dùng
        if intent == "open_website" and "website_name" in command.get("entities", {}):
            site_name = command["entities"]["website_name"]
            if site_name not in self.frequent_sites:
                self.frequent_sites[site_name] = 0
            self.frequent_sites[site_name] += 1
            
        # Cập nhật profile
        self.profile["frequent_apps"] = self.frequent_apps
        self.profile["frequent_sites"] = self.frequent_sites
        
        # Lưu profile
        self.save_profile()
    
    def get_suggestion(self, partial_command):
        """Gợi ý lệnh dựa trên lịch sử"""
        suggestions = []
        partial_command = partial_command.lower()
        
        # Tìm các lệnh tương tự trong lịch sử
        for cmd in self.command_history:
            if cmd["text"].lower().startswith(partial_command):
                suggestions.append(cmd["text"])
                
        # Loại bỏ trùng lặp và giới hạn số lượng gợi ý
        return list(set(suggestions))[:5]
    
    def get_preferred_app(self, category=None):
        """Lấy ứng dụng ưa thích dựa trên lịch sử"""
        if not self.frequent_apps:
            return None
            
        # Nếu không có category, trả về ứng dụng phổ biến nhất
        if not category:
            return max(self.frequent_apps, key=self.frequent_apps.get)
            
        # Thêm logic cho category nếu cần
        
    def set_preference(self, key, value):
        """Thiết lập tùy chọn người dùng"""
        self.preferences[key] = value
        self.profile["preferences"] = self.preferences
        self.save_profile()
        
    def get_preference(self, key, default=None):
        """Lấy tùy chọn người dùng"""
        return self.preferences.get(key, default)