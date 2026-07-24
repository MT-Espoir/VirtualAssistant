import json
import os
import shutil
from datetime import datetime

class DataSaver:
    def __init__(self):
        self.data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "components", "data")
        self.training_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "training_data")
        # Tạo thư mục nếu chưa tồn tại
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.training_dir, exist_ok=True)
    
    def save_data(self, filename, data, backup=True):
        """Save data to JSON file with optional backup"""
        if data is None:
            print(f"No data provided for {filename}")
            return False
            
        file_path = os.path.join(self.data_dir, filename)
        
        try:
            # Tạo backup nếu file đã tồn tại
            if backup and os.path.exists(file_path):
                self._create_backup(file_path)
            
            # Lưu dữ liệu
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"Data saved successfully to {filename}")
            return True
            
        except Exception as e:
            print(f"Error saving data to {filename}: {str(e)}")
            return False
    
    def save_training_data(self, filename, data):
        """Save training data to training_data directory"""
        if data is None:
            print(f"No training data provided for {filename}")
            return False
            
        file_path = os.path.join(self.training_dir, filename)
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                if filename.endswith('.jsonl'):
                    # Lưu từng dòng cho JSONL
                    for item in data:
                        json.dump(item, f, ensure_ascii=False)
                        f.write('\n')
                else:
                    # Lưu JSON thông thường
                    json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"Training data saved successfully to {filename}")
            return True
            
        except Exception as e:
            print(f"Error saving training data to {filename}: {str(e)}")
            return False
    
    def save_user_data(self, user_id, data_type, data):
        """Save user-specific data"""
        user_dir = os.path.join(self.data_dir, "user_data")
        os.makedirs(user_dir, exist_ok=True)
        
        filename = f"{user_id}_{data_type}.json"
        file_path = os.path.join(user_dir, filename)
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"User data saved successfully to {filename}")
            return True
            
        except Exception as e:
            print(f"Error saving user data to {filename}: {str(e)}")
            return False
    
    def _create_backup(self, file_path):
        """Create backup of existing file"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{file_path}.backup_{timestamp}"
            shutil.copy2(file_path, backup_name)
            print(f"Backup created: {backup_name}")
        except Exception as e:
            print(f"Error creating backup: {str(e)}")
    
    def append_to_file(self, filename, data):
        """Append data to existing JSON file (for arrays)"""
        file_path = os.path.join(self.data_dir, filename)
        
        try:
            # Đọc dữ liệu hiện có
            existing_data = []
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            
            # Thêm dữ liệu mới
            if isinstance(existing_data, list):
                existing_data.append(data)
            else:
                existing_data = [existing_data, data]
            
            # Lưu lại
            return self.save_data(filename, existing_data, backup=False)
            
        except Exception as e:
            print(f"Error appending to {filename}: {str(e)}")
            return False
        