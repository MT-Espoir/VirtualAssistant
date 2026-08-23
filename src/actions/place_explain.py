"""
Giải thích VÌ SAO đề xuất — mỗi nhận định phải có BẰNG CHỨNG (F1.5 §5, §9).

Luật của module này, theo đúng thứ tự ưu tiên:

1. Không có dữ liệu -> KHÔNG có nhận định. Không "làm tròn", không nói "chưa rõ giá" cho
   có vẻ đầy đủ.
2. Thuộc tính MỀM (yên tĩnh, hợp học bài, đông/vắng) không đo được bằng trường dữ liệu
   nào. Chỉ được nhắc tới khi có TRÍCH ĐOẠN REVIEW thật, và phải phát ngôn dạng suy đoán
   — "review có nhắc tới ...", KHÔNG phải "quán này yên tĩnh".
3. Số lượt đánh giá dùng làm proxy độ đông thì phải NÓI RÕ là proxy.

Vì sao siết chặt: Phase 0 cho thấy bộ trích chạy hoàn hảo mà vẫn giao ra dữ liệu sai.
Tầng này còn nguy hiểm hơn vì nó SUY DIỄN, và câu suy diễn nghe thuyết phục hơn hẳn câu
trích dẫn. Không có luật thì đây là chỗ dễ biến trợ lý thành máy bịa có duyên nhất.
"""

from actions.place_features import minutes_until_close
from actions.place_ranking import INTENT_LEXICON
from utils.text_norm import strip_accents
from utils.units import say_distance

# Nhận định cho thuộc tính mềm — LUÔN ở dạng suy đoán, không bao giờ khẳng định.
_SOFT_CLAIM = {
    "hoc_lam_viec": "review có nhắc tới việc hợp ngồi học / làm việc",
    "yen_tinh": "review có nhắc tới không gian yên tĩnh",
    "gia_re": "review có nhắc tới giá dễ chịu",
}

_CROWD_WORDS = ("khong dong", "vang", "it nguoi", "dong duc", "dong khach")


def _fmt_time(hm):
    return f"{hm[0]}:{hm[1]:02d}" if hm else None


def _quote_fragment(quote, limit=60):
    """Trích dẫn NGUYÊN VĂN, cắt ngắn cho vừa câu nói."""
    text = " ".join((quote or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def build_evidence(place, ctx=None):
    """-> danh sách {kind: plus|caveat, claim, evidence}. Chỉ gồm thứ CÓ dữ liệu thật."""
    ctx = ctx or {}
    out = []

    km = place.get("distance_km")
    if km is not None:
        nearest = ctx.get("nearest_km")
        is_nearest = nearest is not None and abs(km - nearest) < 1e-9
        out.append({"kind": "plus", "priority": 1,
                    "claim": "gần nhất trong nhóm" if is_nearest else "ở gần",
                    "evidence": say_distance(km)})

    rating, reviews = place.get("rating"), place.get("reviews")
    if rating is not None:
        # Luôn kèm SỐ LƯỢT: 5,0 với 3 lượt và 4,7 với 166 lượt không cùng độ tin cậy.
        ev = f"{rating} sao" + (f" với {reviews} lượt đánh giá" if reviews else "")
        out.append({"kind": "plus", "priority": 2, "claim": "được đánh giá tốt", "evidence": ev})

    opening = place.get("opening") or {}
    state = opening.get("state")
    if state == "open_24h":
        out.append({"kind": "plus", "priority": 3, "claim": "mở cả ngày", "evidence": None})
    elif state == "closing_soon":
        t = _fmt_time(opening.get("closes_at"))
        out.append({"kind": "caveat", "priority": 3, "claim": "sắp đóng cửa",
                    "evidence": f"đóng lúc {t}" if t else None})
    elif state == "closed":
        out.append({"kind": "caveat", "priority": 3, "claim": "đang đóng cửa", "evidence": None})
    elif state == "open":
        left = minutes_until_close(opening, ctx.get("now"))
        t = _fmt_time(opening.get("closes_at"))
        if t and left is not None and left > 60:
            out.append({"kind": "plus", "priority": 3, "claim": f"còn mở tới {t}", "evidence": None})

    price = place.get("price")
    if price and price.get("raw"):
        out.append({"kind": "plus", "priority": 4, "claim": "có công bố dải giá", "evidence": price["raw"]})

    # --- thuộc tính MỀM: chỉ khi có trích đoạn review thật ---
    quote = place.get("quote")
    if quote:
        low = strip_accents(quote.lower())
        for key in ctx.get("intent_keys") or []:
            words = INTENT_LEXICON.get(key, ((), ()))[1]
            if any(w in low for w in words):
                # Ưu tiên 0: đây là nhận định trả lời đúng Ý ĐỊNH người dùng nêu — quan trọng
                # hơn khoảng cách hay điểm số, nên không được bị cắt khi rút gọn câu.
                out.append({"kind": "plus", "priority": 0,
                            "claim": _SOFT_CLAIM.get(key, "review có nhắc tới"),
                            "evidence": f'"{_quote_fragment(quote)}"'})
                break

    # --- proxy độ đông: chỉ khi NGƯỜI DÙNG hỏi tới, và phải nói rõ là proxy ---
    if ctx.get("asked_about_crowd") and reviews:
        if reviews >= (ctx.get("crowd_threshold") or 300):
            out.append({"kind": "caveat", "priority": 5, "claim": "có thể đông",
                        "evidence": f"tới {reviews} lượt đánh giá nên nhiều người biết"})
    return out


def explain(place, ctx=None, max_plus=3):
    """Danh sách bằng chứng -> MỘT câu tiếng Việt. LLM chỉ việc đọc lại.

    Không có bằng chứng nào -> nói thẳng là không có gì để nói thêm, KHÔNG bịa lý do.
    """
    items = build_evidence(place, ctx)
    items.sort(key=lambda i: i.get("priority", 9))     # ý định người dùng lên đầu
    plus = [i for i in items if i["kind"] == "plus"][:max_plus]
    caveat = [i for i in items if i["kind"] == "caveat"]
    name = place.get("name") or "chỗ này"

    if not plus and not caveat:
        return f"Mình chưa có thêm thông tin gì về {name} ngoài vị trí."

    def _phrase(i):
        # Bằng chứng trùng ý với nhận định thì bỏ ngoặc cho câu đỡ lủng củng khi TTS đọc.
        return f"{i['claim']} ({i['evidence']})" if i.get("evidence") else i["claim"]

    parts = [_phrase(i) for i in plus]
    sentence = f"Mình ưu tiên {name} vì " + ", ".join(parts) + "." if parts else f"Về {name}:"
    if caveat:
        sentence += " Lưu ý: " + ", ".join(_phrase(c) for c in caveat) + "."
    return sentence
