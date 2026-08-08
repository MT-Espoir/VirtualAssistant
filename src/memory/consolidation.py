"""Củng cố STM -> LTM: rút điều đáng nhớ từ đoạn hội thoại sắp bị quên.

Tách khỏi short_term.py vì là mối quan tâm KHÁC: short_term lo LƯU vài lượt gần đây,
còn đây lo BIẾN chúng thành trí nhớ dài hạn (prompt trích + phân tích kết quả).
Agent điều phối lượt gọi LLM; file này chỉ có prompt + hàm THUẦN.
"""

import re


EXTRACT_SYSTEM = (
    "Bạn là bộ trích xuất trí nhớ. Từ đoạn hội thoại dưới đây, rút ra những điều đáng nhớ "
    "về NGƯỜI DÙNG. Mỗi điều MỘT DÒNG, ngắn gọn, khách quan.\n"
    "Phân loại mỗi dòng bằng tiền tố:\n"
    "- '[BEN] ' cho SỰ THẬT BỀN VỮNG, không bao giờ hết hạn (tên, sở thích, thói quen, "
    "nghề nghiệp, mục tiêu dài hạn).\n"
    "- '[SUKIEN <thời điểm ISO>] ' cho SỰ KIỆN có thời điểm rồi sẽ qua (phỏng vấn, cuộc "
    "hẹn, deadline, chuyến đi). Suy thời điểm từ ngày giờ hiện tại đã cho, dạng "
    "'YYYY-MM-DDTHH:MM'; không rõ giờ thì ghi '[SUKIEN]'.\n"
    "Ví dụ:\n"
    "[BEN] Thích uống cà phê sữa buổi sáng\n"
    "[SUKIEN 2026-08-08T14:00] Có buổi phỏng vấn với anh Nam\n"
    "TUYỆT ĐỐI không bịa điều không có trong hội thoại; bỏ qua chuyện vặt nhất thời. "
    "Nếu không có gì đáng nhớ, chỉ trả đúng: NONE."
)

_KIND_RE = re.compile(r"^\[\s*(BEN|SUKIEN)\s*([^\]]*)\]\s*", re.IGNORECASE)


def parse_extracted_facts(text, max_facts=3, max_len=120):
    """Tách văn bản model thành danh sách dict {text, kind, when}. [] nếu 'NONE'/rỗng.

    kind: 'event' nếu model gắn [SUKIEN ...], ngược lại 'durable'. `when` = chuỗi thời
    điểm model đưa (có thể rỗng). Thiếu tiền tố -> coi là bền vững (chiều AN TOÀN: sự thật
    bền vững chỉ thừa thông tin, còn coi nhầm thành sự kiện sẽ làm mất trí nhớ sau vài ngày).
    """
    facts = []
    for line in (text or "").splitlines():
        s = re.sub(r"^\s*[-*•]?\s*\d*[.)]?\s*", "", line).strip()
        if not s or s.upper() == "NONE":
            continue
        kind, when = "durable", None
        m = _KIND_RE.match(s)
        if m:
            if m.group(1).upper() == "SUKIEN":
                kind = "event"
                when = (m.group(2) or "").strip() or None
            s = s[m.end():].strip()
        if not s:
            continue
        facts.append({"text": s[:max_len], "kind": kind, "when": when})
        if len(facts) >= max_facts:
            break
    return facts
