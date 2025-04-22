# Tạo dữ liệu huấn luyện
from src.utils.data_generator import generate_training_data
generate_training_data()

# Khởi tạo mô hình NLP và hồ sơ người dùng
from nlp.nlp_model import NLPProcessor
from user.user_profile import UserProfile

nlp_processor = NLPProcessor()
user_profile = UserProfile()