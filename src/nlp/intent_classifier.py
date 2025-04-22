class IntentClassifier:
    def __init__(self):
        # Initialize the intent classifier
        pass

    def train(self, training_data):
        # Train the classifier with the provided training data
        pass

    def load_model(self, model_path):
        # Load a pre-trained model from the specified path
        pass

    def save_model(self, model_path):
        # Save the current model to the specified path
        pass

def classify_intent(text):
    """Phân loại ý định từ văn bản"""
    text = text.lower()
    
    # Xử lý các trường hợp tắt máy và khởi động lại trước tiên
    if "tắt máy" in text or "shutdown" in text:
        return "system_shutdown"
        
    if "khởi động lại" in text or "restart" in text:
        return "system_restart"
    
    # Thêm từ khóa cho việc mở website
    open_website_keywords = ["mở trang", "mở website", "truy cập", "vào trang", "open website", "go to", "visit"]
    
    # Từ khóa cho mở/đóng ứng dụng
    open_app_keywords = ["mở", "chạy", "khởi động", "open", "run", "start", "launch"]
    close_app_keywords = ["đóng", "tắt", "dừng", "close", "exit", "quit"]
    
    # Từ khóa cho điều khiển hệ thống
    system_keywords = ["volume", "brightness", "âm lượng", "độ sáng"]
    
    # Từ khóa cho thao tác tập tin
    file_keywords = ["save", "open file", "create folder", "delete", "lưu", "mở tệp", "tạo thư mục", "xóa"]
    
    # Từ khóa cho tìm kiếm
    search_keywords = ["search", "find", "look for", "tìm kiếm", "tìm", "google"]
    
    # Thêm từ khóa cho việc tìm và phát video YouTube
    youtube_search_keywords = ["tìm video", "tìm trên youtube", "phát nhạc", "mở bài hát", 
                             "play video", "search youtube", "play song", "tìm bài hát"]
    
    # Xác định intent mở website
    if any(keyword in text for keyword in open_website_keywords):
        return "open_website"
    
    # Kiểm tra tên trang web phổ biến trực tiếp sau từ "mở"
    website_names = ["youtube", "facebook", "google", "gmail", "twitter", "instagram"]
    for name in website_names:
        if f"mở {name}" in text or f"open {name}" in text:
            return "open_website"
    
    # Phân loại dựa trên từ khóa
    if any(keyword in text for keyword in system_keywords):
        if "volume" in text or "âm lượng" in text:
            return "system_volume"
        elif "brightness" in text or "độ sáng" in text:
            return "system_brightness"
        return "system_control"
    
    # Xác định intent tìm video YouTube
    if any(keyword in text for keyword in youtube_search_keywords) and "youtube" in text:
        return "youtube_search"
    
    # Hoặc nếu đã mở YouTube rồi và đang yêu cầu tìm kiếm
    if ("tìm" in text or "search" in text or "play" in text or "phát" in text or "mở" in text) and "youtube" in text:
        return "youtube_search"
    
    elif any(keyword in text for keyword in search_keywords):
        return "web_search"
    elif any(keyword in text for keyword in file_keywords):
        return "file_operation"
    elif any(keyword in text for keyword in open_app_keywords):
        return "open_app"
    elif any(keyword in text for keyword in close_app_keywords):
        return "close_app"
    
    return "unknown"