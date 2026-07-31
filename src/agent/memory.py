"""Bộ nhớ HAI TẦNG cho trợ lý.

NGẮN HẠN (ShortTermMemory) — "working memory": vài lượt hội thoại GẦN ĐÂY trong phiên,
giúp LLM hiểu ngữ cảnh liền trước. Giới hạn số lượt (lượt cũ RƠI ra). Mặc định session-only
(quên khi tắt app); tuỳ chọn lưu file (path) để nối tiếp qua restart nếu người dùng muốn.

DÀI HẠN (long-term) — sự thật BỀN VỮNG về người dùng, sống qua mọi phiên: do
`components/user/user_profile.UserProfile` đảm nhiệm (tên, xưng hô, địa điểm, ghi chú
tường minh + auto_facts tự trích). Cầu nối hai tầng: khi STM đẩy lượt cũ sắp quên ra,
Agent có thể "củng cố" (consolidate) — gọi LLM rút sự thật đáng nhớ rồi lưu sang tầng dài
hạn (`parse_extracted_facts` + `EXTRACT_SYSTEM` ở đây; Agent điều phối lượt gọi LLM).
"""

import json
import os
import re

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


# --------------------- Củng cố STM -> LTM (trích sự thật bền vững) --------------------- #

EXTRACT_SYSTEM = (
    "Bạn là bộ trích xuất trí nhớ. Từ đoạn hội thoại dưới đây, rút ra các SỰ THẬT BỀN VỮNG "
    "đáng nhớ lâu dài về NGƯỜI DÙNG (sở thích, thói quen, thông tin cá nhân, mục tiêu). "
    "Mỗi sự thật MỘT DÒNG, ngắn gọn, khách quan. TUYỆT ĐỐI không bịa điều không có trong "
    "hội thoại; bỏ qua chuyện vặt nhất thời. Nếu không có gì đáng nhớ, chỉ trả đúng: NONE."
)


def parse_extracted_facts(text, max_facts=3, max_len=120):
    """Tách văn bản model thành danh sách sự thật đã dọn. [] nếu 'NONE'/rỗng.

    Bỏ bullet/số thứ tự đầu dòng, cắt độ dài, giới hạn số lượng.
    """
    facts = []
    for line in (text or "").splitlines():
        s = re.sub(r"^\s*[-*•]?\s*\d*[.)]?\s*", "", line).strip()
        if not s or s.upper() == "NONE":
            continue
        facts.append(s[:max_len])
        if len(facts) >= max_facts:
            break
    return facts
