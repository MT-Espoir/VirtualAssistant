"""
CommandRouter — "bộ não" của trợ lý, tách hoàn toàn khỏi I/O (micro/loa).

Nhận vào một chuỗi text, phân loại ý định và định tuyến tới handler tương ứng,
trả về chuỗi phản hồi. Không đọc micro, không phát loa — nhờ vậy có thể viết
unit test trực tiếp (xem tests/test_command_router.py).

Phụ thuộc được tiêm vào (dependency injection) nên test có thể thay bằng bản giả:
    - nlp_processor:        có classify_intent(text) và extract_entities(text, intent_type)
    - conversation_engine:  có is_conversation_intent / generate_response / ...
    - actions:              facade AssistantActions (hoặc mock cùng interface)
    - user_profile:         (tùy chọn) có add_command(...)
    - extract_entity:       (tùy chọn) hàm trích xuất thực thể theo rule
"""

import re

from utils.logger import get_logger

logger = get_logger(__name__)

# Cụm từ dùng để tách nhiều lệnh trong một câu
COMMAND_SEPARATORS = [" và ", " and ", " sau đó ", " then ", ", ", "; "]

# Chuẩn hóa tên site viết tắt -> tên đầy đủ
SITE_ALIASES = {
    "fb": "facebook", "face": "facebook",
    "yt": "youtube", "tube": "youtube",
    "gg": "google",
    "ig": "instagram", "insta": "instagram",
    "tweet": "twitter",
    "tik": "tiktok", "tok": "tiktok",
    "git": "github",
    "shop": "shopee",
}


class CommandRouter:
    def __init__(self, nlp_processor, conversation_engine, actions,
                 user_profile=None, extract_entity=None):
        self.nlp = nlp_processor
        self.conversation = conversation_engine
        self.actions = actions
        self.user_profile = user_profile

        if extract_entity is None:
            from nlp.entity_extractor import extract_entity as _extract_entity
            extract_entity = _extract_entity
        self.extract_entity = extract_entity

        # Registry: intent -> handler(text) -> response
        self.handlers = {
            "open_app": self._handle_open_app,
            "close_app": self._handle_close_app,
            "system_volume": self._handle_volume,
            "system_brightness": self._handle_brightness,
            "system_shutdown": self._handle_shutdown,
            "system_restart": self._handle_restart,
            "open_website": self._handle_open_website,
            "web_search": self._handle_web_search,
            "youtube_search": self._handle_youtube,
            "search_on_site": self._handle_search_on_site,
        }

    # ------------------------------------------------------------------ #
    # Điểm vào chính
    # ------------------------------------------------------------------ #
    def route(self, text):
        """Định tuyến MỘT lệnh: text -> response."""
        text = text.lower()
        logger.debug("Routing: '%s'", text)

        intent = self.nlp.classify_intent(text)
        logger.debug("Intent: %s", intent)

        # 1) Ý định hội thoại -> conversation engine
        if self.conversation.is_conversation_intent(intent):
            response = self.conversation.generate_response(text, intent)
            if intent in ("greeting", "conversation", "small_talk"):
                self.conversation.set_conversation_mode(True)
            elif intent == "goodbye":
                self.conversation.set_conversation_mode(False)
            return response

        # 2) Ý định lệnh -> handler tương ứng
        handler = self.handlers.get(intent)
        if handler is not None:
            response = handler(text)
            self._record(text, intent)
            if response is not None:
                return response

        # 3) Không rõ -> để conversation engine xử lý mềm
        if intent == "unknown" or not intent:
            logger.debug("Unknown intent -> conversation engine")
            return self.conversation.generate_response(text, "unknown")

        return "Command not recognized"

    def route_multi(self, text):
        """Tách nhiều lệnh (nối bằng 'và', 'sau đó', dấu phẩy...) rồi chạy lần lượt."""
        commands = self._split_commands(text)

        if len(commands) <= 1:
            return self.route(text)

        logger.info("Phát hiện %d lệnh", len(commands))
        responses = []
        for i, cmd in enumerate(commands, 1):
            logger.debug("Thực thi lệnh %d/%d: '%s'", i, len(commands), cmd)
            responses.append(f"Lệnh {i}: {self.route(cmd)}")
        return " | ".join(responses)

    # ------------------------------------------------------------------ #
    # Tách lệnh
    # ------------------------------------------------------------------ #
    def _split_commands(self, text):
        split_points = []
        for sep in COMMAND_SEPARATORS:
            start = 0
            while True:
                pos = text.find(sep, start)
                if pos == -1:
                    break
                split_points.append((pos, pos + len(sep)))
                start = pos + 1

        if not split_points:
            return [text.strip()] if text.strip() else []

        split_points.sort()
        commands = []
        last_end = 0
        for start, end in split_points:
            if start > last_end:
                seg = text[last_end:start].strip()
                if seg:
                    commands.append(seg)
            last_end = end
        if last_end < len(text):
            seg = text[last_end:].strip()
            if seg:
                commands.append(seg)
        return commands

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #
    def _handle_open_app(self, text):
        app_name = self.extract_entity(text, intent_type="app_name")
        if app_name:
            self.actions.open_application(app_name)
            self.conversation.update_context("last_command", f"open_app: {app_name}")
            return f"Opening {app_name}"
        return "Không xác định được ứng dụng cần mở"

    def _handle_close_app(self, text):
        app_name = self.extract_entity(text, intent_type="app_name")
        if app_name:
            self.actions.close_application(app_name)
            return f"Closing {app_name}"
        return "Không xác định được ứng dụng cần đóng"

    def _handle_volume(self, text):
        percent = self._find_percent(text)
        if self._means_up(text):
            return self.actions.control_volume(change=percent if percent is not None else 10)
        if self._means_down(text):
            amount = percent if percent is not None else 10
            return self.actions.control_volume(change=-amount)
        if percent is not None:
            return self.actions.control_volume(level=percent)
        return self.actions.control_volume(change=0)

    def _handle_brightness(self, text):
        if self._means_up(text):
            return self.actions.control_brightness(change=10)
        if self._means_down(text):
            return self.actions.control_brightness(change=-10)
        percent = self._find_percent(text)
        if percent is not None:
            return self.actions.control_brightness(level=percent)
        return self.actions.control_brightness(change=0)

    def _handle_shutdown(self, text):
        immediate = "ngay lập tức" in text or "immediately" in text
        return self.actions.system_shutdown(close_apps=not immediate)

    def _handle_restart(self, text):
        immediate = "ngay lập tức" in text or "immediately" in text
        return self.actions.system_restart(close_apps=not immediate)

    def _handle_open_website(self, text):
        website = self.extract_entity(text, intent_type="website_name")
        if website:
            return self.actions.open_website(website)
        return "Không xác định được trang web cần mở"

    def _handle_web_search(self, text):
        query = text
        for kw in ("search", "find", "look for", "tìm kiếm", "tìm", "google"):
            query = query.replace(kw, "").strip()
        engine = "google"
        if "youtube" in text:
            engine = "youtube"
        elif "bing" in text:
            engine = "bing"
        return self.actions.search_web(query, engine)

    def _handle_youtube(self, text):
        query = text
        for word in ("tìm", "kiếm", "mở", "phát", "video", "bài hát", "nhạc",
                     "trên", "youtube", "search", "play", "find", "song", "music"):
            query = query.replace(word, "").strip()
        if not query:
            return "Không hiểu bạn muốn tìm gì trên YouTube"
        try:
            return self.actions.search_and_play_youtube_direct(query)
        except Exception as e:
            logger.warning("YouTube trực tiếp lỗi, dùng phương pháp cũ: %s", e)
            return self.actions.search_and_play_youtube(query)

    def _handle_search_on_site(self, text):
        data = self.nlp.extract_entities(text, intent_type="search_on_site")
        site = (data.get("site", "") or "").lower()
        query = data.get("query", "")
        if site and query:
            site = SITE_ALIASES.get(site, site)
            return self.actions.search_on_specific_site(query, site)
        return "Không hiểu trang web hoặc nội dung cần tìm kiếm"

    # ------------------------------------------------------------------ #
    # Tiện ích
    # ------------------------------------------------------------------ #
    @staticmethod
    def _find_percent(text):
        m = re.search(r"(\d+)\s*%", text)
        return int(m.group(1)) if m else None

    @staticmethod
    def _means_up(text):
        return any(w in text for w in ("tăng", "up", "increase"))

    @staticmethod
    def _means_down(text):
        return any(w in text for w in ("giảm", "down", "decrease"))

    def _record(self, text, intent):
        if self.user_profile is not None:
            try:
                self.user_profile.add_command(text, intent, {}, True)
            except Exception as e:  # ghi nhận thất bại không được làm hỏng luồng
                logger.debug("Không ghi được lịch sử lệnh: %s", e)
