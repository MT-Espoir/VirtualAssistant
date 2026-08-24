"""
Thu hoạch TÊN THỰC THỂ từ cấu trúc bài viết — thuần, không LLM.
"""

import re

from actions.web.web_content import html_to_text

# Tiền tố của mục KHÔNG phải tên thực thể: chrome web tiếng Việt và tiêu đề dẫn dắt.
# Đây là rác chung của trang web, không riêng miền nào — miền cụ thể thêm qua tham số.
STOP_PREFIXES = (
    "top ", "danh sách", "danh mục", "mục lục", "kết luận", "lời kết", "tổng hợp",
    "chia sẻ", "bài viết", "xem thêm", "liên hệ", "liên kết", "thông tin", "nội dung",
    "review", "tại sao", "lưu ý", "faq", "câu hỏi", "gợi ý", "bình luận", "để lại",
    "tags", "đăng nhập", "đăng ký", "hỗ trợ", "recent ", "mẹo ", "cài đặt", "tư duy",
    "chính sách", "điều khoản", "giới thiệu", "hướng dẫn", "kinh nghiệm", "khám phá",
    "những ", "các ", "top", "tổng ", "địa điểm", "nên ",
)

MIN_LEN = 4
MAX_LEN = 80
MAX_WORDS = 7

_HEADING = re.compile(r"<(h[234])[^>]*>(.*?)</\1>", re.S | re.I)
_LIST_ITEM = re.compile(r"<li[^>]*>(.*?)</li>", re.S | re.I)
_LEADING_NUMBER = re.compile(r"^\s*(\d{1,2})(?!\d)\s*(?:([\.\)\-–:])\s*|\s+)")

_NUMBERED = re.compile(r"^\d{1,2}[\.\)]\s+\S")

MIN_ORDINAL_RUN = 3

_TRAILING_DESC = re.compile(r"\s[–—-]\s|\s\|\s")


def page_ordinals(headings):
    """[chuỗi heading thô] -> tập số mà TRANG NÀY đang dùng làm số thứ tự. Hàm thuần."""
    expected = 1
    for h in headings or []:
        m = _LEADING_NUMBER.match((h or "").strip())
        if m and int(m.group(1)) == expected:
            expected += 1
    run = expected - 1
    return frozenset(range(1, run + 1)) if run >= MIN_ORDINAL_RUN else frozenset()


def clean_candidate(text, ordinals=frozenset()):
    """Chuỗi thô -> tên ứng viên. Rỗng nếu không dùng được."""
    t = (text or "").strip()
    m = _LEADING_NUMBER.match(t)
    if m and (m.group(2) or int(m.group(1)) in ordinals):
        t = t[m.end():]
    t = _TRAILING_DESC.split(t)[0].strip(" -–—:•. ")
    if not t or len(t) < MIN_LEN or len(t) > MAX_LEN or len(t.split()) > MAX_WORDS:
        return ""
    return t


def is_noise(text, stop_prefixes=()):
    """Mục này có phải chrome/tiêu đề dẫn dắt không."""
    low = (text or "").strip().lower()
    if not low:
        return True
    return any(low.startswith(p) for p in tuple(STOP_PREFIXES) + tuple(stop_prefixes))


def harvest_names(body_html, stop_prefixes=(), key_of=None):
    """HTML THÂN BÀI -> danh sách tên ứng viên, giữ thứ tự xuất hiện, đã khử trùng.

    `key_of(tên)` dùng để khử trùng trong CÙNG một trang; mặc định so chuỗi thường hoá.
    Tầng miền truyền hàm chuẩn hoá của mình vào để "Quán cà phê Trill" và "Trill Bistro"
    không thành hai ứng viên.

    Chỉ lấy heading và mục danh sách ĐÁNH SỐ — đoạn văn thường không được đụng tới, vì
    tên nằm trong câu văn thì không tách được bằng cấu trúc và đoán bừa sẽ sinh rác.
    """
    key_of = key_of or (lambda s: (s or "").strip().lower())
    heads = [html_to_text(m.group(2)) for m in _HEADING.finditer(body_html or "")]
    items = []
    for m in _LIST_ITEM.finditer(body_html or ""):
        text = html_to_text(m.group(1))
        if _NUMBERED.match(text.strip()) and len(text) < 120:
            items.append(text)
    # Dãy số đọc trên heading THÔ — phải tính trước khi lọc, vì chính những mục bị lọc
    # ("1 Mở đầu", "5 Lưu ý khi đi") mới là thứ đang giữ cho dãy liền mạch.
    ordinals = page_ordinals(heads)

    out, seen = [], set()
    for item in heads + items:
        name = clean_candidate(item, ordinals)
        if not name or is_noise(name, stop_prefixes):
            continue
        k = key_of(name)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(name)
    return out


def harvest_per_source(sources, stop_prefixes=(), key_of=None):
    """[{domain, body_html}] -> {domain: [tên]}. Bỏ nguồn không thu được gì.

    Đúng hình dạng đầu vào mà `consensus.consensus()` cần.
    """
    per = {}
    for s in sources or []:
        names = harvest_names(s.get("body_html"), stop_prefixes, key_of)
        if names:
            per[s.get("domain") or s.get("url")] = names
    return per


# ======================== KHỐI NỘI DUNG THEO TỪNG MỤC ========================
#
# Bài dạng danh sách đặt tên quán ở heading rồi mô tả ngay bên dưới, nên phần HTML nằm
# GIỮA hai heading chính là phần nói về quán đó. Nhờ vậy lấy được ảnh và địa chỉ mà không
# cần gọi thêm nguồn nào — chúng đã nằm trong trang vừa tải.
#
# Ảnh phủ tuyệt đối nên đây là nguồn bằng chứng thị giác rẻ nhất có thể có: 0 đồng, 0 lời
# gọi thêm, không đụng điều khoản của nhà cung cấp bản đồ.

_SECTION = re.compile(r"<h[234][^>]*>(.*?)</h[234]>", re.S | re.I)
_IMG_SRC = re.compile(r"<img[^>]+?(?:data-src|data-lazy-src|data-original|src)\s*=\s*"
                      r"[\"']([^\"']+)[\"']", re.I)
_ADDRESS = re.compile(r"(?:Địa\s*chỉ|Add?ress)\s*[::\-–]\s*([^<\n]{6,120})", re.I)

# --- TRÍCH DẪN NGUYÊN VĂN ---
#
# Thẻ kết quả đòi mỗi nhận định phải kèm NGUỒN XEM ĐƯỢC: ảnh, hoặc trích dẫn nguyên văn.
# Trích dẫn là loại bằng chứng THỨ HAI, không thay ảnh — ảnh cho
# thấy chỗ đó TRÔNG thế nào, câu văn cho thấy người viết đã NÓI GÌ về đúng thuộc tính
# được hỏi. Hai loại bổ sung nhau vì chúng hỏng theo hai kiểu khác nhau.
#
# NGUYÊN VĂN nghĩa là nguyên văn: chỉ gộp khoảng trắng và cắt đuôi khi quá dài (có "…"
# đánh dấu). Không ghép mảnh từ hai câu, không diễn đạt lại — câu đã ghép lại là câu do
# hệ thống viết, và khi đó nó thôi không còn là bằng chứng.
QUOTE_MIN_LEN = 25    # ngắn hơn thì thường là mẩu tiêu đề, không phải câu nhận xét
QUOTE_MAX_LEN = 160   # panel bọc chữ ở 330px -> khoảng ba dòng

# Dòng CHÈN của theme nằm lẫn trong thân bài: bài viết liên quan, chú thích ảnh, nguồn.
# Một tiêu đề bài khác kiểu "READ ... Công Viên Cây Xanh" khớp đúng từ khoá đang tìm rồi
# được trích làm bằng chứng, trong khi nó không nói gì về quán đang xét.
#
# Cố ý KHÔNG dùng lại `STOP_PREFIXES` của phần thu hoạch tên: nó có "những " và "các ",
# hợp lý cho tiêu đề mục nhưng sẽ giết đúng những câu văn hay nhất ("Những bức tường trát
# vữa màu vàng nhạt...").
_QUOTE_NOISE_PREFIXES = ("read ", "xem thêm", "xem ngay", "đọc thêm", "có thể bạn",
                         "bài viết liên quan", "tin liên quan", "nguồn:", "ảnh:",
                         "theo dõi", "chia sẻ")

# RANH GIỚI KHỐI là mốc ngắt câu THẬT; dấu chấm chỉ là mốc phụ.
#
# Nhiều bài đặt mỗi dòng thông tin trong một `<p>` riêng và KHÔNG kết thúc bằng dấu chấm —
#
#     <p><span>⏰ Giờ mở cửa: 08h00 – 23h00</span></p>
#     <p><span>💲 Giá tham khảo: 30.000 – 200.000đ/người</span></p>
#     <p><span>Nếu bạn muốn tìm một quán cafe nhiều cây xanh ở Hà Nội thì...</span></p>
#
# `html_to_text` nối mọi mẩu chữ bằng dấu cách (đúng cho việc của nó là đưa văn bản cho
# LLM đọc), nên ba khối trên dính thành một "câu", và trích dẫn ra nguyên mớ giờ giấc kèm
# bảng giá rồi mới tới ý chính. Phải ngắt TRƯỚC khi bóc thẻ, không sửa `html_to_text` —
# nó còn phục vụ đường khác.
_BLOCK_END = re.compile(r"</(?:p|div|li|ul|ol|dl|dd|dt|tr|td|th|h[1-6]|blockquote|"
                        r"figcaption|section|article)>|<br\s*/?>", re.I)
# Mốc ngắt phải là ký tự KHÔNG PHẢI khoảng trắng, nếu không `handle_data` strip mất nó.
_BLOCK_MARK = "\x00"

# Dấu kết câu phải theo sau bằng khoảng trắng HOẶC hết chuỗi — thiếu vế `$` thì câu CUỐI
# đoạn giữ lại dấu chấm còn các câu khác thì không, và trích dẫn ra hai kiểu khác nhau.
# Dùng `\s` chứ không phải ký tự bất kỳ để "35.000 đồng" không bị cắt làm đôi.
#
# Nhánh mốc khối đặt TRƯỚC và nuốt luôn dấu chấm đứng ngay trái nó: `...mát.\x00` không
# có khoảng trắng xen giữa, nên nếu chỉ ngắt ở mốc thì câu cuối mỗi khối giữ lại dấu chấm
# còn các câu khác thì không — trích dẫn ra hai kiểu.
_SENTENCE_SPLIT = re.compile(r"[.!?…]*\x00|[.!?…]+(?:\s|$)|\n+|\|")
_WORD = re.compile(r"\w+", re.UNICODE)

# KHÔNG PHẢI mọi đường dẫn đều là rác. Đường dẫn trong văn xuôi ("nằm cạnh <a>Hồ Xuân
# Hương</a>") là một phần của câu; đường dẫn là TIÊU ĐỀ MỘT BÀI KHÁC thì không. Phân biệt
# bằng ĐỘ DÀI CHỮ TRONG THẺ: tham chiếu giữa câu là cụm 1-4 từ, còn tiêu đề bài là một
# câu hoàn chỉnh.
#
# Widget "tham khảo thêm" dạng `<li><a>tiêu đề bài khác</a></li>` chen giữa thân bài:
# tiêu đề đó khớp từ khoá rồi được trích làm bằng chứng cho một quán mà nó không hề
# nói tới.
_LINK = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S | re.I)
LINK_HEADLINE_WORDS = 5


def _drop_headline_links(html):
    def repl(m):
        inner = html_to_text(m.group(1))
        return _BLOCK_MARK if len(inner.split()) >= LINK_HEADLINE_WORDS else m.group(0)
    return _LINK.sub(repl, html or "")


def block_text(html):
    """HTML -> văn bản còn giữ ranh giới khối (dưới dạng mốc ngắt). Hàm thuần."""
    return html_to_text(_BLOCK_END.sub(_BLOCK_MARK, _drop_headline_links(html)))


def tokens(text):
    """Chuỗi -> tập từ đã hạ chữ thường. Hàm thuần."""
    return {w.lower() for w in _WORD.findall(str(text or ""))}


def pick_quote(text, terms, min_len=QUOTE_MIN_LEN, max_len=QUOTE_MAX_LEN):
    """Đoạn văn + từ khoá nhu cầu -> (câu nguyên văn, số từ khoá khớp). Hàm thuần.

    Trả `(None, 0)` khi không câu nào nhắc tới thuộc tính đang hỏi. Đó là kết quả ĐÚNG,
    không phải thiếu sót: thẻ chỉ hiện trường có dữ liệu thật, thiếu thì im lặng.
    Trích một câu bất kỳ cho đủ ô sẽ là bằng chứng GIẢ — nó trông như đang chứng minh
    điều gì đó trong khi không.

    Chọn câu khớp NHIỀU từ khoá nhất; hoà thì lấy câu ĐẦU, vì phần mở của mỗi mục thường
    là câu người viết tóm ý, phần sau là giá cả và giờ mở cửa.
    """
    want = {t.lower() for t in (terms or []) if t}
    if not want:
        return None, 0

    best, best_hits = None, 0
    for raw in _SENTENCE_SPLIT.split(str(text or "")):
        sentence = " ".join(raw.split())
        if len(sentence) < min_len:
            continue
        if sentence.lower().startswith(_QUOTE_NOISE_PREFIXES):
            continue
        hits = len(want & tokens(sentence))
        if hits > best_hits:
            best, best_hits = sentence, hits
    if best is None:
        return None, 0
    return _clip(best, max_len), best_hits


def _clip(sentence, max_len):
    """Cắt ở RANH GIỚI TỪ và đánh dấu bằng '…'. Cắt giữa từ đọc ra là chữ sai."""
    if len(sentence) <= max_len:
        return sentence
    cut = sentence[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:-–—")
    return (cut or sentence[:max_len]) + "…"

# Ảnh giao diện lẫn vào — loại theo đường dẫn.
#
# Hai nhóm, và nhóm thứ hai mới là nhóm bắt được nhiều nhất:
#   1. tên nói rõ là ảnh giao diện (logo, icon, avatar...)
#   2. NẰM TRONG THƯ MỤC của theme/plugin — ảnh nội dung luôn ở /uploads/ hoặc CDN, không
#      bao giờ ở /themes/ hay /plugins/. Lọc theo TÊN thôi là hụt: ảnh giữ chỗ lazy-load
#      của theme có tên vô hại nhưng vẫn là ảnh giao diện.
_IMG_NOISE = ("logo", "icon", "avatar", "gravatar", "placeholder", "sprite", "banner-ads",
              ".svg", "1x1", "pixel", "lazy", "blank", "spacer", "default-",
              "/themes/", "/plugins/", "/assets/img/")


def _clean_img(src, base_url=None):
    """URL ảnh thô -> URL dùng được, hoặc None nếu là ảnh giao diện."""
    u = (src or "").strip()
    if not u or u.startswith("data:"):
        return None
    if any(bad in u.lower() for bad in _IMG_NOISE):
        return None
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/") and base_url:
        from urllib.parse import urljoin
        return urljoin(base_url, u)
    return u if u.startswith("http") else None


def harvest_records(body_html, stop_prefixes=(), key_of=None, base_url=None, max_photos=3,
                    quote_terms=()):
    """HTML thân bài -> [{name, address, photos, quote, quote_hits}] theo thứ tự xuất hiện.

    Khác `harvest_names` ở chỗ giữ luôn phần THÂN của mỗi mục để bóc ảnh, địa chỉ và câu
    trích dẫn. Không có thì để None / danh sách rỗng — KHÔNG đoán, KHÔNG lấy bằng chứng
    của mục kế bên. Chính vì thế mọi thứ đều bóc trong `chunk` của riêng mục đó.

    `quote_terms` rỗng -> không tìm trích dẫn (`quote = None`).
    """
    key_of = key_of or (lambda s: (s or "").strip().lower())
    parts = _SECTION.split(body_html or "")
    heads = [html_to_text(parts[i]) for i in range(1, len(parts), 2)]
    ordinals = page_ordinals(heads)

    out, seen = [], set()
    for i in range(1, len(parts), 2):
        name = clean_candidate(heads[i // 2], ordinals)
        if not name or is_noise(name, stop_prefixes):
            continue
        k = key_of(name)
        if not k or k in seen:
            continue
        seen.add(k)

        chunk = parts[i + 1] if i + 1 < len(parts) else ""
        photos = []
        for raw in _IMG_SRC.findall(chunk):
            url = _clean_img(raw, base_url)
            if url and url not in photos:
                photos.append(url)
            if len(photos) >= max_photos:
                break
        # Tìm địa chỉ trên HTML THÔ, không phải text đã bóc thẻ: dấu `<` là mốc dừng của
        # biểu thức. Bóc thẻ trước rồi mới tìm thì mất mốc đó và địa chỉ nuốt luôn cả
        # đoạn văn phía sau.
        m = _ADDRESS.search(chunk)
        address = html_to_text(m.group(1)).strip(" .;,") if m else None
        quote, hits = pick_quote(block_text(chunk), quote_terms)
        out.append({"name": name, "address": address or None, "photos": photos,
                    "quote": quote, "quote_hits": hits})
    return out
