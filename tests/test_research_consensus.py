"""
Test đếm đồng thuận chéo nguồn (`research/consensus.py`).

Ca trung tâm: hai domain trông độc lập nhưng đăng gần như cùng một danh sách — thực
chất là một content farm
chép của nhau. Không khử trùng thì quán chi nhiều tiền SEO nhất luôn thắng.
"""

from research.consensus import (consensus, count_votes, group_duplicate_sources, jaccard)


def _key(s):
    return (s or "").strip().lower()


# --------------------------- jaccard --------------------------- #

def test_jaccard_basic():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a", "b"}, {"c"}) == 0.0
    assert round(jaccard({"a", "b", "c"}, {"a", "b", "d"}), 2) == 0.5


def test_jaccard_empty_is_zero_not_one():
    """Tập rỗng -> 0: không kết luận được thì KHÔNG gộp. Trả 1.0 sẽ gộp mọi nguồn rỗng."""
    assert jaccard(set(), set()) == 0.0
    assert jaccard(None, {"a"}) == 0.0


# --------------------------- gộp nguồn chép nhau --------------------------- #

def test_groups_the_real_seo_copy_pair():
    """Hai nguồn chồng lấn phần lớn danh sách -> phải gộp thành MỘT nguồn."""
    shared = {"kat coffee", "uu dam chay", "tropical forest", "an garden", "tayta",
              "garden cafe", "cafe vuon pho co", "vuon xinh", "cafe vuon tre",
              "khu vuon gac mai", "cafe bach thao", "vui garden", "tam art"}
    per_source = {
        "hanoitoplist.com": shared | {"the ylang", "rieng cua hanoitoplist"},
        "mytour.vn": shared | {"the ylang"},
        "kla.vn": {"o tree", "la farine", "sunny garden", "joie", "soranchi"},
    }
    groups = group_duplicate_sources(per_source)
    assert groups["hanoitoplist.com"] == groups["mytour.vn"]
    assert groups["kla.vn"] != groups["mytour.vn"]
    assert len(set(groups.values())) == 2


def test_does_not_merge_merely_similar_sources():
    """Cặp kế tiếp trong số đo chỉ 0,23 — dưới ngưỡng 0,40, KHÔNG được gộp."""
    per_source = {"a.vn": {"x1", "x2", "x3", "x4", "x5"},
                  "b.vn": {"x1", "y2", "y3", "y4", "y5"}}
    groups = group_duplicate_sources(per_source)
    assert groups["a.vn"] != groups["b.vn"]


def test_merge_is_transitive():
    """A chép B, B chép C -> cả ba là MỘT nguồn."""
    base = {"n%d" % i for i in range(10)}
    per_source = {"a.vn": base, "b.vn": base | {"z"}, "c.vn": base | {"z", "w"}}
    assert len(set(group_duplicate_sources(per_source).values())) == 1


# --------------------------- đếm phiếu --------------------------- #

def test_one_source_one_vote_even_if_repeated():
    """Trang nhắc lại tên 5 lần không được tự tạo ra 'đồng thuận'."""
    per_source = {"a.vn": ["Quán X", "Quán X", "quán x"], "b.vn": ["Quán X"]}
    rows = count_votes(per_source, _key)
    assert len(rows) == 1 and rows[0]["sources"] == 2


def test_votes_sorted_by_independent_sources():
    per_source = {"a.vn": ["A", "B"], "b.vn": ["A"], "c.vn": ["A", "C"]}
    rows = count_votes(per_source, _key)
    assert rows[0]["label"] == "A" and rows[0]["sources"] == 3


def test_key_none_items_skipped():
    rows = count_votes({"a.vn": ["", "  ", "Quán X"]}, _key)
    assert [r["label"] for r in rows] == ["Quán X"]


# --------------------------- ngưỡng --------------------------- #

def test_consensus_threshold_and_diag():
    per_source = {"a.vn": ["A", "B"], "b.vn": ["A"], "c.vn": ["A", "C"]}
    passed, ranked, diag = consensus(per_source, _key, min_sources=2)
    assert [r["label"] for r in passed] == ["A"]
    assert len(ranked) == 3                       # B, C vẫn được trả về
    assert diag["independent_sources"] == 3 and diag["passed"] == 1


def test_consensus_keeps_singletons_for_honest_reply():
    """Ứng viên 1 nguồn phải còn trong `ranked` — mã NO_CONSENSUS cần nói được lý do."""
    passed, ranked, diag = consensus({"a.vn": ["A"], "b.vn": ["B"]}, _key, min_sources=2)
    assert passed == [] and len(ranked) == 2 and diag["candidates"] == 2


def test_copy_pair_cannot_reach_threshold_alone():
    """Hai trang chép nhau chỉ đáng MỘT phiếu -> không tự đẩy nhau qua ngưỡng."""
    same = ["Quán Chép", "N1", "N2", "N3", "N4"]
    passed, _, diag = consensus({"farm1.vn": same, "farm2.vn": list(same)},
                                _key, min_sources=2)
    assert passed == []
    assert diag["independent_sources"] == 1 and diag["merged"]


def test_empty_input_safe():
    passed, ranked, diag = consensus({}, _key)
    assert passed == [] and ranked == [] and diag["sources"] == 0
