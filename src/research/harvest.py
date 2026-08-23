"""
Thu hoạch TÊN THỰC THỂ từ cấu trúc bài viết — thuần, không LLM (spec §4).

Bài dạng danh sách có cấu trúc sẵn: `<h2>1. Quán A</h2>`, `<li>2. Quán B</li>`. Đọc cấu
trúc đó bằng parser thay vì nhờ LLM đọc cả bài. Đo 2026-08-22 trên 9 trang thật:

    LLM đọc toàn bài : 57 giây/trang, recall 54%
    parser           : ~0 ms,          recall 93%

Parser thắng ở CẢ hai chiều. LLM tự cắt danh sách (mia.vn: parser 31 tên, LLM dừng ở 10)
còn parser liệt kê cạn kiệt.

Đánh đổi có thật: parser recall cao, **precision trung bình**. Chấp nhận được vì hai tầng
sau lọc giúp — đồng thuận chéo nguồn (`consensus.py`) rồi giải danh tính ở tầng miền.
Recall thì ngược lại: **mất là mất luôn**, không tầng nào cứu được.

Bài học đắt nhất (spec §2.5): bóc trên TOÀN TRANG cho 70% chính xác và đẩy boilerplate
WordPress *"Để lại một bình luận Hủy"* lên **hạng nhất** — vì mọi site WordPress đều có
cùng chuỗi đó, nên nó đồng thuận chéo nguồn còn tốt hơn nội dung thật. Chỉ bóc trong
thân bài viết (`acquire.article_body`) mới cho 100%.
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
    # Tiêu đề MỤC bên trong bài, không phải tên thực thể. Đo thật 2026-08-22:
    # "Những quán cà phê Thủ Đức có view đẹp", "Các quán cafe mở 24/24".
    "những ", "các ", "top", "tổng ", "địa điểm", "nên ",
)

MIN_LEN = 4
MAX_LEN = 80
# Đo thật 2026-08-22 trên nguồn Thủ Đức: tên quán thật dài nhất 5 từ ("The Coffee Farm
# Thủ Đức"), còn tiêu đề mục dài 8-11 từ ("Quán cafe sân vườn Thủ Đức nào có nhiều góc
# check in"). Ngưỡng 12 cũ để lọt hết đám sau.
MAX_WORDS = 7

_HEADING = re.compile(r"<(h[234])[^>]*>(.*?)</\1>", re.S | re.I)
_LIST_ITEM = re.compile(r"<li[^>]*>(.*?)</li>", re.S | re.I)
# Số đứng đầu heading: THỨ TỰ MỤC hay MỘT PHẦN CỦA TÊN? Chuỗi tự nó không trả lời được —
# "36 Coffee", "1900 Cafe", "6 Degrees" là tên quán thật, còn "2 Tiệm cà phê Túi Mơ To" thì
# số 2 là thứ tự mục. Nên số chỉ bị bỏ trong hai trường hợp: có DẤU CÂU ngăn ngay sau nó
# ("1. ", "12) "), hoặc nó là thứ tự HỢP LỆ trong dãy của cả trang (`page_ordinals`).
#
# Nhóm 1 = số, nhóm 2 = dấu câu ngăn (None khi chỉ cách bằng khoảng trắng). `(?!\d)` giữ
# "1900 Cafe" nguyên vẹn: không cho khớp hai chữ số đầu của một số dài hơn.
_LEADING_NUMBER = re.compile(r"^\s*(\d{1,2})(?!\d)\s*(?:([\.\)\-–:])\s*|\s+)")

_NUMBERED = re.compile(r"^\d{1,2}[\.\)]\s+\S")

# Dãy 1,2,3... phải dài bao nhiêu thì mới tin là bài có đánh số. Hai mục thì còn có thể là
# trùng hợp ("1900 Cafe" bị bỏ qua, nhưng "6 Degrees" rồi "7 Bridges" thì không).
MIN_ORDINAL_RUN = 3


# Phần MÔ TẢ mà người viết nối sau tên, ngăn bằng dấu gạch có khoảng trắng hai bên.
_TRAILING_DESC = re.compile(r"\s[–—-]\s|\s\|\s")


def page_ordinals(headings):
    """[chuỗi heading thô] -> tập số mà TRANG NÀY đang dùng làm số thứ tự. Hàm thuần.

    Xét từng heading một cách cô lập thì "2 Tiệm cà phê Túi Mơ To" và "36 Coffee" giống hệt
    nhau. Cái phân biệt chúng nằm ở CẢ TRANG: bài có đánh số thì các số chạy 1, 2, 3... theo
    đúng thứ tự xuất hiện, còn con số trong tên quán thì không ăn khớp với vị trí nào cả.

    Nên chỉ nhận số thứ tự khi nó nối được vào dãy đếm từ 1: đi dọc các heading có số, số
    nào bằng đúng số đang chờ thì dãy dài thêm một, số nào không khớp thì BỎ QUA (nó không
    phải thứ tự) và vẫn chờ đúng số cũ. Nhờ vậy "36 Coffee" chen giữa một bài đánh số không
    làm đứt dãy, và "6 Degrees" đứng ở vị trí thứ 4 thì không được coi là thứ tự.

    Dãy ngắn hơn `MIN_ORDINAL_RUN` -> trả tập rỗng, tức giữ nguyên mọi con số. Đây là phía
    an toàn của đánh đổi: bỏ nhầm số làm HỎNG TÊN THẬT, còn giữ nhầm chỉ khiến tên thừa một
    con số — tầng đồng thuận chéo nguồn vẫn gom được vì mọi nguồn khác viết đúng tên.
    """
    expected = 1
    for h in headings or []:
        m = _LEADING_NUMBER.match((h or "").strip())
        if m and int(m.group(1)) == expected:
            expected += 1
    run = expected - 1
    return frozenset(range(1, run + 1)) if run >= MIN_ORDINAL_RUN else frozenset()


def clean_candidate(text, ordinals=frozenset()):
    """Chuỗi thô -> tên ứng viên. Rỗng nếu không dùng được.

    Thứ tự BẮT BUỘC: bỏ số thứ tự -> **cắt phần mô tả sau dấu gạch** -> rồi mới đo độ dài.

    Đảo thứ tự là hỏng: listicle hay viết "Elmar Coffee - Quán cà phê phong cách Tây Ban
    Nha"; đo độ dài trước khi cắt thì cả cụm dài 9 từ nên bị loại oan. Chạy thật
    2026-08-22: `vincom.com.vn` rớt từ 10 tên xuống 2 vì đúng lỗi này.

    `ordinals` là tập số thứ tự của trang, do `page_ordinals` tính trên TOÀN BỘ heading.
    Rỗng (mặc định) thì số chỉ bị bỏ khi có dấu câu ngăn sau nó.
    """
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
# Đo 2026-08-22 trên 3 truy vấn, 2 thành phố (spec §2.8):
#     ứng viên đạt ngưỡng có ẢNH     : 100%  (23/23)
#     ứng viên đạt ngưỡng có ĐỊA CHỈ :  52%  (12/23)
#
# Ảnh phủ tuyệt đối nên đây là nguồn bằng chứng thị giác rẻ nhất có thể có: 0 đồng, 0 lời
# gọi thêm, không đụng điều khoản của nhà cung cấp bản đồ.

_SECTION = re.compile(r"<h[234][^>]*>(.*?)</h[234]>", re.S | re.I)
_IMG_SRC = re.compile(r"<img[^>]+?(?:data-src|data-lazy-src|data-original|src)\s*=\s*"
                      r"[\"']([^\"']+)[\"']", re.I)
_ADDRESS = re.compile(r"(?:Địa\s*chỉ|Add?ress)\s*[::\-–]\s*([^<\n]{6,120})", re.I)

# --- TRÍCH DẪN NGUYÊN VĂN (spec §12) ---
#
# Thẻ kết quả đòi mỗi nhận định phải kèm NGUỒN XEM ĐƯỢC: ảnh, hoặc trích dẫn nguyên văn.
# Ảnh đã có (100%, §2.8). Trích dẫn là loại bằng chứng THỨ HAI, không thay ảnh — ảnh cho
# thấy chỗ đó TRÔNG thế nào, câu văn cho thấy người viết đã NÓI GÌ về đúng thuộc tính
# được hỏi. Hai loại bổ sung nhau vì chúng hỏng theo hai kiểu khác nhau.
#
# NGUYÊN VĂN nghĩa là nguyên văn: chỉ gộp khoảng trắng và cắt đuôi khi quá dài (có "…"
# đánh dấu). Không ghép mảnh từ hai câu, không diễn đạt lại — câu đã ghép lại là câu do
# hệ thống viết, và khi đó nó thôi không còn là bằng chứng.
QUOTE_MIN_LEN = 25    # ngắn hơn thì thường là mẩu tiêu đề, không phải câu nhận xét
QUOTE_MAX_LEN = 160   # panel bọc chữ ở 330px -> khoảng ba dòng

# Dòng CHÈN của theme nằm lẫn trong thân bài: bài viết liên quan, chú thích ảnh, nguồn.
# Chạy thật 2026-08-23: Lermalermer bị trích *"READ Hải Phòng Cải Tạo Sân Vận Động Máy Tơ
# Thành Công Viên Cây Xanh 2026"* — một đường dẫn sang bài khác, khớp "cây xanh" nhưng
# không nói gì về quán đang xét.
#
# Cố ý KHÔNG dùng lại `STOP_PREFIXES` của phần thu hoạch tên: nó có "những " và "các ",
# hợp lý cho tiêu đề mục nhưng sẽ giết đúng những câu văn hay nhất ("Những bức tường trát
# vữa màu vàng nhạt...").
_QUOTE_NOISE_PREFIXES = ("read ", "xem thêm", "xem ngay", "đọc thêm", "có thể bạn",
                         "bài viết liên quan", "tin liên quan", "nguồn:", "ảnh:",
                         "theo dõi", "chia sẻ")

# RANH GIỚI KHỐI là mốc ngắt câu THẬT; dấu chấm chỉ là mốc phụ.
#
# Đo thật 2026-08-23 trên noithattruongsa.com: mỗi dòng thông tin là một `<p>` riêng và
# KHÔNG kết thúc bằng dấu chấm —
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
# Đo thật 2026-08-23 trên zalopay.vn: `<li><a><span><u>Thác Voi Đà Lạt: Vẻ đẹp, đường đi
# và kinh nghiệm du lịch</u></span></a></li>` chen giữa thân bài, khớp "đẹp" rồi được
# trích làm bằng chứng cho một quán mà nó không hề nói tới.
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
    không phải thiếu sót: thẻ chỉ hiện trường có dữ liệu thật, thiếu thì im lặng (§12).
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
# Hai nhóm, và nhóm thứ hai mới là nhóm bắt được nhiều nhất khi chạy thật:
#   1. tên nói rõ là ảnh giao diện (logo, icon, avatar...)
#   2. NẰM TRONG THƯ MỤC của theme/plugin — ảnh nội dung luôn ở /uploads/ hoặc CDN, không
#      bao giờ ở /themes/ hay /plugins/. Chạy thật 2026-08-22 lọt
#      `.../themes/flatsome/assets/img/lazy.png` (ảnh giữ chỗ lazy-load) vì chỉ lọc theo tên.
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
