"""Củng cố STM -> LTM: rút điều đáng nhớ từ đoạn hội thoại sắp bị quên.

Tách khỏi short_term.py vì là mối quan tâm KHÁC: short_term lo LƯU vài lượt gần đây,
còn đây lo BIẾN chúng thành trí nhớ dài hạn (prompt trích + phân tích kết quả).
Agent điều phối lượt gọi LLM; file này chỉ có prompt + hàm THUẦN.
"""

import hashlib
import re

from utils.text_norm import norm


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
    "Chỉ rút điều có thể đối chiếu với một câu do chính Người dùng nói; không lấy câu "
    "của Trợ lý làm bằng chứng. "
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


_EVIDENCE_STOPWORDS = frozenset({
    "toi", "minh", "em", "anh", "chi", "ban", "la", "co", "mot", "nhung",
    "va", "voi", "cua", "cho", "nay", "do", "thi", "hay", "rat", "dang",
})


def supporting_evidence(transcript, fact_text, max_quote=240):
    """Find the strongest exact user utterance supporting an extracted candidate.

    The extractor may paraphrase, but it may not create durable memory from assistant
    text or an unrelated user sentence. The result contains a bounded quote, confidence
    and a transcript fingerprint suitable for ``memory_evidence.source_id``.
    """
    fact_tokens = {token for token in norm(fact_text or "").split()
                   if len(token) > 1 and token not in _EVIDENCE_STOPWORDS}
    if not fact_tokens:
        return None
    best = None
    for line in (transcript or "").splitlines():
        prefix, separator, raw = line.partition(":")
        if not separator or norm(prefix).strip() != "nguoi dung":
            continue
        quote = raw.strip()
        quote_tokens = {token for token in norm(quote).split()
                        if len(token) > 1 and token not in _EVIDENCE_STOPWORDS}
        overlap = len(fact_tokens & quote_tokens)
        if overlap <= 0:
            continue
        coverage = overlap / max(1, len(fact_tokens))
        score = (overlap, coverage, len(quote_tokens))
        if best is None or score > best[0]:
            best = (score, quote)
    if best is None:
        return None
    overlap, coverage, _ = best[0]
    confidence = min(0.9, 0.5 + 0.08 * overlap + 0.22 * coverage)
    source_id = "stm:" + hashlib.sha256(
        (transcript or "").encode("utf-8")).hexdigest()
    return {"quote": best[1][:max_quote], "confidence": round(confidence, 3),
            "source_id": source_id}
