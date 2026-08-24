"""
Đồng thuận chéo nguồn — TẤT ĐỊNH, thuần, không LLM.

Tín hiệu chính lấy từ web KHÔNG phải văn xuôi mà là **mức đồng thuận về TÊN**: bao nhiêu
nguồn độc lập cùng nhắc tới một thực thể khi trả lời cùng một nhu cầu.

Vì sao đếm bằng parser chứ không cho LLM đọc từng trang: LLM tự cắt danh sách giữa chừng
nên bỏ sót nhiều tên, lại chậm hơn nhiều bậc. Parser liệt kê cạn kiệt; precision thấp hơn
của nó được xử lý ở hạ nguồn — đồng thuận ở đây, rồi giải danh tính ở tầng miền.

Cái bẫy phải đề phòng: **content farm SEO chép của nhau**. Hai domain trông độc lập có thể
đăng gần như cùng một danh sách. Không khử trùng thì quán chi nhiều tiền SEO nhất luôn thắng.
"""

from utils.logger import get_logger

logger = get_logger(__name__)

# Ngưỡng gộp nguồn: cặp chép nhau có độ trùng rất cao, còn cặp độc lập thì thấp hẳn, nên
# 0,40 nằm giữa hai mức đó — bắt đúng cặp cần bắt mà không gộp nhầm.
DUPLICATE_JACCARD = 0.40

# Số mục CHUNG tối thiểu mới được kết luận "chép nhau".
#
# Chỉ dùng Jaccard là KHÔNG đủ: hai nguồn cùng nhắc đúng một cái tên có Jaccard = 1,0 và
# sẽ bị gộp làm một — tức là hai nguồn độc lập thật sự đồng thuận lại bị triệt tiêu thành
# một phiếu, đúng ngược điều ta cần. Content farm chép cả DANH SÁCH, nên đòi hỏi chồng lấn
# phải ĐỦ LỚN mới có ý nghĩa.
MIN_SHARED_ITEMS = 5

# Số nguồn ĐỘC LẬP tối thiểu để một ứng viên được vào vòng kiểm chứng.
MIN_SOURCES = 2


def jaccard(a, b):
    """Độ chồng lấn hai tập. Tập rỗng -> 0.0 (không kết luận được thì không gộp)."""
    sa, sb = set(a or ()), set(b or ())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def looks_copied(a, b, threshold=DUPLICATE_JACCARD, min_shared=MIN_SHARED_ITEMS):
    """Hai tập mục có phải chép của nhau không. Cần CẢ chồng lấn lớn LẪN đủ nhiều mục chung."""
    sa, sb = set(a or ()), set(b or ())
    return len(sa & sb) >= max(1, int(min_shared)) and jaccard(sa, sb) > threshold


def group_duplicate_sources(per_source, threshold=DUPLICATE_JACCARD,
                            min_shared=MIN_SHARED_ITEMS):
    """{nguồn: tập khoá} -> {nguồn: id nhóm}. Nguồn chép nhau về cùng một nhóm.

    Union-find: A chép B, B chép C thì cả ba là MỘT nguồn, dù A và C không trực tiếp
    giống nhau đủ ngưỡng.
    """
    parent = {s: s for s in per_source}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    names = list(per_source)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if looks_copied(per_source[a], per_source[b], threshold, min_shared):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
    return {s: find(s) for s in names}


def count_votes(per_source_items, key_of, label_of=None):
    """{nguồn: [mục]} -> danh sách ứng viên kèm số NGUỒN ĐỘC LẬP, giảm dần.

    `key_of(mục)` -> khoá gộp (rỗng/None thì bỏ mục đó).
    `label_of(mục)` -> nhãn hiển thị; mặc định lấy chính mục.

    Một nguồn đóng góp TỐI ĐA MỘT PHIẾU cho mỗi khoá, dù nhắc bao nhiêu lần — nếu không
    thì một trang nhắc lại tên quán 5 lần sẽ tự tạo ra "đồng thuận".
    """
    label_of = label_of or (lambda x: x)
    keyed = {s: {key_of(i) for i in items if key_of(i)}
             for s, items in (per_source_items or {}).items()}
    groups = group_duplicate_sources(keyed)

    votes, labels = {}, {}
    for source, items in (per_source_items or {}).items():
        for item in items:
            k = key_of(item)
            if not k:
                continue
            votes.setdefault(k, set()).add(groups[source])
            labels.setdefault(k, label_of(item))

    out = [{"key": k, "label": labels[k], "sources": len(g), "source_ids": sorted(g)}
           for k, g in votes.items()]
    out.sort(key=lambda r: (-r["sources"], r["label"]))
    return out


def consensus(per_source_items, key_of, label_of=None, min_sources=MIN_SOURCES):
    """-> (ứng viên đạt ngưỡng, toàn bộ ứng viên đã đếm, chẩn đoán).

    Trả cả danh sách CHƯA đạt ngưỡng vì tầng phát ngôn cần nó: mã `NO_CONSENSUS` phải
    nói được "tôi chỉ thấy mỗi chỗ được nhắc một lần", chứ không phải im lặng như thể
    không tìm thấy gì.
    """
    ranked = count_votes(per_source_items, key_of, label_of)
    groups = group_duplicate_sources(
        {s: {key_of(i) for i in items if key_of(i)}
         for s, items in (per_source_items or {}).items()})
    n_independent = len(set(groups.values()))

    passed = [r for r in ranked if r["sources"] >= max(1, int(min_sources))]
    diag = {"sources": len(per_source_items or {}), "independent_sources": n_independent,
            "candidates": len(ranked), "passed": len(passed),
            "min_sources": min_sources,
            "merged": {s: g for s, g in groups.items() if s != g}}
    if diag["merged"]:
        logger.info("research: gộp nguồn chép nhau: %s", diag["merged"])
    return passed, ranked, diag
