"""Bộ nhớ của trợ lý — gom mọi thứ liên quan trí nhớ về một chỗ.

Bản đồ gói:
  short_term.py    NGẮN HẠN: vài lượt hội thoại gần đây trong phiên (working memory).
  profile.py       DÀI HẠN: sự thật bền vững về người dùng (tên, xưng hô, sở thích) +
                   SỰ KIỆN có thời điểm (phỏng vấn, cuộc hẹn) tự hết hạn.
  consolidation.py CẦU NỐI: rút điều đáng nhớ từ các lượt sắp bị quên (STM -> LTM).
  timefmt.py       MỐC THỜI GIAN: "bây giờ" + xác định một sự kiện đã qua hay chưa.
  data/            Dữ liệu thật (profile.json, persona.json) — RIÊNG TƯ, đã gitignore.

Vì sao tách SỰ KIỆN khỏi sự thật bền vững: tên/sở thích không bao giờ hết hạn, còn
"phỏng vấn lúc 12h" thì có. Gộp chung khiến trợ lý nhắc việc đã xong như sắp diễn ra.
"""

from memory.short_term import ShortTermMemory
from memory.consolidation import EXTRACT_SYSTEM, parse_extracted_facts
from memory.profile import UserProfile, apply_update, summarize
from memory.timefmt import format_now

__all__ = ["ShortTermMemory", "EXTRACT_SYSTEM", "parse_extracted_facts",
           "UserProfile", "apply_update", "summarize", "format_now"]
