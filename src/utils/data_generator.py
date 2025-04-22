import json
import os
import random

def generate_training_data():
    """Tạo dữ liệu huấn luyện ban đầu"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "training_data")
    os.makedirs(data_dir, exist_ok=True)
    
    output_file = os.path.join(data_dir, "training_data.jsonl")
    
    # Mẫu câu lệnh theo ý định
    intent_samples = {
        "open_app": [
            "mở {app}",
            "khởi động {app}",
            "chạy {app}",
            "bật {app} lên",
            "mở ứng dụng {app}",
            "open {app}",
            "start {app}",
            "run {app}",
            "launch {app}"
        ],
        "close_app": [
            "đóng {app}",
            "tắt {app}",
            "dừng {app}",
            "ngừng {app}",
            "close {app}",
            "quit {app}",
            "exit {app}",
            "stop {app}"
        ],
        "system_volume": [
            "tăng âm lượng lên {number}%",
            "giảm âm lượng xuống {number}%",
            "đặt âm lượng {number}%",
            "âm lượng {number}%",
            "tăng âm lượng",
            "giảm âm lượng",
            "increase volume to {number}%",
            "decrease volume to {number}%",
            "set volume to {number}%"
        ]
    }
    
    # Thực thể để thay thế
    entities = {
        "app": ["notepad", "chrome", "firefox", "word", "excel", "calculator", "paint",
                "explorer", "cmd", "spotify", "edge"],
        "number": ["10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]
    }
    
    # Tạo dữ liệu
    training_data = []
    
    for intent, templates in intent_samples.items():
        # Tạo 50 mẫu cho mỗi intent
        for _ in range(50):
            template = random.choice(templates)
            text = template
            
            # Thay thế thực thể
            for entity_type, values in entities.items():
                if f"{{{entity_type}}}" in text:
                    entity_value = random.choice(values)
                    text = text.replace(f"{{{entity_type}}}", entity_value)
            
            # Tạo mẫu dữ liệu
            data_point = {
                "text": text,
                "intent": intent
            }
            
            training_data.append(data_point)
    
    # Lưu dữ liệu
    with open(output_file, 'w', encoding='utf-8') as f:
        for data_point in training_data:
            f.write(json.dumps(data_point, ensure_ascii=False) + '\n')
            
    print(f"Đã tạo {len(training_data)} mẫu dữ liệu huấn luyện")
    return training_data

