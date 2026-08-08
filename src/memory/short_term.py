"""Bộ nhớ NGẮN HẠN — "working memory": vài lượt hội thoại GẦN ĐÂY trong phiên.

Giúp LLM hiểu ngữ cảnh liền trước. Giới hạn số lượt (lượt cũ RƠI ra). Mặc định session-only
(quên khi tắt app); tuỳ chọn lưu file (path) để nối tiếp qua restart nếu người dùng muốn.

Vị trí trong gói `memory/` (xem memory/__init__.py cho bản đồ tổng thể):
tầng DÀI HẠN ở `memory/profile.py`, cầu nối hai tầng ở `memory/consolidation.py`.
"""

import json
import os

from llm.client import Message
from utils.logger import get_logger

logger = get_logger(__name__)


class ShortTermMemory:
    """Vài lượt hội thoại gần đây. `path=None` = chỉ giữ trong phiên (không lưu file)."""

    def __init__(self, max_turns=10, path=None):
        self.max_turns = max_turns
        self.path = path or None
        self.turns = []          # list[Message]: 2 phần tử mỗi lượt (user + assistant)
        self._load()

    def messages(self):
        """Bản sao danh sách lượt để ghép vào prompt (không cho sửa trực tiếp)."""
        return list(self.turns)

    def add(self, user_text, assistant_text):
        """Thêm một lượt trao đổi. Trả danh sách Message BỊ ĐẨY RA (evicted) do vượt giới hạn."""
        self.turns.append(Message(role="user", text=user_text))
        self.turns.append(Message(role="assistant", text=assistant_text))
        cap = max(self.max_turns, 0) * 2
        evicted = []
        if len(self.turns) > cap:
            keep_from = len(self.turns) - cap
            evicted = self.turns[:keep_from]
            self.turns = self.turns[keep_from:]
        self._save()
        return evicted

    def clear(self):
        self.turns = []
        self._save()

    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.turns = [Message(role=m["role"], text=m.get("text", "")) for m in data]
        except (OSError, ValueError, KeyError) as e:
            logger.warning("Không đọc được bộ nhớ ngắn hạn: %s", e)

    def _save(self):
        if not self.path:
            return
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump([{"role": m.role, "text": m.text} for m in self.turns],
                          f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Không lưu được bộ nhớ ngắn hạn: %s", e)
