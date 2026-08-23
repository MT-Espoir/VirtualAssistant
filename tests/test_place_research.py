"""
Test Lane 3 — tìm địa điểm theo NHU CẦU (`research/harvest.py` + `actions/place_research.py`).

Ràng buộc quan trọng nhất được khoá ở đây: **web chỉ SINH ỨNG VIÊN, không phán quyết**.
Không có nhận định thẩm mỹ nào được sinh ra ở tầng này; nhiều nguồn nhắc tới mà tra không
ra chỗ thật thì phải trả `INSUFFICIENT_EVIDENCE`, không được nhận vơ.

Không test nào chạm mạng: `http_get` và `places` đều tiêm vào.
"""

from actions.place_research import build_queries, research
from research.harvest import (clean_candidate, harvest_names, harvest_per_source, is_noise,
                              page_ordinals)


# --------------------------- thu hoạch tên --------------------------- #

def test_clean_candidate_strips_numbering():
    assert clean_candidate("1. Tropical Forest") == "Tropical Forest"
    assert clean_candidate("12) KAT Coffee ") == "KAT Coffee"


def test_clean_candidate_rejects_sentences():
    assert clean_candidate("Đây là một câu văn rất dài kể về quán cà phê và cây cối xung quanh") == ""
    assert clean_candidate("ab") == ""


def test_is_noise_catches_wordpress_chrome():
    """Boilerplate WordPress đồng thuận chéo nguồn TỐT HƠN nội dung thật — phải chặn."""
    assert is_noise("Để lại một bình luận Hủy")
    assert is_noise("Danh mục – Sản phẩm")
    assert is_noise("Đăng nhập")
    assert not is_noise("Tropical Forest")


def test_is_noise_accepts_domain_stop_prefixes():
    assert is_noise("Địa chỉ quán", stop_prefixes=("địa chỉ",))
    assert not is_noise("Địa chỉ quán")


def test_harvest_names_from_headings_and_numbered_items():
    body = ("<h2>1. Tropical Forest</h2>"
            "<h3>2. KAT Coffee</h3>"
            "<li>3. The Ylang</li>"
            "<li>không đánh số nên bỏ qua</li>"
            "<p>Tên nằm trong câu văn thì không lấy</p>")
    assert harvest_names(body) == ["Tropical Forest", "KAT Coffee", "The Ylang"]


def test_harvest_names_dedupes_within_page():
    body = "<h2>Trill Bistro</h2><h3>Trill Bistro</h3>"
    assert harvest_names(body) == ["Trill Bistro"]


def test_harvest_names_uses_domain_key_for_dedupe():
    """Tầng miền truyền hàm chuẩn hoá vào -> 'Quán cà phê Trill' và 'Trill' là MỘT."""
    from actions.place_research import _name_key
    body = "<h2>Quán cà phê Trill</h2><h2>Trill</h2>"
    assert len(harvest_names(body, key_of=_name_key)) == 1


def test_harvest_per_source_skips_empty_sources():
    sources = [{"domain": "a.vn", "body_html": "<h2>1. Quán A</h2>"},
               {"domain": "b.vn", "body_html": "<p>không có gì</p>"}]
    assert list(harvest_per_source(sources)) == ["a.vn"]


# --------------------------- dựng câu tìm kiếm --------------------------- #

def test_build_queries_keeps_user_wording_first():
    """Câu ĐẦU phải là NGUYÊN VĂN lời người dùng — biến thể chỉ đứng sau."""
    qs = build_queries("quán cà phê nhiều cây xanh", "Hà Nội")
    assert qs[0] == "quán cà phê nhiều cây xanh Hà Nội"


def test_build_queries_adds_listicle_variant():
    """Biến thể thiên vị BÀI LIỆT KÊ — thứ đang thiếu khi tìm qua trình duyệt (§21.2)."""
    qs = build_queries("quán cà phê nhiều cây xanh", "Thủ Đức")
    assert len(qs) == 2 and qs[1].startswith("top ")


def test_build_queries_respects_max():
    """Mỗi biến thể là một lượt tìm kiếm ~3 giây qua trình duyệt -> phải chặn được."""
    assert len(build_queries("quán cà phê", "Hà Nội", max_queries=1)) == 1


def test_build_queries_without_area():
    assert build_queries("quán cà phê nhiều cây xanh")[0] == "quán cà phê nhiều cây xanh"


def test_build_queries_empty_need():
    assert build_queries("  ") == []


# --------------------------- xuyên tầng --------------------------- #

class _Resp:
    def __init__(self, text):
        self.text = text


def _listicle(names):
    items = "".join("<h2>%d. %s</h2>" % (i, n) for i, n in enumerate(names, 1))
    return ("<article>" + items + "<p>" + ("Không gian nhiều cây xanh. " * 200)
            + "</p></article>")


def _fake_web(pages):
    def get(url):
        if "duckduckgo" in url:
            import urllib.parse
            return _Resp("".join("uddg=%s " % urllib.parse.quote(u, safe="")
                                 for u in pages))
        return _Resp(pages[url])
    return get


class _FakePlaces:
    """Giả `PlacesService`: chỉ biết những quán trong `known`."""
    def __init__(self, known):
        self.known = known
        self.calls = []

    def find_place(self, name, origin=None, area=None):
        self.calls.append(name)
        for key, row in self.known.items():
            if key.lower() in name.lower():
                return {"outcome": "OK", "results": [dict(row)]}
        return {"outcome": "NO_RESULTS", "results": []}


def test_research_ok_path_ranks_by_consensus():
    # Tên "riêng" phải KHÁC KHOÁ nhau: "Riêng của A/B/C" đều rút về "rieng" (vì "của"
    # nằm trong GENERIC_TOKENS) nên gộp thành một ứng viên 3 nguồn và leo lên đầu bảng.
    pages = {
        "https://a.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "Quán Alpha Riêng"]),
        "https://b.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "Quán Beta Riêng"]),
        "https://c.vn/x": _listicle(["Tropical Forest", "Quán Gamma Riêng", "Quán Delta Riêng"]),
    }
    places = _FakePlaces({
        "Tropical Forest": {"name": "Tropical Forest", "lat": 21.03, "lng": 105.79,
                            "distance_km": 1.2},
        "KAT Coffee": {"name": "KAT Coffee", "lat": 21.04, "lng": 105.80,
                       "distance_km": 0.4},
    })
    out = research("quán cà phê nhiều cây xanh", area="Hà Nội", places=places,
                   http_get=_fake_web(pages), resolve_limit=2)

    assert out["outcome"] == "OK"
    names = [r["name"] for r in out["results"]]
    assert names[0] == "Tropical Forest", "3 nguồn phải xếp trên 2 nguồn, dù xa hơn"
    assert out["results"][0]["sources"] == 3
    assert set(names) == {"Tropical Forest", "KAT Coffee"}


def test_research_no_consensus_names_the_singletons():
    """Đều một nguồn -> nói ra được là đã thấy gì, không im lặng."""
    pages = {"https://a.vn/x": _listicle(["Bagang Café", "Philo Garden", "Annamoi"]),
             "https://b.vn/x": _listicle(["Soranchi", "Treeland Coffee", "La Farine"])}
    out = research("quán yên tĩnh", places=_FakePlaces({}), http_get=_fake_web(pages))
    assert out["outcome"] == "NO_CONSENSUS"
    assert out["diagnostics"]["single_source_candidates"]


def test_research_insufficient_evidence_when_nothing_resolves():
    """Nhiều nguồn nhắc tới nhưng tra không ra chỗ thật -> KHÔNG được nhận vơ."""
    pages = {"https://a.vn/x": _listicle(["Quán Không Tồn Tại", "Chỗ Hư Cấu", "Riêng A"]),
             "https://b.vn/x": _listicle(["Quán Không Tồn Tại", "Chỗ Hư Cấu", "Riêng B"])}
    out = research("quán cà phê", places=_FakePlaces({}), http_get=_fake_web(pages),
                   resolve_limit=2)
    assert out["outcome"] == "INSUFFICIENT_EVIDENCE" and out["results"] == []


def test_research_sources_unusable_when_all_gated_out():
    pages = {"https://spa.vn/x": "<div ng-repeat='a'>{{b}}</div>" * 12}
    out = research("quán cà phê", places=_FakePlaces({}), http_get=_fake_web(pages))
    assert out["outcome"] == "SOURCES_UNUSABLE"


def test_research_respects_resolve_budget():
    """Mỗi lần giải danh tính là một lượt tra bản đồ (~12s) -> phải chặn trần."""
    common = ["Tropical Forest", "KAT Coffee", "The Ylang", "Trill Bistro",
              "Haawa Cafe", "Philo Garden"]
    # Mỗi nguồn phải có nhiều mục RIÊNG, nếu không thì chồng lấn vượt ngưỡng và ba nguồn
    # bị gộp thành một (đúng luật khử trùng) — lúc đó không ứng viên nào đạt ngưỡng.
    # Nhãn phân biệt phải NHIỀU ký tự: token một ký tự bị `tokens()` loại, nên "Riêng A
    # số 1" và "Riêng B số 1" sẽ về cùng một khoá và ba nguồn lại bị gộp.
    def page(tag):
        return _listicle(common + ["Quán %s Thứ %d" % (tag, i) for i in range(1, 13)])

    pages = {"https://a.vn/x": page("Alpha"), "https://b.vn/x": page("Beta"),
             "https://c.vn/x": page("Gamma")}
    places = _FakePlaces({n: {"name": n, "lat": 21.0 + i / 100.0, "lng": 105.0}
                          for i, n in enumerate(common)})
    out = research("quán cà phê", places=places, http_get=_fake_web(pages), resolve_limit=2)
    assert out["diagnostics"]["consensus"]["independent_sources"] == 3
    assert len(places.calls) == 2, "gọi quá trần %d lần" % len(places.calls)


def test_research_without_places_returns_names_only():
    """Chưa có tầng bản đồ vẫn phải trả được ứng viên cho panel — chỉ thiếu khoảng cách."""
    pages = {"https://a.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "Riêng A"]),
             "https://b.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "Riêng B"])}
    out = research("quán cà phê", places=None, http_get=_fake_web(pages))
    assert out["outcome"] == "OK"
    assert all(r["resolved"] is False for r in out["results"])
    assert out["results"][0]["sources"] == 2


def test_research_makes_no_aesthetic_claim():
    """Tầng này KHÔNG được sinh nhận định thẩm mỹ nào — web chỉ cho suất vào vòng trong."""
    pages = {"https://a.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "Riêng A"]),
             "https://b.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "Riêng B"])}
    out = research("quán cà phê nhiều cây xanh", places=None, http_get=_fake_web(pages))
    for row in out["results"]:
        # Không có trường nào mang PHÁN QUYẾT về thuộc tính được hỏi. `photos`/`address`
        # là bằng chứng thô để người dùng tự nhìn, không phải kết luận của hệ thống.
        assert "quiet" not in row and "green" not in row and "verdict" not in row
        assert "match_score" not in row and "visual_match" not in row
        assert set(row) <= {"name", "sources", "resolved", "canonical_id", "brand_key",
                            "aliases", "photos", "photo_sources", "address",
                            # `quote` là câu NGUYÊN VĂN của người viết kèm tên nguồn —
                            # cùng loại với `photos`: bằng chứng thô để người dùng tự
                            # nhìn, không phải kết luận của hệ thống.
                            "quote", "quote_source"}


def test_research_empty_need_safe():
    out = research("", places=None, http_get=lambda u: _Resp(""))
    assert out["outcome"] == "NO_RESULTS"


# --------------------------- câu đọc: quy tắc chống bịa --------------------------- #

def test_say_research_never_asserts_the_quality():
    """KHOÁ RÀNG BUỘC I-L3-3: chỉ được nói 'nguồn nhắc tới', không được khẳng định."""
    from actions.place_research import say_research
    out = {"outcome": "OK",
           "results": [{"name": "Tropical Forest", "sources": 3, "distance_km": 1.2}],
           "diagnostics": {"consensus": {"independent_sources": 6}}}
    text = say_research(out, "quán cà phê nhiều cây xanh")
    assert "3 nguồn nhắc tới" in text
    # KHÔNG được xuất hiện câu khẳng định quán có tính chất đó
    assert "quán này nhiều cây" not in text.lower()
    assert "rất nhiều cây" not in text.lower()


def test_say_research_no_consensus_is_honest():
    from actions.place_research import say_research
    out = {"outcome": "NO_CONSENSUS", "results": [],
           "diagnostics": {"single_source_candidates": ["Bagang Café", "Annamoi"]}}
    text = say_research(out, "quán yên tĩnh")
    assert "một nguồn" in text and "Bagang Café" in text


def test_say_research_insufficient_evidence_does_not_claim():
    from actions.place_research import say_research
    text = say_research({"outcome": "INSUFFICIENT_EVIDENCE", "results": []}, "quán cổ")
    assert "chưa tra ra được" in text


def test_say_research_sources_unusable():
    from actions.place_research import say_research
    text = say_research({"outcome": "SOURCES_UNUSABLE", "results": []}, "quán cổ")
    assert "không đọc được nội dung" in text


def test_say_research_omits_distance_when_unknown():
    """Chưa giải toạ độ -> KHÔNG được bịa khoảng cách, và phải NÓI RA là chưa lọc.

    Hai vế, không được thiếu vế nào. Không bịa thôi thì vẫn để người dùng tưởng "gần đây"
    đã được áp: thẻ trong panel có ghi "(chưa tra được trên bản đồ)" nhưng câu ĐỌC mới là
    thứ người dùng nhận, mà giọng nói thì không có thẻ nào để nhìn.
    """
    import re
    from actions.place_research import say_research
    out = {"outcome": "OK",
           "results": [{"name": "KAT Coffee", "sources": 2, "resolved": False}],
           "diagnostics": {}}
    text = say_research(out, "quán cà phê")
    assert not re.search(r"cách\s+[\d,.]+\s*(km|mét|m\b)", text), "không được bịa số"
    assert "2 nguồn nhắc tới" in text
    assert "chưa lọc theo khoảng cách" in text


# --------------------------- bằng chứng lấy từ chính trang đã tải --------------------------- #

def _listicle_rich(entries):
    """entries = [(tên, địa chỉ|None, [url ảnh])] -> HTML bài dạng danh sách."""
    parts = []
    for i, (name, addr, imgs) in enumerate(entries, 1):
        parts.append("<h2>%d. %s</h2>" % (i, name))
        for u in imgs:
            parts.append('<img src="%s">' % u)
        if addr:
            parts.append("<p>Địa chỉ: %s</p>" % addr)
        parts.append("<p>" + ("Không gian nhiều cây xanh. " * 60) + "</p>")
    return "<article>" + "".join(parts) + "</article>"


def test_research_attaches_photos_from_each_source():
    """Ảnh ưu tiên MỖI NGUỒN MỘT TẤM — 3 blog độc lập mạnh hơn 3 góc chụp cùng một bài."""
    pages = {
        "https://a.vn/x": _listicle_rich([
            ("Tropical Forest", None, ["https://a.vn/tf1.jpg", "https://a.vn/tf2.jpg"]),
            ("KAT Coffee", None, ["https://a.vn/kat.jpg"]), ("Riêng A", None, [])]),
        "https://b.vn/x": _listicle_rich([
            ("Tropical Forest", None, ["https://b.vn/tf.jpg"]),
            ("KAT Coffee", None, ["https://b.vn/kat.jpg"]), ("Riêng B", None, [])]),
    }
    out = research("quán nhiều cây", places=None, http_get=_fake_web(pages))
    top = out["results"][0]
    assert top["photo_sources"] == 2, "phải gom ảnh từ CẢ HAI nguồn"
    assert len(set(p.split("/")[2] for p in top["photos"])) == 2


def test_research_attaches_address_when_page_has_it():
    pages = {
        "https://a.vn/x": _listicle_rich([
            ("Loading T", "8 Chân Cầm, Q. Hoàn Kiếm, Hà Nội", ["https://a.vn/1.jpg"]),
            ("Cộng Cà phê", None, []), ("Riêng A", None, [])]),
        "https://b.vn/x": _listicle_rich([
            ("Loading T", None, ["https://b.vn/1.jpg"]),
            ("Cộng Cà phê", None, []), ("Riêng B", None, [])]),
    }
    out = research("quán cổ", places=None, http_get=_fake_web(pages))
    loading = [r for r in out["results"] if "Loading" in r["name"]][0]
    assert loading["address"] == "8 Chân Cầm, Q. Hoàn Kiếm, Hà Nội"


def test_research_no_address_key_when_absent():
    """Không có địa chỉ thì KHÔNG được có trường address rỗng — thiếu là im lặng."""
    pages = {"https://a.vn/x": _listicle_rich([("Quán Một", None, []), ("Quán Hai", None, []),
                                               ("Riêng A", None, [])]),
             "https://b.vn/x": _listicle_rich([("Quán Một", None, []), ("Quán Hai", None, []),
                                               ("Riêng B", None, [])])}
    out = research("quán cổ", places=None, http_get=_fake_web(pages))
    assert all("address" not in r for r in out["results"])


def test_say_research_search_failed_does_not_claim_pages_were_read():
    """Chưa tải trang nào thì KHÔNG được nói 'các trang lấy được không đọc được'.

    Nói sai chuyện đã xảy ra cũng là một kiểu bịa. Chạy thật 2026-08-22 mắc đúng lỗi này.
    """
    from actions.place_research import say_research
    text = say_research({"outcome": "SEARCH_FAILED", "results": []}, "quán cà phê retro")
    assert "không tìm kiếm được" in text
    assert "trang lấy được" not in text


def test_research_search_failed_when_discovery_empty():
    out = research("quán retro", places=None, http_get=lambda u: _Resp("<html></html>"))
    assert out["outcome"] == "SEARCH_FAILED"


# --------------------------- giải toạ độ LƯỜI (mặc định) --------------------------- #
#
# Chạy thật 2026-08-22: một lượt research mất 65 giây, trong đó 62 giây nằm ở ĐÚNG MỘT lời
# gọi find_place (chạm trần MAPS_READ 45s rồi rơi vào dự phòng OSM hỏng). Và bước discovery
# dự phòng cũng dùng trình duyệt — Chrome là tài nguyên NỐI TIẾP, nên tra bản đồ ngay sau
# khi vừa đọc trang kết quả là tự tranh chấp với chính mình.

def test_research_does_not_touch_map_by_default():
    """Mặc định KHÔNG tra bản đồ: đó là toàn bộ khoản 57 giây tiết kiệm được."""
    pages = {"https://a.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "Quán Alpha"]),
             "https://b.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "Quán Beta"])}
    places = _FakePlaces({"Tropical Forest": {"name": "Tropical Forest", "lat": 21.0,
                                              "lng": 105.0}})
    out = research("quán cà phê", places=places, http_get=_fake_web(pages))
    assert places.calls == [], "chế độ lười mà vẫn gọi bản đồ"
    assert out["outcome"] == "OK"
    assert all(r["resolved"] is False for r in out["results"])


def test_research_returns_all_passing_candidates_not_just_resolved():
    """Panel hiện được nhiều chỗ hơn vì không còn bị chặn bởi trần giải toạ độ."""
    pages = {"https://a.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "The Ylang",
                                          "Quán Alpha"]),
             "https://b.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "The Ylang",
                                          "Quán Beta"])}
    out = research("quán cà phê", places=None, http_get=_fake_web(pages))
    assert len(out["results"]) == 3


def test_research_lazy_mode_never_claims_insufficient_evidence():
    """Không tra gì thì KHÔNG được kết luận 'tra không ra' — đó là nói về việc chưa làm."""
    pages = {"https://a.vn/x": _listicle(["Quán Không Có Thật", "Chỗ Hư Cấu", "Quán Alpha"]),
             "https://b.vn/x": _listicle(["Quán Không Có Thật", "Chỗ Hư Cấu", "Quán Beta"])}
    out = research("quán cà phê", places=_FakePlaces({}), http_get=_fake_web(pages))
    assert out["outcome"] == "OK"


def test_research_reports_harvest_yield_per_source():
    """Ít ứng viên có hai nguyên nhân trông giống hệt nhau — phải phân biệt được.

    Nguồn vốn ít tên (trang của CHÍNH một quán) khác hẳn bộ thu hoạch đọc hụt trang. Không
    có số liệu theo từng nguồn thì chỉ còn cách đoán, mà đoán đã sai nhiều lần.
    """
    pages = {
        "https://list.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "The Ylang",
                                        "Quán Alpha"]),
        "https://other.vn/x": _listicle(["Tropical Forest", "KAT Coffee", "Quán Beta"]),
        # Trang của chính một quán: dài, qua cổng, nhưng không liệt kê quán nào khác.
        "https://mycafe.vn/x": ("<article><h2>Giới thiệu</h2><h2>Không gian</h2>"
                                "<h2>Menu</h2><h2>Liên hệ</h2><h2>Đường đi</h2><p>"
                                + ("Quán của chúng tôi rất nhiều cây xanh. " * 200)
                                + "</p></article>"),
    }
    out = research("quán cà phê", places=None, http_get=_fake_web(pages))
    per = out["diagnostics"]["harvest"]["per_source"]

    # Điều cần thấy được là ĐỘ CHÊNH: bài liệt kê cho nhiều tên, trang một-quán gần như
    # không cho tên nào (thứ nó cho ra là nhiễu tiêu đề mục, ví dụ "Đường đi").
    assert per["list.vn"] == 4 and per["other.vn"] == 3
    assert per.get("mycafe.vn", 0) <= 1, (
        "trang của chính một quán không được trông giống một bài liệt kê")
    assert per["list.vn"] > per.get("mycafe.vn", 0) * 3


# --------------------------- hai lỗi tìm ra khi đo nguồn Thủ Đức --------------------------- #

def test_clean_candidate_cuts_description_before_measuring_length():
    """HỒI QUY: đo độ dài TRƯỚC khi cắt mô tả -> loại oan tên thật.

    Chạy thật 2026-08-22: `vincom.com.vn` viết "Elmar Coffee - Quán cà phê phong cách Tây
    Ban Nha"; cả cụm 9 từ nên bị ngưỡng MAX_WORDS loại, và nguồn đó rớt từ 10 tên xuống 2.
    """
    assert clean_candidate("Elmar Coffee - Quán cà phê phong cách Tây Ban Nha") == "Elmar Coffee"
    assert clean_candidate("Last Minute Premium Cafe - Quán cà phê 24/24 tại Thủ Đức") \
        == "Last Minute Premium Cafe"
    # Tiêu đề MỤC không có dấu gạch thì vẫn phải bị loại vì quá dài
    assert clean_candidate("Quán cafe sân vườn Thủ Đức nào có nhiều góc check in") == ""


def test_canonicalize_merges_name_variants():
    """Khớp khoá bằng dấu BẰNG quá chặt: cùng quán, hai cách viết -> hai ứng viên."""
    from actions.place_research import canonicalize_keys
    alias = canonicalize_keys({
        "a.vn": ["Last Minute Cafe", "Ngôi Nhà Gỗ"],
        "b.vn": ["Last Minute Premium Cafe", "Yana Coffee Tea"],
    })
    assert alias.get("last minute premium") == "last minute"


def test_canonicalize_refuses_single_token_keys():
    """GIỚI HẠN CÓ CHỦ ĐÍCH: khoá một token không được nuốt khoá dài.

    "Cafe Thanh" (khoá `thanh`) mà gộp mọi quán có chữ "thanh" thì bằng chứng dính vào sai
    chỗ — hỏng im lặng, đúng thứ phải tránh nhất.
    """
    from actions.place_research import canonicalize_keys
    alias = canonicalize_keys({"a.vn": ["Cafe Thanh"], "b.vn": ["Thanh Xuân Coffee House"]})
    assert alias == {}


def test_research_merges_variants_end_to_end():
    pages = {"https://a.vn/x": _listicle(["Last Minute Cafe", "Quán Alpha Một",
                                          "Quán Alpha Hai"]),
             "https://b.vn/x": _listicle(["Last Minute Premium Cafe", "Quán Beta Một",
                                          "Quán Beta Hai"])}
    out = research("quán cà phê", places=None, http_get=_fake_web(pages))
    assert out["outcome"] == "OK"
    assert out["results"][0]["sources"] == 2, "hai biến thể của cùng một quán phải gộp"


# --------------------------- trích dẫn nguyên văn (L3-5a) --------------------------- #

def _listicle_prose(entries):
    """entries = [(tên, đoạn văn)] -> HTML bài dạng danh sách.

    Chèn thêm văn ĐỆM để trang qua được cổng nội dung (>= 4000 ký tự). Câu đệm cố ý
    không nhắc thuộc tính nào để nó không bao giờ được chọn làm trích dẫn.
    """
    pad = "Chỗ để xe rộng, nhân viên phục vụ nhanh và thân thiện. " * 25
    parts = []
    for i, (name, prose) in enumerate(entries, 1):
        parts.append("<h2>%d. %s</h2><p>%s %s</p>" % (i, name, prose, pad))
    return "<article>" + "".join(parts) + "</article>"


def test_quote_terms_drops_category_and_area_words():
    """Từ tả THỂ LOẠI có mặt ở mọi đoạn nên vô dụng để tìm bằng chứng; khu vực cũng vậy."""
    from actions.place_research import quote_terms
    assert quote_terms("quán cà phê view hồ", "Hà Nội") == {"view", "hồ"}
    assert quote_terms("quán cà phê", "Hà Nội") == set(), "chỉ có thể loại -> không từ nào"


def test_research_attaches_quote_with_source_attribution():
    filler = "Quán mở cửa từ 7h sáng tới 22h, có chỗ để xe máy ngay trước cửa."
    pages = {
        "https://a.vn/x": _listicle_prose([
            ("Tropical Forest", filler),
            ("KAT Coffee", filler), ("Riêng A", filler)]),
        "https://b.vn/x": _listicle_prose([
            ("Tropical Forest", "Sân vườn rợp bóng cây xanh, ngồi ngoài trời rất mát."),
            ("KAT Coffee", filler), ("Riêng B", filler)]),
    }
    out = research("quán cà phê nhiều cây xanh", places=None, http_get=_fake_web(pages))
    top = [r for r in out["results"] if "Tropical" in r["name"]][0]
    assert top["quote"] == "Sân vườn rợp bóng cây xanh, ngồi ngoài trời rất mát"
    assert top["quote_source"] == "b.vn", "phải ghi nguồn để người dùng lần lại được"


def test_research_has_no_quote_when_prose_never_mentions_the_need():
    """Không nguồn nào nói về thuộc tính -> im lặng, KHÔNG trích một câu bất kỳ.

    Một câu có thật, trích đúng nguyên văn, mà không chứng minh điều đang nói vẫn là
    bằng chứng giả — và là kiểu hỏng nguy hiểm nhất vì nó trông hợp lệ (spec §12).
    """
    filler = "Quán mở cửa từ 7h sáng tới 22h, giá đồ uống từ 35.000 đồng."
    pages = {
        "https://a.vn/x": _listicle_prose([("Quán Một", filler), ("Quán Hai", filler),
                                           ("Riêng A", filler)]),
        "https://b.vn/x": _listicle_prose([("Quán Một", filler), ("Quán Hai", filler),
                                           ("Riêng B", filler)]),
    }
    out = research("quán cà phê nhiều cây xanh", places=None, http_get=_fake_web(pages))
    assert out["results"], "vẫn phải có ứng viên"
    assert all("quote" not in r for r in out["results"])


def test_quote_terms_drops_quantifiers():
    """HỒI QUY (chạy thật 2026-08-23).

    "quán cà phê nhiều cây xanh" trích cho Tằm Art Café câu *"Quán trưng bày nhiều tác
    phẩm nghệ thuật..."* — khớp đúng chữ "nhiều" và nói về TRANH. Lượng từ chỉ đo danh
    từ đứng sau nó, tự nó không phải thuộc tính nào cả.
    """
    from actions.place_research import quote_terms
    assert quote_terms("quán cà phê nhiều cây xanh", "Hà Nội") == {"cây", "xanh"}
    assert quote_terms("quán rất yên tĩnh") == {"yên", "tĩnh"}


# --------------------------- số thứ tự lọt vào tên (chạy thật 2026-08-23) --------------------------- #
#
# Cùng một chuỗi, hai nghĩa trái ngược: trong "2 Tiệm cà phê Túi Mơ To" số 2 là thứ tự mục,
# trong "36 Coffee" số 36 là tên quán. Luật cũ đòi phải có DẤU CÂU sau số nên an toàn với
# "36 Coffee" nhưng để lọt cả loạt bài đánh số trần. Luật mới đọc DÃY SỐ CỦA CẢ TRANG, nên
# hai chiều dưới đây phải cùng đúng — sửa một chiều mà hỏng chiều kia là chưa sửa được gì.

_DALAT_20 = [
    "Horizon Coffee", "Tiệm cà phê Túi Mơ To", "An Cafe", "Bonjour Cafe", "Cousine Chateau",
    "The Married Beans", "Panorama Coffee", "Mountain View", "La Viet Coffee", "Cây Cam Ngọt",
    "Nhum Coffee", "Still Café", "Dalat Nights", "Cheo Veo Hills", "Cong Caphe",
    "Tiem Ca Phe Nho", "Windmills Coffee", "Le Chalet Dalat", "Duong Coffee",
    "Cà Phê Đợi Một Người",
]


def _bare_numbered(names, start=1):
    """[tên] -> HTML các heading đánh số KHÔNG có dấu câu: `<h2>2 Tiệm cà phê Túi Mơ To</h2>`."""
    return "".join("<h2>%d %s</h2>" % (i, n) for i, n in enumerate(names, start=start))


def test_harvest_drops_ordinal_written_without_punctuation():
    """HỒI QUY: truy vấn "quán cà phê view đẹp Đà Lạt" chạy thật 2026-08-23.

    Bài đánh số bằng khoảng trắng chứ không bằng dấu chấm, và luật cũ
    (`^\s*\d{1,2}\s*[.)\-–:]\s*`) ĐÒI dấu câu nên không khớp. Bốn tên ra ngoài kèm số
    thứ tự: "2 Tiệm cà phê Túi Mơ To", "10 Cây Cam Ngọt", "12 Still Café",
    "20 Cà Phê Đợi Một Người".
    """
    got = harvest_names(_bare_numbered(_DALAT_20))
    for want in ("Tiệm cà phê Túi Mơ To", "Cây Cam Ngọt", "Still Café", "Cà Phê Đợi Một Người"):
        assert want in got, "còn dính số thứ tự: %r" % [g for g in got if want in g]


def test_harvest_keeps_number_that_is_part_of_the_name():
    """CHIỀU NGƯỢC LẠI: có tên quán THẬT bắt đầu bằng số. Bỏ số vô điều kiện là hỏng chúng.

    Trang này không đánh số mục nào cả, nên không con số nào được coi là thứ tự.
    """
    body = "<h2>36 Coffee</h2><h2>1900 Cafe</h2><h2>6 Degrees</h2><h2>The Coffee House</h2>"
    assert harvest_names(body) == ["36 Coffee", "1900 Cafe", "6 Degrees", "The Coffee House"]


def test_harvest_keeps_number_that_does_not_fit_the_sequence():
    """Trang CÓ đánh số, nhưng "6 Degrees" đứng ở mục thứ 4 — 6 không phải thứ tự của nó.

    Đây là ca khó nhất và là lý do phải xét dãy chứ không xét từng heading: cùng một trang
    vừa có số thứ tự thật (1, 2, 3) vừa có số nằm trong tên.
    """
    body = _bare_numbered(["An Cafe", "Bonjour Cafe", "La Viet Coffee"]) + "<h2>6 Degrees</h2>"
    assert harvest_names(body) == ["An Cafe", "Bonjour Cafe", "La Viet Coffee", "6 Degrees"]


def test_real_name_number_does_not_break_the_ordinal_run():
    """"36 Coffee" chen giữa bài đánh số: nó bị BỎ QUA khi dò dãy, không làm đứt dãy.

    Dò dãy mà đòi các số phải liền nhau tuyệt đối thì một tên như thế đủ để tắt luật, và
    mọi mục còn lại của trang lại lọt số ra ngoài.
    """
    body = ("<h2>1 An Cafe</h2><h2>36 Coffee</h2><h2>2 Bonjour Cafe</h2>"
            "<h2>3 La Viet Coffee</h2><h2>4 Nhum Coffee</h2>")
    assert harvest_names(body) == ["An Cafe", "36 Coffee", "Bonjour Cafe", "La Viet Coffee",
                                   "Nhum Coffee"]


def test_ordinal_run_must_be_long_enough():
    """Dãy quá ngắn -> không kết luận là bài đánh số, giữ nguyên số.

    Hai heading "1 Phút Coffee" / "2 Chàng Trai" có thể là thứ tự, cũng có thể là tên thật.
    Không đủ bằng chứng thì chọn phía KHÔNG bỏ: giữ nhầm số chỉ làm tên thừa một chữ, còn
    bỏ nhầm thì tên thật hỏng hẳn.
    """
    assert harvest_names("<h2>1 Phút Coffee</h2><h2>2 Chàng Trai</h2>") \
        == ["1 Phút Coffee", "2 Chàng Trai"]
    assert len(page_ordinals(["1 a", "2 b"])) == 0
    assert sorted(page_ordinals(["1 a", "2 b", "3 c"])) == [1, 2, 3]


def test_punctuated_numbering_still_stripped_without_a_run():
    """Dấu câu vẫn là bằng chứng đủ mạnh tự nó — không cần dãy, giữ nguyên hành vi cũ."""
    assert clean_candidate("1. Tropical Forest") == "Tropical Forest"
    assert clean_candidate("12) KAT Coffee ") == "KAT Coffee"
    assert harvest_names("<h2>7. Nhum Coffee</h2>") == ["Nhum Coffee"]


def test_harvest_records_strips_bare_ordinals_too():
    """Đường SẢN XUẤT là `harvest_records`, không phải `harvest_names` — phải sửa cả hai."""
    from research.harvest import harvest_records
    recs = harvest_records(_bare_numbered(_DALAT_20))
    names = [r["name"] for r in recs]
    assert "Tiệm cà phê Túi Mơ To" in names and "Cà Phê Đợi Một Người" in names
    assert [r["name"] for r in harvest_records("<h2>36 Coffee</h2><h2>1900 Cafe</h2>")] \
        == ["36 Coffee", "1900 Cafe"]


# --------------------------- nói thật khi các bài ít trùng nhau (§22.1) --------------------------- #

def test_sparse_note_fires_when_answer_looks_thin_but_many_were_seen():
    """Thủ Đức: 34 ứng viên, 1 đạt ngưỡng. Im lặng ở đây bị hiểu thành "khu vực này chỉ
    có ngần đó quán", trong khi sự thật là các bài viết không đồng thuận với nhau."""
    from actions.place_research import say_sparse_note
    note = say_sparse_note({"candidates": 34, "passed": 1})
    assert "ít trùng nhau" in note and "34" in note


def test_sparse_note_silent_on_a_healthy_answer():
    """Hà Nội: ~40 ứng viên, 8 đạt ngưỡng — tỉ lệ thấp y hệt, nhưng 8 chỗ thì không mỏng."""
    from actions.place_research import say_sparse_note
    assert say_sparse_note({"candidates": 40, "passed": 8}) == ""


def test_sparse_note_silent_when_few_candidates_were_seen():
    """Thấy ít mà đạt ít thì đúng là tìm được ít, không phải các nguồn bất đồng."""
    from actions.place_research import say_sparse_note
    assert say_sparse_note({"candidates": 6, "passed": 1}) == ""
    assert say_sparse_note({}) == ""


def test_say_research_carries_the_sparse_note():
    from actions.place_research import say_research
    out = {"outcome": "OK",
           "results": [{"name": "KAT Coffee", "sources": 2, "resolved": False}],
           "diagnostics": {"consensus": {"candidates": 34, "passed": 1,
                                         "independent_sources": 5}}}
    assert "ít trùng nhau" in say_research(out, "quán cà phê")
