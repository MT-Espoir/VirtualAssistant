import json
import os
import re
import random
from collections import Counter
from datetime import datetime
from utils.data_loader import DataLoader

# Import AI enhancer (optional - will fallback if not available)
# LƯU Ý: các module lightweight_ai_enhancer / ai_personality_enhancer hiện chưa có
# trong repo (mất source). try/except dưới đây đảm bảo module vẫn chạy ở chế độ
# rule-based khi không tìm thấy chúng. Module này hiện là thành phần thử nghiệm,
# CHƯA được wire vào main.py.
try:
    from .lightweight_ai_enhancer import create_ai_enhancer
    AI_AVAILABLE = True
except ImportError:
    try:
        # Fallback to full AI enhancer if available
        from .ai_personality_enhancer import AIPersonalityEnhancer
        AI_AVAILABLE = True
    except ImportError:
        AI_AVAILABLE = False
        print("AI enhancer not available. Using rule-based system only.")

class PersonalityLearner:
    def __init__(self, use_ai=True, ai_model_tier="phi2_optimized"):
        self.question_asked_today = []
        self.daily_stats = {}
        self.learning_data = {}
        self.data_loader = DataLoader()
        self.question_data = self.data_loader.conversation_data
        self.conversation_history = []
        
        # AI Enhancement with Phi-2
        self.use_ai = use_ai and AI_AVAILABLE
        self.ai_enhancer = None
        self.ai_model_tier = ai_model_tier
        
        if self.use_ai:
            try:
                print(f"Initializing Phi-2 AI enhancer (tier: {ai_model_tier})...")
                
                # Try lightweight enhancer with Phi-2 (recommended for your hardware)
                if 'create_ai_enhancer' in globals():
                    self.ai_enhancer = create_ai_enhancer(model_tier=ai_model_tier)
                    print("✅ Phi-2 AI enhancer ready!")
                    print(f"📊 Model info: {self.ai_enhancer.get_model_info()}")
                else:
                    # Fallback to full enhancer
                    self.ai_enhancer = AIPersonalityEnhancer()
                    print("✅ Full AI enhancer ready!")
                    
            except Exception as e:
                print(f"Failed to initialize Phi-2 enhancer: {e}")
                print("🔄 Falling back to rule-based system")
                self.use_ai = False
        
    def get_daily_question(self, data, keys, default=None):
        """
        Get value from nested dict using list of keys
        keys: ['daily_learning', 'question_pool', 'personal']
        """
        current = data
        try:
            for key in keys:
                current = current[key]
            return current
        except (KeyError, TypeError):
            return default
        
    def get_random_question(self):
        """
        Randomly select a value from a nested dict using list of keys
        keys: ['daily_learning', 'question_pool', 'personal']
        """
        path_to_categories = ['daily_learning', 'question_categories']
        available_categories = self.get_daily_question(self.question_data, path_to_categories, default=[])
        if not available_categories:
            print("Không còn lựa chọn nào khả dụng")
            return None, None
        
        selected_category = random.choice(available_categories)
        path_to_questions = ['daily_learning', 'question_pool', selected_category]
        items = self.get_daily_question(self.question_data, path_to_questions, default=[])

        if not items:
            print(f"Lưu ý: Danh mục '{selected_category}' không có câu hỏi nào.")
            return selected_category, None # Có danh mục nhưng không có câu hỏi
            
        selected_item = random.choice(items)
        
        return selected_category, selected_item

    def check_asked_question(self,question):
        """Kiểm tra xem câu hỏi đã được hỏi trong ngày chưa"""
        if question in self.question_asked_today:
            return True
        else:
            self.question_asked_today.append(question)
            return False
    #====================================================================================#

    #====================================================================================#
    def preprocess_text(self, text):
        """Tiền xử lý văn bản: loại bỏ ký tự đặc biệt, chuyển sang chữ thường"""
        self.stopwords = {
            'tôi', 'bạn', 'là', 'của', 'và', 'có', 'trong', 'để', 'với', 
            'một', 'này', 'đó', 'được', 'cho', 'từ', 'những', 'các',
            'không', 'khi', 'họ', 'nó', 'sẽ', 'đã', 'bị', 'hay'
        }
        if not text:
            print("Văn bản rỗng, không thể tiền xử lý.")
            return False
        text = text.lower()
        text = re.sub(r'[^\w\s]', '', text)  # Loại bỏ

        words = text.split()
        filtered_words = [word for word in words if word not in self.stopwords and len(word) > 1]

        return filtered_words

    def extract_keywords(self, text, top_n=7):
        """Trích xuất từ khóa từ văn bản"""
        if not text:
            print("Văn bản rỗng, không thể trích xuất từ khóa.")
            return []
        
        words = self.preprocess_text(text)
        if not words:
            print("Không có từ khóa hợp lệ sau khi tiền xử lý.")
            return []
        
        word_freqs = Counter(words)
        return word_freqs.most_common(top_n)

#====================================================================================#
                                # IN DEVELOPMENT #
#====================================================================================#
    def predict_music_genre(self, text):
        """Dự đoán thể loại âm nhạc từ văn bản"""
        if not text:
            print("Văn bản rỗng, không thể dự đoán thể loại âm nhạc.")
            return None
        
        keywords = self.extract_keywords(text)
        if not keywords:
            print("Không có từ khóa hợp lệ để dự đoán thể loại âm nhạc.")
            return None
        
        # Giả sử ta có một hàm hoặc mô hình để dự đoán thể loại âm nhạc
        # Ở đây ta chỉ trả về từ khóa đầu tiên như một ví dụ
        return keywords[0][0] if keywords else None

    def detect_music_preferences(self, text):
        """Phát hiện sở thích âm nhạc từ văn bản"""
        if not text:
            return {}
        
        # Dictionary các thể loại nhạc và từ khóa liên quan
        music_genres = {
            'pop': ['pop', 'taylor swift', 'ariana grande', 'justin bieber', 'catchy', 'mainstream'],
            'rock': ['rock', 'guitar', 'band', 'metal', 'heavy', 'drums', 'electric'],
            'hip_hop': ['rap', 'hip hop', 'beat', 'rhyme', 'eminem', 'drake', 'rhythm'],
            'classical': ['classical', 'symphony', 'orchestra', 'piano', 'violin', 'mozart', 'beethoven'],
            'jazz': ['jazz', 'swing', 'blues', 'saxophone', 'trumpet', 'improvisation'],
            'electronic': ['electronic', 'edm', 'techno', 'house', 'synth', 'dj', 'remix'],
            'country': ['country', 'folk', 'acoustic', 'banjo', 'rural', 'traditional'],
            'r_and_b': ['r&b', 'soul', 'smooth', 'vocal', 'groove', 'rhythm and blues']
        }
        
        # Mood-based preferences
        mood_preferences = {
            'energetic': ['upbeat', 'energetic', 'fast', 'dancing', 'party', 'workout'],
            'relaxing': ['chill', 'relaxing', 'calm', 'peaceful', 'meditation', 'spa'],
            'emotional': ['emotional', 'sad', 'heartbreak', 'love', 'feelings', 'deep'],
            'motivational': ['motivational', 'inspiring', 'powerful', 'strength', 'confidence']
        }
        
        keywords = [word.lower() for word, _ in self.extract_keywords(text, top_n=10)]
        text_lower = text.lower()
        
        preferences = {
            'genres': {},
            'moods': {},
            'artists': [],
            'instruments': []
        }
        
        # Detect genres
        for genre, genre_keywords in music_genres.items():
            score = sum(1 for keyword in genre_keywords if keyword in text_lower)
            if score > 0:
                preferences['genres'][genre] = score
        
        # Detect moods
        for mood, mood_keywords in mood_preferences.items():
            score = sum(1 for keyword in mood_keywords if keyword in text_lower)
            if score > 0:
                preferences['moods'][mood] = score
        
        # Simple artist detection (can be expanded)
        common_artists = ['taylor swift', 'ariana grande', 'justin bieber', 'eminem', 'drake', 
                         'beyonce', 'adele', 'ed sheeran', 'bruno mars', 'billie eilish']
        for artist in common_artists:
            if artist in text_lower:
                preferences['artists'].append(artist)
        
        # Instrument detection
        instruments = ['guitar', 'piano', 'violin', 'drums', 'saxophone', 'trumpet', 'bass']
        for instrument in instruments:
            if instrument in text_lower:
                preferences['instruments'].append(instrument)
        
        return preferences

#====================================================================================#

#====================================================================================#
    def scoring_emotional_stat(self, text):
        """Dự đoán điểm cảm xúc từ văn bản"""
        if not text:
            return 0
            
        # Dictionary ánh xạ từ khóa với điểm cảm xúc
        emotional_keywords = {
            # Positive emotions (+1 to +3)
            'tuyệt vời': 3, 'xuất sắc': 3, 'hoàn hảo': 3, 'tốt': 2, 'vui': 2,
            'hạnh phúc': 2, 'thích': 2, 'yêu': 2, 'tích cực': 2, 'hào hứng': 2,
            'phấn khích': 2, 'ổn': 1, 'được': 1, 'ok': 1, 'bình thường': 1,
            
            # Negative emotions (-1 to -3)
            'tệ': -3, 'kinh khủng': -3, 'ghét': -3, 'buồn': -2, 'tức giận': -2,
            'bực': -2, 'thất vọng': -2, 'chán': -2, 'khó chịu': -2, 'tồi tệ': -2,
            'không thích': -1, 'không tốt': -1, 'kém': -1
        }
        
        keywords = self.extract_keywords(text, top_n=10)
        total_score = 0
        word_count = 0
        
        for word, freq in keywords:
            if word in emotional_keywords:
                total_score += emotional_keywords[word] * freq
                word_count += freq
        
        # Chuẩn hóa điểm về thang -5 đến +5
        if word_count > 0:
            normalized_score = max(-5, min(5, total_score / word_count))
        else:
            normalized_score = 0
            
        return round(normalized_score, 2)

    def detect_emotional_tone(self, text):
        """Phát hiện tông cảm xúc từ văn bản"""
        if not text:
            return "neutral"
            
        emotional_categories = {
            'happy': ['vui', 'hạnh phúc', 'tuyệt vời', 'tốt', 'thích', 'yêu', 'hào hứng'],
            'sad': ['buồn', 'tệ', 'thất vọng', 'chán', 'không vui', 'u sầu'],
            'angry': ['tức giận', 'bực', 'khó chịu', 'ghét', 'điên', 'cáu'],
            'excited': ['phấn khích', 'hào hứng', 'thú vị', 'tuyệt', 'xuất sắc'],
            'calm': ['bình tĩnh', 'thư giãn', 'yên tĩnh', 'ổn định', 'bình thường'],
            'anxious': ['lo lắng', 'căng thẳng', 'stress', 'áp lực', 'bồn chồn']
        }
        
        keywords = [word.lower() for word, _ in self.extract_keywords(text, top_n=15)]
        emotion_scores = {}
        
        for emotion, emotion_words in emotional_categories.items():
            score = sum(1 for word in keywords if word in emotion_words)
            if score > 0:
                emotion_scores[emotion] = score
        
        if not emotion_scores:
            return "neutral"
            
        # Trả về emotion có điểm cao nhất
        dominant_emotion = max(emotion_scores, key=emotion_scores.get)
        
        # Nếu có nhiều emotions với điểm bằng nhau, trả về mixed
        max_score = emotion_scores[dominant_emotion]
        tied_emotions = [emotion for emotion, score in emotion_scores.items() if score == max_score]
        
        if len(tied_emotions) > 1:
            return "mixed"
        
        return dominant_emotion

    def analyzer_user_response(self, user_response):
        """Phân tích và lưu trữ đặc điểm cá tính"""
        if not user_response:
            return {}
        
        analysis_result = {
            'timestamp': datetime.now().isoformat(),
            'response_length': len(user_response.split()),
            'emotional_score': self.scoring_emotional_stat(user_response),
            'emotional_tone': self.detect_emotional_tone(user_response),
            'keywords': self.extract_keywords(user_response, top_n=5),
            'communication_style': self._analyze_communication_style(user_response),
            'politeness_level': self._analyze_politeness(user_response)
        }
        
        # Lưu vào learning_data để tracking theo thời gian
        today = datetime.now().strftime('%Y-%m-%d')
        if today not in self.learning_data:
            self.learning_data[today] = []
        
        self.learning_data[today].append(analysis_result)
        
        return analysis_result
    
    def _analyze_communication_style(self, text):
        """Phân tích style giao tiếp: formal vs informal"""
        formal_indicators = ['xin chào', 'cảm ơn', 'xin lỗi', 'vui lòng', 'kính thưa']
        informal_indicators = ['hi', 'hey', 'ok', 'oki', 'yeah', 'ừm', 'uhm']
        
        text_lower = text.lower()
        formal_count = sum(1 for indicator in formal_indicators if indicator in text_lower)
        informal_count = sum(1 for indicator in informal_indicators if indicator in text_lower)
        
        if formal_count > informal_count:
            return "formal"
        elif informal_count > formal_count:
            return "informal"
        else:
            return "mixed"
    
    def _analyze_politeness(self, text):
        """Phân tích mức độ lịch sự (0-10)"""
        polite_words = ['cảm ơn', 'xin lỗi', 'vui lòng', 'xin chào', 'chào', 'thanks', 'please']
        text_lower = text.lower()
        
        politeness_score = 0
        for word in polite_words:
            if word in text_lower:
                politeness_score += 2
        
        # Chuẩn hóa về thang 0-10
        return min(10, politeness_score)

    #====================================================================================#
    
    #====================================================================================#    
    def update_personality_profile(self, user_response):
        """Update personality profile based on user response"""
        analysis = self.analyzer_user_response(user_response)
        
        # Initialize profile if not exists
        if 'personality_profile' not in self.daily_stats:
            self.daily_stats['personality_profile'] = {
                'communication_style': {'formal': 0, 'informal': 0, 'mixed': 0},
                'avg_response_length': 0,
                'total_responses': 0,
                'emotional_patterns': {
                    'happy': 0, 'sad': 0, 'angry': 0, 'excited': 0, 
                    'calm': 0, 'anxious': 0, 'neutral': 0, 'mixed': 0
                },
                'avg_politeness': 0,
                'avg_emotional_score': 0,
                'interest_topics': {},
                'last_updated': datetime.now().isoformat()
            }
        
        profile = self.daily_stats['personality_profile']
        
        # Update communication style
        style = analysis.get('communication_style', 'mixed')
        profile['communication_style'][style] += 1
        
        # Update average response length
        current_length = analysis.get('response_length', 0)
        total_responses = profile['total_responses']
        profile['avg_response_length'] = (
            (profile['avg_response_length'] * total_responses + current_length) / 
            (total_responses + 1)
        )
        
        # Update emotional patterns
        emotional_tone = analysis.get('emotional_tone', 'neutral')
        profile['emotional_patterns'][emotional_tone] += 1
        
        # Update averages
        profile['avg_politeness'] = (
            (profile['avg_politeness'] * total_responses + analysis.get('politeness_level', 0)) /
            (total_responses + 1)
        )
        
        profile['avg_emotional_score'] = (
            (profile['avg_emotional_score'] * total_responses + analysis.get('emotional_score', 0)) /
            (total_responses + 1)
        )
        
        # Update interest topics based on keywords
        keywords = analysis.get('keywords', [])
        for keyword, freq in keywords:
            if keyword in profile['interest_topics']:
                profile['interest_topics'][keyword] += freq
            else:
                profile['interest_topics'][keyword] = freq
        
        # Update counters
        profile['total_responses'] += 1
        profile['last_updated'] = datetime.now().isoformat()
        
        return profile

    def generate_personalized_response(self, user_input):
        """Tạo response theo style của user - AI Enhanced"""
        
        # Update conversation history
        self._update_conversation_history(user_input, None)  # Response will be added later
        
        # Check if we have personality profile
        if 'personality_profile' not in self.daily_stats:
            default_response = "Xin chào! Tôi đang học cách hiểu bạn tốt hơn."
            self._update_conversation_history(user_input, default_response)
            return default_response
        
        profile = self.daily_stats['personality_profile']
        
        # Try AI-powered response first
        if self.use_ai and self.ai_enhancer:
            try:
                ai_response = self.ai_enhancer.generate_personality_response(
                    user_input=user_input,
                    personality_profile=profile,
                    conversation_history=self.conversation_history[-5:]  # Last 5 exchanges
                )
                
                if ai_response and len(ai_response.strip()) > 0:
                    self._update_conversation_history(user_input, ai_response)
                    return ai_response
                    
            except Exception as e:
                print(f"AI response generation failed: {e}")
        
        # Fallback to rule-based response
        rule_based_response = self._generate_rule_based_response(user_input, profile)
        self._update_conversation_history(user_input, rule_based_response)
        return rule_based_response
    
    def _generate_rule_based_response(self, user_input, profile):
        """Original rule-based response generation (as fallback)"""
        
        # Determine dominant communication style
        style_counts = profile['communication_style']
        dominant_style = max(style_counts, key=style_counts.get)
        
        # Determine dominant emotion
        emotion_counts = profile['emotional_patterns']
        dominant_emotion = max(emotion_counts, key=emotion_counts.get)
        
        # Generate response based on style and emotion
        response_templates = {
            'formal': {
                'happy': ["Tôi rất vui khi thấy bạn hạnh phúc!", "Thật tuyệt vời khi bạn cảm thấy tích cực!"],
                'sad': ["Tôi hiểu bạn đang buồn. Tôi ở đây để hỗ trợ bạn.", "Hy vọng mọi thứ sẽ tốt hơn cho bạn."],
                'excited': ["Tôi cảm nhận được sự hào hứng của bạn!", "Thật tuyệt khi bạn cảm thấy phấn khích!"],
                'default': ["Cảm ơn bạn đã chia sẻ với tôi.", "Tôi luôn sẵn sàng lắng nghe bạn."]
            },
            'informal': {
                'happy': ["Hay quá! Bạn có vẻ vui nhỉ!", "Tuyệt vời! Mình thích thấy bạn vui vậy!"],
                'sad': ["Ôi, bạn buồn à? Mình ở đây nè!", "Đừng buồn nhé, mọi thứ sẽ ổn thôi."],
                'excited': ["Wow! Bạn hào hứng quá đi!", "Yeah! Mình cũng excited luôn!"],
                'default': ["Oki, mình hiểu rồi!", "Thanks bạn đã share nhé!"]
            }
        }
        
        # Select appropriate template
        if dominant_style in response_templates:
            if dominant_emotion in response_templates[dominant_style]:
                templates = response_templates[dominant_style][dominant_emotion]
            else:
                templates = response_templates[dominant_style]['default']
        else:
            templates = ["Cảm ơn bạn! Tôi đang học cách hiểu bạn tốt hơn."]
        
        # Add personalization based on interests
        top_interests = sorted(profile['interest_topics'].items(), key=lambda x: x[1], reverse=True)[:3]
        if top_interests and random.random() < 0.3:  # 30% chance to mention interests
            interest_word = top_interests[0][0]
            templates.append(f"Mình nhớ bạn hay nói về {interest_word} đấy!")
        
        return random.choice(templates)
    
    def _update_conversation_history(self, user_input, assistant_response):
        """Update conversation history for AI context"""
        if assistant_response:  # Only add complete exchanges
            self.conversation_history.append({
                'user': user_input,
                'assistant': assistant_response,
                'timestamp': datetime.now().isoformat()
            })
            
            # Keep only last 10 exchanges to manage memory
            if len(self.conversation_history) > 10:
                self.conversation_history = self.conversation_history[-10:]
    
    def get_ai_enhanced_sentiment(self, text):
        """Get AI-powered sentiment analysis"""
        if self.use_ai and self.ai_enhancer:
            try:
                return self.ai_enhancer.enhance_sentiment_analysis(text)
            except Exception as e:
                print(f"AI sentiment analysis failed: {e}")
        
        # Fallback to rule-based
        return {
            "sentiment": "positive" if self.scoring_emotional_stat(text) > 0 else "negative" if self.scoring_emotional_stat(text) < 0 else "neutral",
            "confidence": 0.7,
            "emotions": [self.detect_emotional_tone(text)]
        }
    
    def generate_conversation_questions(self):
        """Generate AI-powered conversation questions"""
        if self.use_ai and self.ai_enhancer and 'personality_profile' in self.daily_stats:
            try:
                return self.ai_enhancer.generate_conversation_questions(
                    self.daily_stats['personality_profile']
                )
            except Exception as e:
                print(f"AI question generation failed: {e}")
        
        # Fallback to rule-based questions
        return [
            "Bạn cảm thấy thế nào hôm nay?",
            "Có điều gì thú vị muốn chia sẻ không?",
            "Bạn đang nghĩ về gì vậy?"
        ]
    
    def enhanced_analyzer_user_response(self, user_response):
        """Enhanced analysis combining rule-based + AI"""
        # Get rule-based analysis
        rule_analysis = self.analyzer_user_response(user_response)
        
        # Get AI enhancement
        if self.use_ai and self.ai_enhancer:
            try:
                ai_sentiment = self.get_ai_enhanced_sentiment(user_response)
                rule_analysis['ai_sentiment'] = ai_sentiment
                rule_analysis['enhanced'] = True
            except Exception as e:
                print(f"AI enhancement failed: {e}")
                rule_analysis['enhanced'] = False
        else:
            rule_analysis['enhanced'] = False
        
        return rule_analysis
    
    def cleanup_ai_resources(self):
        """Clean up AI model resources"""
        if self.ai_enhancer:
            self.ai_enhancer.cleanup()
            self.ai_enhancer = None
        
    def __del__(self):
        """Destructor to clean up resources"""
        try:
            self.cleanup_ai_resources()
        except:
            pass
