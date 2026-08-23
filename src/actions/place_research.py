"""
Lane 3 — tìm địa điểm theo NHU CẦU, không theo loại (spec `docs/research_lane_spec.md`).

Đây là phần cắm miền địa điểm vào lõi `research/`: lõi lo tìm-tải-lọc-đếm, file này lo
phần chỉ địa điểm mới có (chuẩn hoá tên quán, giải toạ độ, khoảng cách).

NGUYÊN TẮC CHI PHỐI — DISCOVERY khác VERIFICATION (spec §3):

    Web  -> "chỗ nào có TIẾNG là nhiều cây xanh"   -> SINH ỨNG VIÊN
    Maps -> "chỗ CỤ THỂ này có thật thế không"     -> KIỂM CHỨNG

Web trả lời tốt câu thứ nhất và tệ câu thứ hai. Bài listicle của một công ty giàn giáo
vẫn kể ĐÚNG TÊN quán, nhưng lời khen trong đó không đáng tin. Nên bằng chứng từ web chỉ
cho ứng viên một SUẤT VÀO VÒNG TRONG, không bao giờ là phán quyết cuối.

Vì thế ở đây KHÔNG có nhận định nào về thẩm mỹ. File này chỉ trả về "chỗ nào được nhắc
tới, bởi mấy nguồn độc lập". Việc xác nhận quán có thật nhiều cây hay không thuộc bước
kiểm chứng bằng ảnh (L3-5), còn đang chờ quyết định ở spec §14.
"""

import time

from actions.place_identity import merge_duplicates, normalize_name
from research.acquire import acquire, fetch_images
from research.claim_cache import merge_sources
from research.consensus import MIN_SOURCES, consensus
from research.harvest import harvest_records, tokens
from utils.logger import get_logger
from utils.text_norm import norm

logger = get_logger(__name__)

# Tiền tố rác riêng của miền địa điểm, thêm vào danh sách chung của `harvest`.
PLACE_STOP_PREFIXES = ("địa chỉ", "giờ mở", "giờ hoạt động", "bảng giá", "giá cả",
                       "menu", "không gian", "đồ uống", "điểm nổi bật", "vị trí")

# NGÂN SÁCH (spec §10).
#
# GIẢI TOẠ ĐỘ MẶC ĐỊNH LÀ **LƯỜI** (`0`). Đo trong app thật 2026-08-22: một lượt research
# mất **65 giây**, trong đó **62 giây** nằm ở đúng một lời gọi `find_place` — nó chạm trần
# `MAPS_READ` 45 giây rồi còn rơi vào dự phòng OSM hỏng.
#
# Tệ hơn: bước discovery dự phòng cũng dùng trình duyệt, mà Chrome là tài nguyên NỐI TIẾP
# (một cửa sổ, một lượt). Tra bản đồ ngay sau khi vừa đọc trang kết quả là tự tranh chấp
# với chính mình.
#
# Hai phương án rẻ hơn đều đã đo và đều HỎNG:
#     Nominatim trên địa chỉ bóc được : 1/8 = 12% — không dùng được
#     find_place qua DOM              : tới 45 giây, nối tiếp
#
# Nên: trả ứng viên kèm TÊN + ẢNH + ĐỊA CHỈ (chữ) trong ~8 giây, và chỉ tra bản đồ khi
# người dùng thật sự chọn một chỗ. Đổi lại: câu trả lời đầu không có khoảng cách.
DEFAULT_RESOLVE_LIMIT = 0
DEFAULT_DISPLAY_LIMIT = 8      # số ứng viên trả về cho panel (không tốn gì thêm)
DEFAULT_FETCH_LIMIT = 8
DEFAULT_FETCH_WALL_S = 6.0


# Tiền tố THIÊN VỊ BÀI LIỆT KÊ. Vấn đề đo được ở §21.2 không phải "câu chữ chưa hay" mà là
# đường tìm kiếm qua trình duyệt trả về nhiều SITE THƯƠNG HIỆU (trang của chính một quán,
# trang trung tâm thương mại) thay vì bài liệt kê — mà đồng thuận chỉ hình thành từ bài liệt kê.
#
# "Top ..." là đúng cách các bài đó tự đặt tiêu đề, nên nó nhắm thẳng vào thứ đang thiếu.
#
# ĐÂY LÀ GIẢ THUYẾT, CHƯA ĐO ĐƯỢC: lúc viết, mọi máy tìm kiếm HTTP đều đang chặn nên không
# so được biến thể nào tốt hơn. `diag["acquire"]["queries"]` ghi số domain MỚI của từng biến
# thể để lượt chạy thật trả lời — biến thể không mang thêm domain nào thì nên bỏ.
QUERY_VARIANT_PREFIXES = ("top",)
DEFAULT_MAX_QUERIES = 2


# Từ tả THỂ LOẠI, không tả THUỘC TÍNH. Bỏ khỏi từ khoá đi tìm câu trích dẫn.
#
# Vì sao cần: trong bài về cà phê thì "cà phê" có mặt ở gần như mọi đoạn, nên câu chọn ra
# sẽ là *"quán cà phê này đồ uống ngon"* — đem làm bằng chứng cho *"nhiều cây xanh"*. Một
# câu có thật, trích đúng nguyên văn, mà vẫn không chứng minh điều đang được nói. Đó là
# kiểu hỏng nguy hiểm nhất ở đây vì nó trông hoàn toàn hợp lệ.
#
# Đây là danh sách của MIỀN ĐỊA ĐIỂM, cố ý đặt cạnh `PLACE_STOP_PREFIXES` chứ không đẩy
# vào lõi `harvest`: lõi không được biết miền này bán cà phê.
PLACE_GENERIC_TERMS = frozenset(
    # Thể loại và vị trí — có mặt ở gần như mọi đoạn của bài.
    "quán quan cà ca phê phe cafe coffee trà tra quầy nhà nha hàng ăn uống uong đồ do "
    "chỗ cho nơi noi địa dia điểm diem khu vực vuc gần gan tại tai ở và va có co "
    "những nhung các cac một mot này nay là la cho với voi khi thì thi top list "
    # LƯỢNG TỪ và từ nhấn. Chạy thật 2026-08-23: *"quán cà phê nhiều cây xanh"* trích cho
    # Tằm Art Café câu *"Quán trưng bày nhiều tác phẩm nghệ thuật..."* — khớp đúng một
    # chữ "nhiều" và nói về TRANH. Lượng từ không mang nghĩa thuộc tính, nó chỉ đo cái
    # danh từ đứng sau; để nó lại thì mọi câu có chữ "nhiều" đều thành bằng chứng.
    "nhiều nhieu ít it rất rat hơi khá kha cực cuc siêu sieu lắm lam quá qua".split())


def cache_key(need, area=None):
    """Nhu cầu (+ khu vực) -> khoá claim cache. Hàm thuần.

    Bỏ dấu và thường hoá vì cùng một câu hỏi đến từ hai đường: gõ phím có dấu, đọc bằng
    giọng thì bộ nhận dạng có khi trả về không dấu. Hai đường ấy phải trúng cùng một ô nhớ,
    nếu không thì cache gần như không bao giờ ăn.

    Chỉ KHOÁ mới bị chuẩn hoá — `need` nguyên văn vẫn đi tiếp để dựng câu tìm kiếm và câu
    đọc, vì bài liệt kê được viết bằng tiếng Việt có dấu.
    """
    core = norm(need)
    if not core:
        return ""
    return core + "|" + norm(area)


def quote_terms(need, area=None):
    """Nhu cầu (+ khu vực) -> tập từ khoá dùng để tìm câu trích dẫn. Hàm thuần.

    Bỏ tên khu vực vì nó có mặt ở mọi đoạn của mọi bài trong lượt tìm này, y hệt lý do bỏ
    từ tả thể loại. Bỏ luôn từ một ký tự và số.
    """
    words = tokens(need) - tokens(area)
    return {w for w in words - PLACE_GENERIC_TERMS if len(w) > 1 and not w.isdigit()}


def build_queries(need, area=None, max_queries=DEFAULT_MAX_QUERIES):
    """Nhu cầu (+ khu vực) -> danh sách câu tìm kiếm. Hàm thuần.

    Câu ĐẦU giữ NGUYÊN lời người dùng: bài liệt kê được viết bằng chính thứ ngôn ngữ người
    ta dùng để hỏi nhau, nên câu tự nhiên khớp tốt hơn từ khoá rút gọn.

    Các câu sau thiên vị bài liệt kê (xem `QUERY_VARIANT_PREFIXES`). Mỗi câu là một lượt
    tìm kiếm, và qua trình duyệt thì mỗi lượt tốn ~3 giây — nên mặc định chỉ 2.
    """
    core = " ".join(str(need or "").split())
    if not core:
        return []
    place = " ".join(str(area or "").split())
    base = f"{core} {place}".strip() if place else core

    out = [base]
    for prefix in QUERY_VARIANT_PREFIXES:
        if len(out) >= max(1, int(max_queries)):
            break
        out.append(f"{prefix} {base}")
    return out


def _name_key(text):
    """Khoá gộp tên quán: bỏ phần mô tả sau dấu gạch rồi chuẩn hoá.

    Listicle hay viết "The Ylang – quán cafe vườn ở Hà Nội"; phần sau dấu gạch là mô tả
    của người viết, không thuộc tên. Không cắt thì mỗi trang thành một ứng viên riêng và
    đồng thuận không bao giờ hình thành.
    """
    head = str(text or "").split(" – ")[0].split(" — ")[0].split(" - ")[0]
    return normalize_name(head)


def _display_name(text):
    return str(text or "").split(" – ")[0].split(" — ")[0].split(" - ")[0].strip()


def canonicalize_keys(per_source):
    """{nguồn: [tên]} -> {khoá dài: khoá gộp}. Gộp các biến thể của CÙNG một quán.

    Khớp khoá bằng dấu BẰNG là quá chặt cho tên quán trên blog. Đo thật 2026-08-22:

        greensm.com : "Last Minute Cafe"          -> last minute
        vincom.com.vn: "Last Minute Premium Cafe" -> last minute premium

    Cùng một quán, hai khoá, và đồng thuận không bao giờ hình thành. Với 64 tên từ 5 nguồn
    mà chỉ 4 tên đạt ngưỡng, phần lớn thiệt hại đến từ đây.

    Luật gộp: khoá NGẮN là tập con của khoá DÀI thì gộp về khoá ngắn — nhưng khoá ngắn phải
    có **ít nhất 2 token**. Không có điều kiện đó thì "Cafe Thanh" (khoá `thanh`) sẽ nuốt
    mọi quán có chữ "thanh", tức gộp nhầm hai quán khác nhau và mọi bằng chứng sau đó dính
    vào sai chỗ — hỏng im lặng, đúng thứ phải tránh.
    """
    keys = set()
    for names in (per_source or {}).values():
        for n in names:
            k = _name_key(n)
            if k:
                keys.add(k)

    alias = {}
    for long in keys:
        long_tokens = set(long.split())
        best = None
        for short in keys:
            if short == long or len(short.split()) < 2:
                continue
            if set(short.split()) < long_tokens:          # tập con THỰC SỰ
                if best is None or len(short) < len(best):
                    best = short
        if best:
            alias[long] = best
    return alias


def _harvest_all(sources, terms=()):
    """[nguồn đã tải] -> {domain: {url, records}}. Đây là "LỜI CỦA TỪNG NGUỒN".

    Bằng chứng lấy được MIỄN PHÍ từ chính trang đã tải: ảnh, địa chỉ và câu văn nằm trong
    khối ngay dưới tên quán. Đo được ảnh phủ 100%, địa chỉ 52% (spec §2.8).

    Tách khỏi `_aggregate` là điều kiện để có claim cache (L3-6): hình dạng trả về ở đây
    JSON hoá được và ghép được giữa các lượt, nên nguồn nhớ từ lượt trước và nguồn vừa
    đọc đi vào cùng một đường gộp phía sau.
    """
    by_domain = {}
    for src in sources or []:
        domain = src.get("domain") or src.get("url")
        records = harvest_records(src.get("body_html"), PLACE_STOP_PREFIXES,
                                  key_of=_name_key, base_url=src.get("url"),
                                  quote_terms=terms)
        if records:
            by_domain[domain] = {"url": src.get("url"), "records": records}
    return by_domain


def _aggregate(by_domain):
    """{domain: {records}} -> ({domain: [tên]}, {khoá: bằng chứng gom từ MỌI nguồn}).

    Ảnh ưu tiên lấy MỖI NGUỒN MỘT TẤM thay vì ba tấm của một nguồn: ba blog độc lập cùng
    chụp một không gian rợp cây là bằng chứng mạnh hơn hẳn ba góc chụp của cùng một bài PR.
    """
    per_source, evidence = {}, {}
    for domain, block in (by_domain or {}).items():
        records = (block or {}).get("records") or []
        if not records:
            continue
        per_source[domain] = [r["name"] for r in records]
        for rec in records:
            key = _name_key(rec.get("name"))
            if not key:
                continue
            slot = evidence.setdefault(key, {"addresses": [], "photos": [], "quotes": []})
            if rec.get("address"):
                slot["addresses"].append({"domain": domain, "text": rec["address"]})
            if rec.get("photos"):
                slot["photos"].append({"domain": domain, "url": rec["photos"][0]})
            if rec.get("quote"):
                slot["quotes"].append({"domain": domain, "text": rec["quote"],
                                       "hits": rec.get("quote_hits") or 0})
    return per_source, evidence


def research(need, area=None, places=None, origin=None, http_get=None,
             min_sources=MIN_SOURCES, resolve_limit=DEFAULT_RESOLVE_LIMIT,
             fetch_limit=DEFAULT_FETCH_LIMIT, wall_seconds=DEFAULT_FETCH_WALL_S,
             fetch_photos=True, browser_search=None,
             display_limit=DEFAULT_DISPLAY_LIMIT, cache=None):
    """Nhu cầu -> {outcome, results, diagnostics}.

    Cùng hình dạng trả về với `PlacesService.find_nearby/find_place` để tầng tool và tầng
    phát ngôn không phải học thêm giao diện thứ hai.

    `places` = `PlacesService` dùng để giải danh tính. None -> bỏ qua bước đó và trả ứng
    viên chỉ có tên (vẫn dùng được cho panel, chỉ thiếu khoảng cách).

    `cache` = `ClaimCache` (L3-6). None -> không nhớ gì, mỗi lượt đọc web lại từ đầu.
    """
    t0 = time.time()
    queries = build_queries(need, area)
    diag = {"need": need, "area": area, "queries": queries, "timing_ms": {}}
    if not queries:
        return {"outcome": "NO_RESULTS", "results": [], "diagnostics": diag}

    terms = quote_terms(need, area)
    diag["quote_terms"] = sorted(terms)

    # --- 1-4. tìm, tải song song, hai cổng lọc — HOẶC lấy từ bản nhớ (L3-6) ---
    sources = []          # rỗng suốt nhánh cache hit: lượt này không tải trang nào
    key = cache_key(need, area)
    remembered = cache.get(key) if (cache is not None and key) else None

    if remembered and remembered["fresh"]:
        # Còn trong cửa sổ tươi -> không đụng mạng. Thẩm mỹ của một quán không đổi trong
        # một ngày, mà đây lại là khoản đắt nhất của cả lượt.
        by_domain = remembered["sources"]
        diag["cache"] = {"mode": "hit", "age_hours": round(remembered["age_hours"], 1)}
    else:
        sources, adiag = acquire(queries[0], http_get=http_get, limit=fetch_limit,
                                 wall_seconds=wall_seconds, browser_search=browser_search,
                                 extra_queries=queries[1:])
        diag["acquire"] = adiag
        diag["timing_ms"]["acquire"] = int((time.time() - t0) * 1000)
        by_domain = _harvest_all(sources, terms) if sources else {}

        if by_domain and remembered:
            # HỢP NHẤT. §2.5 đo được tập kết quả tìm kiếm không ổn định giữa hai lần gọi;
            # gộp lại thì mỗi lượt góp thêm nguồn ĐỘC LẬP thay vì thay chỗ nguồn cũ.
            fresh_only = set(by_domain)
            by_domain = merge_sources(remembered["sources"], by_domain)
            diag["cache"] = {"mode": "merge", "age_hours": round(remembered["age_hours"], 1),
                             "from_cache": len(set(by_domain) - fresh_only)}
        elif by_domain:
            diag["cache"] = {"mode": "miss"} if cache is not None else {"mode": "off"}
        elif remembered:
            # Tìm kiếm hỏng mà còn bản nhớ -> dùng nó, và `say_research` PHẢI nói ra là
            # dữ liệu cũ. Im lặng ở đây khiến người dùng tưởng vừa đọc web xong.
            by_domain = remembered["sources"]
            diag["cache"] = {"mode": "fallback",
                             "age_hours": round(remembered["age_hours"], 1)}
        elif not sources:
            # Hai ca KHÁC HẲN nhau, không được nói chung một câu: chưa tìm kiếm được thì
            # không có "trang lấy được" nào để mà chê là không đọc nổi. Nói sai chuyện đã
            # xảy ra cũng là một kiểu bịa.
            failed_at = adiag.get("failed_at")
            outcome = "SEARCH_FAILED" if failed_at == "discovery" else "SOURCES_UNUSABLE"
            return {"outcome": outcome, "results": [], "diagnostics": diag}
        else:
            # Có trang nhưng không bóc được tên nào -> để bước đồng thuận kết luận, đúng
            # như trước khi có cache.
            diag["cache"] = {"mode": "miss"} if cache is not None else {"mode": "off"}

        if cache is not None and key and diag["cache"]["mode"] in ("miss", "merge"):
            cache.put(key, by_domain)

    if diag.get("cache", {}).get("mode") in ("hit", "merge", "fallback"):
        logger.info("research: claim cache %s (%.0f giờ tuổi, %d nguồn)",
                    diag["cache"]["mode"], diag["cache"].get("age_hours") or 0,
                    len(by_domain))

    # --- 5-6. gom bằng chứng, khử trùng nguồn, đếm đồng thuận ---
    per_source, evidence = _aggregate(by_domain)
    # Gộp biến thể tên TRƯỚC khi đếm — nếu không, "Last Minute Cafe" và "Last Minute
    # Premium Cafe" thành hai ứng viên một-nguồn thay vì một ứng viên hai-nguồn.
    alias = canonicalize_keys(per_source)
    key_of = (lambda t: alias.get(_name_key(t), _name_key(t))) if alias else _name_key
    if alias:
        logger.info("research: gộp biến thể tên: %s", alias)
    # Số tên MỖI NGUỒN đóng góp. Cần để phân biệt hai nguyên nhân trông giống nhau khi ít
    # ứng viên: nguồn vốn đã ít tên (trang của chính một quán, không phải bài liệt kê), hay
    # bộ thu hoạch đọc hụt trang đó. Thiếu con số này thì chỉ còn cách đoán.
    yield_by_source = {d: len(v) for d, v in per_source.items()}
    empty = [s.get("domain") for s in sources if s.get("domain") not in per_source]
    diag["harvest"] = {"per_source": yield_by_source, "no_names": empty}
    logger.info("research: thu hoạch %s%s", yield_by_source,
                (" | không ra tên: " + ", ".join(empty)) if empty else "")
    passed, ranked, cdiag = consensus(per_source, key_of=key_of,
                                      label_of=_display_name, min_sources=min_sources)
    diag["consensus"] = cdiag
    if not passed:
        # Có ứng viên nhưng đều một nguồn -> phải NÓI RA điều đó, không im lặng như thể
        # không tìm thấy gì (spec §13).
        diag["single_source_candidates"] = [r["label"] for r in ranked[:5]]
        return {"outcome": "NO_CONSENSUS", "results": [], "diagnostics": diag}

    # --- 7. ứng viên -> hàng kết quả. Giải toạ độ chỉ cho `resolve_limit` chỗ đầu (mặc
    #        định 0 = lười; xem ghi chú ở DEFAULT_RESOLVE_LIMIT).
    rows = [{"name": r["label"], "sources": r["sources"], "resolved": False}
            for r in passed[:max(1, int(display_limit))]]

    n_resolve = 0 if places is None else max(0, int(resolve_limit))
    diag["resolved_attempted"] = n_resolve
    if n_resolve:
        t1 = time.time()
        for row in rows[:n_resolve]:
            hit = _resolve(places, row["name"], origin=origin, area=area)
            if hit is None:
                continue
            hit.update({"sources": row["sources"], "resolved": True})
            row.clear()
            row.update(hit)
        diag["timing_ms"]["resolve"] = int((time.time() - t1) * 1000)

    # Gắn BẰNG CHỨNG XEM ĐƯỢC — thứ người dùng dùng để tự kiểm chứng (spec §12).
    # Khớp lại theo khoá tên vì `_resolve` có thể trả về tên chuẩn khác tên trên blog.
    for row in rows:
        slot = evidence.get(key_of(row.get("name")) or "") or             evidence.get(_name_key(row.get("name")) or "")
        if not slot:
            continue
        if slot["photos"]:
            row["photos"] = [p["url"] for p in slot["photos"][:3]]
            row["photo_sources"] = len(slot["photos"])
        if slot["addresses"] and not row.get("address"):
            row["address"] = slot["addresses"][0]["text"]
        if slot["quotes"]:
            # Câu khớp NHIỀU từ khoá nhất trong tất cả các nguồn; hoà thì `max` giữ nguồn
            # đầu. Chỉ hiện MỘT câu: thẻ có ba tấm ảnh đã đủ dày, thêm ba câu thì người
            # dùng ngừng đọc — mà bằng chứng không được đọc thì không phải bằng chứng.
            #
            # CẢNH BÁO cho người sửa sau: `quote` ở đây là VĂN BLOG (thường là bài PR),
            # KHÔNG phải review khách viết. `place_ranking.evidence_score` cũng đọc trường
            # tên `quote` nhưng nó được thiết kế cho review Maps. Đừng cho hàng Lane 3 chạy
            # qua `score_place` mà không tách hai nguồn ra: khi đó lời tự khen của quán sẽ
            # tự chấm điểm cho chính quán đó — đúng cái vòng tròn mà §3 dựng lên để tránh.
            best = max(slot["quotes"], key=lambda q: q["hits"])
            row["quote"] = best["text"]
            row["quote_source"] = best["domain"]

    rows = merge_duplicates(rows)

    # Trích dẫn đến từ MẤY nguồn khác nhau. Chạy thật 2026-08-23: 6/6 chỗ có trích dẫn
    # nhưng 5 câu cùng một blog, vì site đó viết theo khuôn *"Nếu bạn muốn tìm một quán
    # cafe nhiều cây xanh ở Hà Nội thì đừng bỏ qua X"* — câu ấy khớp nhiều từ khoá nhất
    # nên luôn thắng, trong khi nó chỉ chép lại câu hỏi và không tả gì về quán.
    #
    # Tách "câu tả thật" khỏi "câu nhắc lại" bằng code thuần thì phải có danh sách hư từ
    # tiếng Việt — đúng thứ đang cố tránh. Nên: ĐO trước, sửa sau. Con số này ở đây để
    # lượt chạy thật trả lời, y như `acquire.queries` ở §22.2.
    quoted = [r for r in rows if r.get("quote")]
    if quoted:
        diag["quotes"] = {"rows": len(quoted),
                          "domains": len({r["quote_source"] for r in quoted})}

    # Tải ảnh về BYTES cho panel. Chỉ tấm ĐẦU của mỗi chỗ, ngân sách riêng 2,5 giây, hỏng
    # thì bỏ — ảnh là thứ để xem, không đáng giữ cả câu trả lời lại vì nó.
    if fetch_photos:
        t2 = time.time()
        first = [r["photos"][0] for r in rows if r.get("photos")]
        blobs = fetch_images(first, http_get=http_get)
        for row in rows:
            data = blobs.get((row.get("photos") or [None])[0])
            if data:
                row["photo_data"] = [data]
        diag["timing_ms"]["photos"] = int((time.time() - t2) * 1000)
        diag["photos_fetched"] = len(blobs)

    diag["timing_ms"]["total"] = int((time.time() - t0) * 1000)
    diag["resolved_ok"] = sum(1 for r in rows if r.get("resolved"))

    if n_resolve and not any(r.get("resolved") for r in rows[:n_resolve]):
        # ĐÃ thử tra bản đồ mà không ra chỗ nào -> nói đúng như vậy, không nhận vơ.
        # Chỉ áp khi thực sự có thử: chế độ lười không tra gì thì không được kết luận gì.
        return {"outcome": "INSUFFICIENT_EVIDENCE", "results": [], "diagnostics": diag}

    rows.sort(key=lambda r: (-(r.get("sources") or 0),
                             r.get("distance_km") if r.get("distance_km") is not None else 9e9))
    return {"outcome": "OK", "results": rows, "diagnostics": diag}


def _resolve(places, name, origin=None, area=None):
    """Tên quán -> bản ghi có toạ độ, hoặc None nếu không tra ra.

    Dùng ĐÚNG `find_place` mà các tool khác dùng, không viết đường tra thứ hai — bài học
    `set_my_location` vs `find_nearby` (phụ lục S2 của `smart_places_spec.md`): để hai
    đường song song thì cùng một chuỗi cho hai kết quả khác nhau.
    """
    try:
        out = places.find_place(name, origin=origin, area=area)
    except Exception as e:
        logger.warning("place_research: tra '%s' lỗi: %s", name, e)
        return None
    if out.get("outcome") != "OK" or not out.get("results"):
        return None
    top = dict(out["results"][0])
    top["name"] = top.get("name") or name
    return top


# ======================== CÂU ĐỌC ========================

# Khi nào phải NÓI RA rằng các bài viết ít trùng nhau (spec §22.1).
#
# Hai điều kiện, và phải có CẢ HAI. Chỉ xét tỉ lệ thì câu này bật cả ở lượt tốt: Hà Nội cho
# 8 chỗ đạt ngưỡng trên ~40 ứng viên — tỉ lệ thấp y hệt Thủ Đức, nhưng câu trả lời 8 chỗ
# không hề mỏng nên không ai hiểu nhầm. Cái sinh ra hiểu nhầm là câu trả lời TRÔNG MỎNG
# trong khi thực tế đã thấy rất nhiều tên.
#
#     Thủ Đức : 34 ứng viên, 1 đạt ngưỡng  -> bật  (đúng ca §22.1 mô tả)
#     Hà Nội  : ~40 ứng viên, 8 đạt ngưỡng -> tắt
#     khu nhỏ :  6 ứng viên, 1 đạt ngưỡng  -> tắt  (đúng là tìm được ít, không phải bất đồng)
SPARSE_MIN_CANDIDATES = 10
SPARSE_MAX_PASSED = 3


def say_sparse_note(cdiag):
    """Chẩn đoán đồng thuận -> câu nói thêm khi các bài ít trùng nhau. Hàm thuần.

    Im lặng ở ca này khiến người dùng hiểu "khu vực này chỉ có ngần đó quán", trong khi sự
    thật là *các bài viết không đồng thuận với nhau*. Hai điều khác hẳn nhau (§22.1).
    """
    total = int((cdiag or {}).get("candidates") or 0)
    passed = int((cdiag or {}).get("passed") or 0)
    if total < SPARSE_MIN_CANDIDATES or passed > SPARSE_MAX_PASSED:
        return ""
    return (f"(Ở khu vực này các bài viết ít trùng nhau — tôi thấy {total} chỗ được nhắc "
            f"tới nhưng phần lớn chỉ ở một nguồn.)")


def say_age(hours):
    """Số giờ -> cách nói tuổi của dữ liệu. Hàm thuần."""
    h = max(0.0, float(hours or 0))
    if h < 2:
        return "vừa nãy"
    if h < 48:
        return "%d tiếng trước" % int(round(h))
    return "%d ngày trước" % int(round(h / 24))


def say_research(out, need, speak_limit=3):
    """Kết quả -> câu đọc cho người dùng. Hàm thuần.

    RÀNG BUỘC PHÁT NGÔN (spec §3, I-L3-3): tầng này chỉ biết *bao nhiêu nguồn nhắc tới*,
    nó KHÔNG biết quán có thật sự nhiều cây hay không. Nên câu nói bắt buộc ở dạng
    "được N nguồn nhắc tới khi nói về X" — CẤM dạng "quán này nhiều cây xanh".

    Đây là quy tắc kế thừa từ F1.5 §5 và là thứ dễ trôi nhất khi sửa về sau: câu suy diễn
    nghe thuyết phục hơn hẳn câu trích dẫn, nên phải chặn ngay ở tầng sinh câu.

    Khi dữ liệu đến từ BẢN NHỚ vì lượt tìm hỏng (L3-6, chế độ `fallback`), câu trả lời mở
    đầu bằng lời nói rõ điều đó. Đây cùng một luật với I-L3-9: không được âm thầm đưa ra
    thứ khác với thứ người dùng tưởng mình đang nhận.
    """
    cache = (out.get("diagnostics") or {}).get("cache") or {}
    body = _say_outcome(out, need, speak_limit)
    if cache.get("mode") != "fallback":
        return body
    return ("Lúc này tôi không tìm mới được trên mạng, nên đây là những gì tôi đọc được "
            + say_age(cache.get("age_hours")) + ". " + body)


def _say_outcome(out, need, speak_limit=3):
    from utils.units import say_distance

    outcome = out.get("outcome")
    rows = out.get("results") or []
    diag = out.get("diagnostics") or {}
    what = " ".join(str(need or "").split()) or "yêu cầu đó"

    if outcome == "SEARCH_FAILED":
        return (f"Lúc này tôi không tìm kiếm được trên mạng nên chưa tra được {what}. "
                f"Bạn thử lại sau một lát giúp tôi nhé.")

    if outcome == "SOURCES_UNUSABLE":
        return (f"Tôi có tìm nhưng các trang lấy được đều không đọc được nội dung, "
                f"nên chưa có gì để nói về {what}.")

    if outcome == "NO_CONSENSUS":
        seen = diag.get("single_source_candidates") or []
        head = (f"Tôi có thấy vài chỗ khi tìm {what}, nhưng mỗi chỗ chỉ được đúng một "
                f"nguồn nhắc tới nên chưa đủ để tôi tin.")
        if seen:
            head += " Ví dụ: " + ", ".join(seen[:3]) + "."
        return head

    if outcome == "INSUFFICIENT_EVIDENCE":
        return (f"Có mấy chỗ được nhiều nguồn nhắc tới khi nói về {what}, nhưng tôi chưa "
                f"tra ra được chỗ nào trên bản đồ nên chưa dám đưa cho bạn.")

    if outcome != "OK" or not rows:
        return f"Tôi chưa tìm được chỗ nào cho {what}."

    n_src = (diag.get("consensus") or {}).get("independent_sources")
    lines = []
    for i, row in enumerate(rows[:max(1, int(speak_limit))], 1):
        bits = [f"{row['sources']} nguồn nhắc tới"]
        far = say_distance(row.get("distance_km"))
        if far:
            bits.append(far)
        lines.append(f"{i}. {row['name']} ({', '.join(bits)})")

    head = f"Tôi đọc {n_src} nguồn về {what}" if n_src else f"Tôi tìm về {what}"
    head += f" và có {len(rows)} chỗ được nhắc lại ở nhiều nguồn"
    if len(rows) > speak_limit:
        head += f", đọc cho bạn {min(len(rows), speak_limit)} chỗ đầu"

    tail = [head + ":\n" + "\n".join(lines)]
    note = say_sparse_note(diag.get("consensus") or {})
    if note:
        tail.append(note)
    if not any(r.get("distance_km") is not None for r in rows):
        # Chế độ giải toạ độ LƯỜI (§19.4): chưa tra bản đồ nên chưa lọc theo khoảng cách.
        # Thẻ trong panel đã ghi "(chưa tra được trên bản đồ)" nhưng CÂU ĐỌC thì chưa —
        # mà với trợ lý giọng nói, câu đọc mới là thứ người dùng thật sự nhận. Im lặng ở
        # đây khiến "quán cà phê nhiều cây xanh gần đây" nghe như đã lọc theo "gần đây".
        tail.append("Tôi chưa tra bản đồ nên chưa lọc theo khoảng cách — bảo tôi mở chỗ "
                    "nào thì tôi tra chỗ đó.")
    # Ghi chú xuống DÒNG RIÊNG: phần trên kết thúc bằng danh sách đánh số, nối tiếp bằng
    # dấu cách thì câu ghi chú trông như phần đuôi của mục cuối cùng.
    return tail[0] + ("\n" + " ".join(tail[1:]) if len(tail) > 1 else "")
