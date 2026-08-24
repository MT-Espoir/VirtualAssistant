"""
Thu thập nguồn: TÌM -> TẢI SONG SONG -> HAI CỔNG LỌC.

Có HAI cổng chứ không phải một, vì có hai cái bẫy khác hẳn nhau:

1. Trang SPA trả HTTP 200 kèm cả chục kb "text" — nhưng đó là khung template rỗng
   (`{{...}}`, thuộc tính `ng-*`/`v-*`). Fetcher ngây thơ sẽ đưa khung template cho
   LLM và LLM sẽ bịa ra nội dung. -> `content_gate`.

2. Trang có nội dung thật, dài, sạch — nhưng không phải danh sách quán (vd bài "mẹo
   chụp ảnh cafe"): nó đóng góp toàn ứng viên rác, không tên quán nào. -> `page_type_gate`.

Cổng phải chặn TRƯỚC khi dữ liệu tới tay LLM: bộ trích chạy hoàn hảo mà vẫn giao ra dữ
liệu sai là kiểu hỏng khó thấy nhất.

Toàn bộ hàm phân tích ở đây là THUẦN (test không cần mạng); phần chạm mạng gom ở cuối
và nhận `http_get` tiêm vào — cùng quy ước với `actions/places.py` và `web_content.py`.
"""

import re
import urllib.parse

from actions.web.web_content import html_to_text
from utils.logger import get_logger

logger = get_logger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_DDG_HTML = "https://html.duckduckgo.com/html/"

# --- ngưỡng cổng nội dung (bẫy 1) ---
MIN_BODY_CHARS = 4000      # mức sàn rộng rãi: bài liệt kê thật đều dài hơn nhiều
MAX_TEMPLATE_MARKERS = 5   # trang thật hầu như không có marker; khung SPA thì hàng chục

# --- ngưỡng cổng loại trang (bẫy 2) ---
MIN_ENUMERATED = 3         # listicle thường ĐÁNH SỐ mục
MIN_HEADINGS = 5           # ...nhưng không phải lúc nào cũng vậy — xem `page_type_gate`

# Khối "chrome" của trang — không bao giờ chứa nội dung bài viết.
_CHROME_TAGS = ("nav", "header", "footer", "aside", "form", "script", "style", "noscript")

# Widget lạc vào giữa thân bài (sản phẩm liên quan, bài viết liên quan). Không gỡ thì
# tên sản phẩm và tiêu đề bài khác lọt vào danh sách ứng viên.
_WIDGET_CLASS = re.compile(
    r'<(div|section|ul)[^>]*class="[^"]*'
    r'(related|sidebar|widget|comment|share|tag-list|popular|trending|recirc|promo)'
    r'[^"]*"[^>]*>', re.I)

_TEMPLATE_MARKER = re.compile(r"\{\{[^}]{1,200}\}\}|\sng-[a-z-]+=|\sv-(?:if|for|bind|model)=")

# Thứ tự ưu tiên khi tìm thân bài. Bóc TOÀN TRANG là sai: boilerplate WordPress ("Để lại
# một bình luận", "Đăng nhập") giống nhau ở mọi site nên nó đồng thuận chéo nguồn tốt hơn
# cả nội dung thật, và leo lên đầu bảng ứng viên.
_BODY_PATTERNS = (
    ("article", re.compile(r"<article[^>]*>(.*?)</article>", re.S | re.I)),
    ("entry-content", re.compile(
        r'<div[^>]*class="[^"]*'
        r'(?:entry-content|post-content|article-content|content-detail|detail-content)'
        r'[^"]*"[^>]*>(.*)', re.S | re.I)),
    ("main", re.compile(r"<main[^>]*>(.*?)</main>", re.S | re.I)),
)

_ENUMERATED = re.compile(r">\s*(?:<[^>]+>\s*)*\d{1,2}\s*[\.\)]\s+\S")
_HEADING = re.compile(r"<h[234][^>]*>", re.I)


# ======================== HÀM THUẦN ========================

def decode_ddg_links(html):
    """Trang kết quả DDG HTML -> danh sách URL đích, theo thứ tự xuất hiện.

    DDG bọc mọi link ngoài trong `/l/?uddg=<url đã encode>`. Quên giải mã thì tưởng
    trang không có link nào — chính lỗi này làm tôi kết luận nhầm lúc đo lần đầu.
    """
    out, seen = [], set()
    # Lớp ký tự phải loại CẢ khoảng trắng và `<>`: thiếu `\s` thì một match nuốt luôn các
    # link phía sau thành một chuỗi dài, và kết quả vẫn "bắt đầu bằng https://" nên lọt
    # qua mọi kiểm tra — hỏng im lặng. Test `..._dedupes_and_ignores_junk` khoá ca này.
    for raw in re.findall(r"uddg=([^&\"'\s<>]+)", html or ""):
        url = urllib.parse.unquote(raw)
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            out.append(url)
    return out


# Bing đặt link đích THẲNG trong href, không bọc redirect như DDG. Phải loại các domain
# của chính Bing/Microsoft, nếu không thì "kết quả" toàn là link điều hướng nội bộ.
_BING_SKIP = ("bing.com", "microsoft.com", "msn.com", "microsofttranslator.com",
              "go.microsoft", "windows.com", "live.com", "office.com")


def decode_bing_links(html):
    """Trang kết quả Bing -> danh sách URL ngoài, theo thứ tự xuất hiện."""
    out, seen = [], set()
    for raw in re.findall(r'href="(https?://[^"]+)"', html or ""):
        url = raw.replace("&amp;", "&")
        host = urllib.parse.urlparse(url).netloc.lower()
        if not host or any(skip in host for skip in _BING_SKIP) or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def domain_of(url):
    return urllib.parse.urlparse(url or "").netloc.lower()


def one_per_domain(urls, exclude=()):
    """Giữ URL ĐẦU TIÊN của mỗi domain, bỏ domain trong `exclude`.

    Một domain một suất vì bước đếm đồng thuận (`consensus.py`) tính phiếu theo NGUỒN;
    lấy ba trang của cùng một site không làm bằng chứng mạnh hơn.
    """
    bad = tuple(x.lower() for x in exclude)
    out, seen = [], set()
    for u in urls or []:
        d = domain_of(u)
        if not d or d in seen or any(b in d for b in bad):
            continue
        seen.add(d)
        out.append(u)
    return out


def strip_chrome(html):
    """Gỡ nav/header/footer/aside/form/script/style và các widget 'bài liên quan'.

    Widget được cắt bằng cách bỏ TỪ ĐÓ TỚI HẾT (regex không khớp được cặp thẻ lồng nhau).
    Nhưng CHỈ cắt khi phía trước đã có đủ nội dung: giả định "widget luôn nằm sau nội dung
    chính" là SAI — nút share/tags nằm ngay ĐẦU nhiều bài, cắt ở đó thì giết sạch trang và
    nó bị loại nhầm là 'too_short'.
    """
    out = html or ""
    for tag in _CHROME_TAGS:
        out = re.sub(r"<%s[^>]*>.*?</%s>" % (tag, tag), " ", out, flags=re.S | re.I)
    for m in _WIDGET_CLASS.finditer(out):
        if len(html_to_text(out[:m.start()])) >= MIN_BODY_CHARS:
            return out[:m.start()]
    return out


def article_body(html):
    """HTML trang -> (html thân bài, cách lấy được). Không tìm ra -> trả cả trang.

    Lùi về cả trang là CÓ CHỦ ĐÍCH chứ không phải bỏ cuộc: nhiều site không khớp mẫu nào
    mà vẫn cho danh sách tên sạch. Mất chính xác một ít còn hơn mất trắng nguồn.
    """
    cleaned = strip_chrome(html)
    for how, pattern in _BODY_PATTERNS:
        m = pattern.search(cleaned)
        if m and len(html_to_text(m.group(1))) > 2000:
            return m.group(1), how
    return cleaned, "whole_page"


def content_gate(html, body_html=None):
    """Trang này có NỘI DUNG THẬT không? -> (ok, chẩn đoán).

    Chặn SPA trả khung template: không có cổng này thì trang HTTP 200 toàn marker đi
    thẳng vào tầng trích và LLM sẽ bịa ra nội dung từ khung rỗng.
    """
    markers = len(_TEMPLATE_MARKER.findall(html or ""))
    text = html_to_text(body_html if body_html is not None else (html or ""))
    diag = {"markers": markers, "text_chars": len(text)}
    if markers >= MAX_TEMPLATE_MARKERS:
        diag["reason"] = "template_markers"
        return False, diag
    if len(text) < MIN_BODY_CHARS:
        diag["reason"] = "too_short"
        return False, diag
    return True, diag


def page_type_gate(body_html):
    """Trang này có CẤU TRÚC LIỆT KÊ không? -> (ok, chẩn đoán).

    CỔNG YẾU, CỐ Ý ĐỂ YẾU. Đòi trang phải có mục ĐÁNH SỐ là quá chặt: nhiều bài liệt kê
    thật chỉ dùng heading không đánh số, nên cổng chặt vừa loại nhầm nguồn tốt vừa vẫn cho
    lọt trang cần chặn — giá trị ròng ÂM.

    Nên chỉ đòi *một dạng liệt kê nào đó*: mục đánh số HOẶC đủ nhiều heading. Nó bảo vệ
    NGÂN SÁCH (khỏi tải bài một-chủ-đề), KHÔNG bảo vệ tính đúng.

    Chốt chặn tính đúng nằm ở hai tầng sau, và đó mới là chỗ đáng tin: đồng thuận chéo
    nguồn (`research/consensus.py`) và giải danh tính qua nguồn bản đồ — thứ không giải ra
    được địa điểm thì bị loại, dù lọt qua đây.
    """
    n_enum = len(_ENUMERATED.findall(body_html or ""))
    n_head = len(_HEADING.findall(body_html or ""))
    ok = n_enum >= MIN_ENUMERATED or n_head >= MIN_HEADINGS
    return ok, {"enumerated": n_enum, "headings": n_head,
                "reason": None if ok else "not_a_list"}


# ======================== CHẠM MẠNG ========================

def build_search_url(query, engine="ddg"):
    """Truy vấn -> URL trang kết quả. Hàm thuần, tách ra để test không cần mạng."""
    q = urllib.parse.quote((query or "").strip())
    if not q:
        raise ValueError("Cần nội dung để tìm kiếm.")
    if (engine or "ddg").lower() == "bing":
        return "https://www.bing.com/search?q=" + q
    return _DDG_HTML + "?q=" + q


def _default_get(url, timeout=6):
    import requests
    return requests.get(url, timeout=timeout,
                        headers={"User-Agent": _UA, "Accept-Language": "vi,en;q=0.8"})


def _discover_one(query, engine, get, exclude, limit):
    """Một máy tìm kiếm -> (danh sách URL, lý do rỗng|None)."""
    try:
        resp = get(build_search_url(query, engine))
        html = getattr(resp, "text", resp)
        status = getattr(resp, "status_code", 200)
    except Exception as e:
        return [], "lỗi mạng: %s" % e
    # Mã trạng thái nói thẳng là bị chặn — phải phân biệt với "không có kết quả". Lưu ý
    # 202: máy tìm kiếm trả trang "anomaly" kèm 202 chứ không phải mã lỗi, nên không kiểm
    # mã ở đây thì nó bị hiểu nhầm thành một trang kết quả rỗng.
    if status in (202, 403, 429, 503):
        return [], "bị chặn (HTTP %s)" % status
    links = decode_bing_links(html) if engine == "bing" else decode_ddg_links(html)
    if not links:
        # HTTP 200 mà KHÔNG có link nào = bị chặn/giới hạn tần suất, KHÔNG phải "không có
        # kết quả". Trả [] lặng lẽ ở đây thì tầng trên báo nhầm là tìm không ra.
        return [], "trả 200 nhưng không có link nào (nhiều khả năng bị chặn)"
    return one_per_domain(links, exclude=exclude)[:max(1, int(limit))], None


def discover(query, http_get=None, engine="ddg", limit=8, exclude=("facebook.com",),
             diag=None, browser_search=None):
    """Truy vấn -> danh sách URL ứng viên (mỗi domain một suất).

    HAI TẦNG, và tầng hai mới là tầng đáng tin:

      1. HTTP thẳng (DDG, rồi Bing) — nhanh, nhưng **không đáng tin khi dùng lâu dài**.
      2. `browser_search(query, limit)` — đọc trang kết quả trong TRÌNH DUYỆT THẬT.

    Vì sao cần tầng hai: sau một buổi gọi liên tục từ cùng một IP thì MỌI máy tìm kiếm
    qua HTTP thẳng đều từ chối (202/403/429, hoặc trả trang render bằng JS). "Discovery
    qua HTTP thẳng là đủ" chỉ đúng khi IP còn sạch.

    Trình duyệt thật không bị chặn vì nó LÀ trình duyệt thật. Chậm hơn (mở tab, render,
    đọc DOM) nên chỉ dùng khi tầng một đã hỏng — nhưng nó là thứ giữ cho tính năng còn
    sống thay vì chết lặng.

    `browser_search` là một callable được TIÊM VÀO; lõi `research/` không biết gì về
    Chrome hay extension.

    `diag` (dict) được điền lý do nếu có — tầng trên cần phân biệt "không tìm kiếm được"
    với "tìm được nhưng trang không đọc nổi"; hai câu trả lời cho người dùng khác hẳn nhau.
    """
    get = http_get or _default_get
    order = [engine] + [e for e in ("ddg", "bing") if e != engine]
    reasons = {}
    for eng in order:
        urls, why = _discover_one(query, eng, get, exclude, limit)
        if urls:
            if diag is not None:
                diag["engine"] = eng
                diag["engine_fallback"] = eng != engine
            return urls
        reasons[eng] = why
        logger.warning("research: discovery '%s' qua %s: %s", query, eng, why)

    if browser_search is not None:
        try:
            urls = one_per_domain(browser_search(query, limit) or [], exclude=exclude)
        except Exception as e:
            reasons["browser"] = "lỗi: %s" % e
            urls = []
        if urls:
            logger.info("research: HTTP bị chặn, đã lấy %d nguồn qua trình duyệt", len(urls))
            if diag is not None:
                diag["engine"] = "browser"
                diag["engine_fallback"] = True
            return urls[:max(1, int(limit))]
        reasons.setdefault("browser", "không trả về link nào")

    if diag is not None:
        diag["discover_failed"] = reasons
    return []


def fetch_many(urls, http_get=None, max_workers=8, wall_seconds=6.0):
    """Tải SONG SONG, áp trần thời gian chung -> danh sách kết quả theo thứ tự `urls`.

    Song song là khoản tiết kiệm lớn nhất và nó MIỄN PHÍ: tổng thời gian bằng trang CHẬM
    NHẤT thay vì tổng các trang.

    Quá `wall_seconds` thì DÙNG NHỮNG TRANG ĐÃ VỀ thay vì chờ tiếp: bước thu thập không
    được phép chạy không có trần.
    """
    import concurrent.futures as cf
    import time

    get = http_get or _default_get
    results = {}
    started = time.time()

    def work(u):
        t0 = time.time()
        resp = get(u)
        return {"url": u, "domain": domain_of(u),
                "html": getattr(resp, "text", resp), "ms": int((time.time() - t0) * 1000)}

    pool = cf.ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
    try:
        futures = {pool.submit(work, u): u for u in urls or []}
        # Trần phải đặt Ở CHÍNH `as_completed`: nếu chỉ kiểm giờ SAU mỗi future xong thì
        # một nguồn treo sẽ giữ cả lượt tới khi nó tự timeout, bất kể `wall_seconds`.
        try:
            for fut in cf.as_completed(futures, timeout=max(0.1, float(wall_seconds))):
                u = futures[fut]
                try:
                    results[u] = fut.result(timeout=0)
                except Exception as e:
                    results[u] = {"url": u, "domain": domain_of(u), "html": "",
                                  "ms": None, "error": str(e)}
        except cf.TimeoutError:
            logger.info("research: quá hạn %.1fs, dùng %d/%d nguồn đã về",
                        time.time() - started, len(results), len(futures))
        for fut, u in futures.items():
            if u not in results:
                fut.cancel()
                results[u] = {"url": u, "domain": domain_of(u), "html": "", "ms": None,
                              "error": "quá hạn thu thập"}
    finally:
        # Không chờ các thread còn treo — trần thời gian phải là trần THẬT.
        pool.shutdown(wait=False)
    return [results[u] for u in (urls or []) if u in results]


def fetch_images(urls, http_get=None, max_workers=6, wall_seconds=2.5, max_bytes=2_000_000):
    """[url ảnh] -> {url: bytes}. Ảnh nào hỏng/quá hạn thì VẮNG MẶT, không có khoá rỗng.

    Tách khỏi `fetch_many` vì cần `.content` chứ không phải `.text`, và ngân sách khác hẳn:
    ảnh chỉ để xem nên quá hạn thì bỏ, không đáng giữ cả lượt trả lời lại.

    Phải tải ở ĐÂY chứ không phải trong panel: widget Tk chỉ được đụng từ main thread, và
    gọi mạng trên luồng đó sẽ treo cả giao diện.
    """
    import concurrent.futures as cf

    get = http_get or _default_get
    out = {}
    if not urls:
        return out

    def work(u):
        resp = get(u)
        data = getattr(resp, "content", None)
        if data is None and isinstance(resp, bytes):
            data = resp                        # bản giả trong test có thể trả thẳng bytes
        if not isinstance(data, bytes):
            # KHÔNG ép kiểu từ text/object: bịa ra bytes rồi đưa cho bộ giải ảnh là tạo dữ
            # liệu sai một cách im lặng. Không có `.content` thì coi như không có ảnh.
            return u, None
        return u, data[:max_bytes]

    pool = cf.ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
    try:
        futures = [pool.submit(work, u) for u in urls]
        try:
            for fut in cf.as_completed(futures, timeout=max(0.1, float(wall_seconds))):
                try:
                    url, data = fut.result(timeout=0)
                    if data:
                        out[url] = data
                except Exception as e:
                    logger.debug("research: tải ảnh lỗi: %s", e)
        except cf.TimeoutError:
            logger.info("research: quá hạn tải ảnh, dùng %d/%d tấm", len(out), len(urls))
        for fut in futures:
            fut.cancel()
    finally:
        pool.shutdown(wait=False)
    return out


def acquire(query, http_get=None, limit=8, wall_seconds=6.0, engine="ddg",
            browser_search=None, extra_queries=()):
    """TÌM -> TẢI SONG SONG -> HAI CỔNG. Trả (danh sách nguồn qua cổng, chẩn đoán).

    Mỗi nguồn: {url, domain, body_html, body_how, ms}. Chẩn đoán ghi rõ trang nào bị
    loại và VÌ SAO — cần cho việc nói thật với người dùng khi không đủ bằng chứng
    (mã `SOURCES_UNUSABLE`).
    """
    diag = {"query": query, "found": 0, "rejected": {}, "kept": 0}

    # MỞ RỘNG TRUY VẤN: mỗi biến thể là một lượt tìm kiếm riêng, gộp chung rổ URL rồi mới
    # tải MỘT lần song song. Mục tiêu không phải "câu chữ hay hơn" mà là **nhiều nguồn độc
    # lập hơn**, vì đồng thuận chỉ hình thành khi các bài có chồng lấn.
    #
    # Ghi số domain MỚI mà mỗi biến thể mang lại: biến thể nào không mang thêm gì thì nó
    # đang tiêu một lượt tìm kiếm vô ích, và số liệu này là cách duy nhất để biết.
    pool, per_query = [], {}
    for q in [query] + [x for x in (extra_queries or []) if x and x != query]:
        qdiag = {}
        got = discover(q, http_get=http_get, engine=engine, limit=limit, diag=qdiag,
                       browser_search=browser_search)
        before = len(one_per_domain(pool))
        pool.extend(got)
        after = len(one_per_domain(pool))
        per_query[q] = {"found": len(got), "new_domains": after - before,
                        "engine": qdiag.get("engine")}
        if not qdiag.get("engine") and qdiag.get("discover_failed"):
            diag.setdefault("discover_failed", qdiag["discover_failed"])

    urls = one_per_domain(pool)[:max(1, int(limit))]
    diag["queries"] = per_query
    diag["engine"] = next((v["engine"] for v in per_query.values() if v["engine"]), None)
    diag["found"] = len(urls)
    if len(per_query) > 1:
        logger.info("research: mở rộng truy vấn %s -> %d domain",
                    {q: v["new_domains"] for q, v in per_query.items()}, len(urls))
    if not urls:
        # KHÔNG gộp với ca "trang không đọc được": ở đây chưa hề tải trang nào.
        diag["failed_at"] = "discovery"
        return [], diag

    kept = []
    for row in fetch_many(urls, http_get=http_get, wall_seconds=wall_seconds):
        if row.get("error") or not row.get("html"):
            diag["rejected"][row["domain"]] = row.get("error") or "trang rỗng"
            continue
        body, how = article_body(row["html"])
        ok, cdiag = content_gate(row["html"], body)
        if not ok:
            diag["rejected"][row["domain"]] = cdiag["reason"]
            continue
        ok, pdiag = page_type_gate(body)
        if not ok:
            diag["rejected"][row["domain"]] = pdiag["reason"]
            continue
        kept.append({"url": row["url"], "domain": row["domain"],
                     "body_html": body, "body_how": how, "ms": row.get("ms")})
    diag["kept"] = len(kept)
    # Ghi TÊN domain đã giữ, không chỉ số lượng: chẩn đoán "vì sao ít ứng viên" cần biết
    # đã đọc những trang nào; log chỉ có con số thì không truy ngược được.
    diag["kept_domains"] = [k["domain"] for k in kept]
    logger.info("research: '%s' -> giữ %d/%d nguồn: %s", query, len(kept), len(urls),
                ", ".join(diag["kept_domains"]) or "(không có)")
    return kept, diag
