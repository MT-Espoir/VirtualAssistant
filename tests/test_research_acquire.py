"""
Test tầng thu thập nguồn cho Lane 3 (`research/acquire.py`).

Dữ liệu mẫu lấy từ SỐ ĐO THẬT ngày 2026-08-22 (`docs/research_lane_spec.md` §2):
foody.vn là khung AngularJS trả HTTP 200, thuychauecopark.vn là bài "mẹo chụp ảnh"
không phải danh sách quán. Hai ca đó chính là lý do có hai cổng lọc.

Không có test nào ở đây chạm mạng: `http_get` được tiêm vào.
"""

from research.acquire import (article_body, content_gate, decode_ddg_links, discover,
                              domain_of, fetch_many, one_per_domain, page_type_gate,
                              strip_chrome, acquire, build_search_url)


# --------------------------- giải mã link DuckDuckGo --------------------------- #

def test_decode_ddg_links_unwraps_redirect():
    """DDG bọc link ngoài trong `/l/?uddg=`. Quên giải mã -> tưởng trang không có link."""
    html = ('<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Ftoplist.vn%2Fabc.htm">A</a>'
            '<a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fkla.vn%2Fxyz">B</a>')
    assert decode_ddg_links(html) == ["https://toplist.vn/abc.htm", "https://kla.vn/xyz"]


def test_decode_ddg_links_dedupes_and_ignores_junk():
    html = ("uddg=https%3A%2F%2Fa.vn%2F1 uddg=https%3A%2F%2Fa.vn%2F1 "
            "uddg=javascript%3Aalert(1)")
    assert decode_ddg_links(html) == ["https://a.vn/1"]


def test_decode_ddg_links_empty_safe():
    assert decode_ddg_links("") == [] and decode_ddg_links(None) == []


# --------------------------- một domain một suất --------------------------- #

def test_one_per_domain_keeps_first_and_excludes():
    urls = ["https://mytour.vn/a", "https://mytour.vn/b", "https://www.facebook.com/x",
            "https://kla.vn/c"]
    assert one_per_domain(urls, exclude=("facebook.com",)) == [
        "https://mytour.vn/a", "https://kla.vn/c"]


def test_domain_of_lowercases():
    assert domain_of("https://WWW.Toplist.VN/abc") == "www.toplist.vn"


# --------------------------- gỡ chrome + tìm thân bài --------------------------- #

def test_strip_chrome_removes_nav_and_footer():
    html = "<nav>menu</nav><article>NOI DUNG</article><footer>Đăng nhập</footer>"
    out = strip_chrome(html)
    assert "NOI DUNG" in out and "menu" not in out and "Đăng nhập" not in out


def test_strip_chrome_cuts_related_widget_after_real_content():
    """Widget 'bài liên quan' làm lọt rác — đo được ở §2.6 (mia.vn, quananngonhanoi)."""
    html = ('<article><p>' + ("Quán cà phê nhiều cây xanh. " * 200) + '</p></article>'
            '<div class="related-posts"><h3>Khám Phá 5 Địa Chỉ Lẩu Băng Chuyền</h3></div>')
    out = strip_chrome(html)
    assert "Quán cà phê nhiều cây xanh." in out and "Lẩu Băng Chuyền" not in out


def test_strip_chrome_does_not_cut_widget_at_top_of_page():
    """HỒI QUY: nút share/tags nằm ở ĐẦU bài, cắt ở đó thì giết sạch trang.

    Chạy thật 2026-08-22 lộ lỗi này: `toplist.vn` và `quananngonhanoi.com` bị loại nhầm
    'too_short' dù thật ra có 14,8kb và 12,6kb nội dung.
    """
    html = ('<div class="share-buttons">Chia sẻ</div>'
            '<article><p>' + ("Nội dung thật của bài viết. " * 200) + '</p></article>')
    out = strip_chrome(html)
    assert "Nội dung thật của bài viết." in out
    assert len(out) > 4000, "cắt ở widget đầu trang -> mất trắng nội dung"


def test_article_body_prefers_article_tag():
    body, how = article_body("<div>ngoài</div><article>" + "x" * 2500 + "</article>")
    assert how == "article" and "ngoài" not in body


def test_article_body_falls_back_to_whole_page():
    """toplist.vn không khớp mẫu nào mà vẫn cho 9 tên sạch -> lùi về cả trang, không bỏ."""
    body, how = article_body("<div>" + "y" * 3000 + "</div>")
    assert how == "whole_page" and body


# --------------------------- cổng 1: có nội dung thật không --------------------------- #

def test_content_gate_rejects_angular_template():
    """Ca foody.vn: HTTP 200, có 'text', nhưng là khung `{{...}}` + `ng-*`."""
    html = "<div ng-repeat='x in y'>{{item.DisplayName}}</div>" * 12
    ok, diag = content_gate(html)
    assert not ok and diag["reason"] == "template_markers" and diag["markers"] >= 5


def test_content_gate_rejects_too_short():
    ok, diag = content_gate("<p>ngắn quá</p>")
    assert not ok and diag["reason"] == "too_short"


def test_content_gate_accepts_real_article():
    html = "<article><p>" + ("Quán cà phê nhiều cây xanh. " * 220) + "</p></article>"
    body, _ = article_body(html)
    ok, diag = content_gate(html, body)
    assert ok and diag["text_chars"] >= 4000 and diag["markers"] == 0


# --------------------------- cổng 2: có phải danh sách không --------------------------- #

def test_page_type_gate_accepts_enumerated_list():
    body = "<h2>1. Tropical Forest</h2><h2>2. KAT Coffee</h2><h2>3. The Ylang</h2>"
    ok, diag = page_type_gate(body)
    assert ok and diag["enumerated"] == 3


def test_page_type_gate_rejects_howto_article():
    """Ca thuychauecopark.vn: qua cổng nội dung (31,7kb) nhưng là bài mẹo chụp ảnh."""
    body = ("<h2>Mẹo chụp ảnh cafe view đẹp</h2>"
            "<h2>Cài đặt máy ảnh Pro/Manual</h2>"
            "<h2>Tư duy góc chụp</h2>")
    ok, diag = page_type_gate(body)
    assert not ok and diag["reason"] == "not_a_list"


# --------------------------- tải song song --------------------------- #

class _Resp:
    def __init__(self, text):
        self.text = text


def test_fetch_many_keeps_input_order():
    urls = ["https://a.vn/1", "https://b.vn/2", "https://c.vn/3"]
    rows = fetch_many(urls, http_get=lambda u: _Resp("noi dung " + u))
    assert [r["url"] for r in rows] == urls
    assert all(r["html"].startswith("noi dung") for r in rows)


def test_fetch_many_survives_one_bad_source():
    """Một nguồn hỏng không được làm sập cả lượt thu thập."""
    def get(url):
        if "bad" in url:
            raise RuntimeError("timeout")
        return _Resp("ok")
    rows = fetch_many(["https://good.vn/1", "https://bad.vn/2"], http_get=get)
    by = {r["domain"]: r for r in rows}
    assert by["good.vn"]["html"] == "ok"
    assert by["bad.vn"]["error"] and by["bad.vn"]["html"] == ""


# --------------------------- xuyên tầng --------------------------- #

def test_build_search_url_requires_query():
    import pytest
    with pytest.raises(ValueError):
        build_search_url("   ")


def test_discover_returns_empty_on_network_error():
    """Lỗi mạng -> danh sách rỗng, KHÔNG ném lỗi lên tầng trên."""
    def boom(url):
        raise RuntimeError("mất mạng")
    assert discover("quán cà phê", http_get=boom) == []


def _page(n_items=4, filler=260):
    items = "".join("<h2>%d. Quán số %d</h2>" % (i, i) for i in range(1, n_items + 1))
    return "<article>" + items + "<p>" + ("Không gian nhiều cây xanh. " * filler) + "</p></article>"


def test_acquire_filters_and_reports_why():
    """Chẩn đoán phải nói RÕ trang nào bị loại vì lý do gì — cần cho mã SOURCES_UNUSABLE."""
    pages = {
        "https://good.vn/x": _page(),                                   # qua cả hai cổng
        "https://spa.vn/x": "<div ng-repeat='a'>{{b}}</div>" * 12,      # cổng 1 loại
        "https://howto.vn/x": "<article><h2>Mẹo chụp ảnh</h2><p>"
                              + ("chữ " * 1500) + "</p></article>",     # cổng 2 loại
    }
    urls = list(pages)

    def get(url):
        if "duckduckgo" in url:
            import urllib.parse
            return _Resp("".join("uddg=%s " % urllib.parse.quote(u, safe="") for u in urls))
        return _Resp(pages[url])

    kept, diag = acquire("quán cà phê nhiều cây xanh", http_get=get)
    assert [k["domain"] for k in kept] == ["good.vn"]
    assert diag["found"] == 3 and diag["kept"] == 1
    assert diag["rejected"]["spa.vn"] == "template_markers"
    assert diag["rejected"]["howto.vn"] == "not_a_list"


def test_page_type_gate_accepts_unnumbered_headings():
    """HỒI QUY: listicle dùng heading KHÔNG đánh số vẫn phải qua.

    Bản đầu chỉ nhận mục đánh số -> loại nhầm `hanoitoplist.com`, `giatheficoco.com`
    khi chạy thật 2026-08-22, trong khi vẫn cho lọt trang cần chặn. Giá trị ròng âm.
    """
    body = "".join("<h2>Quán số %d</h2>" % i for i in range(1, 6))
    ok, diag = page_type_gate(body)
    assert ok and diag["enumerated"] == 0 and diag["headings"] == 5


def test_fetch_many_enforces_wall_clock():
    """HỒI QUY: trần thời gian phải CẮT THẬT, không chờ nguồn treo tự timeout.

    Chạy thật 2026-08-22: `mytour.vn` giữ cả lượt 15s dù đặt wall_seconds=8, vì code cũ
    chỉ kiểm giờ SAU khi mỗi future xong.
    """
    import time

    def slow_get(url):
        if "slow" in url:
            time.sleep(10)
        return _Resp("nhanh")

    t0 = time.time()
    rows = fetch_many(["https://fast.vn/1", "https://slow.vn/2"],
                      http_get=slow_get, wall_seconds=1.0)
    elapsed = time.time() - t0
    assert elapsed < 5, "trần thời gian không cắt được nguồn treo (%.1fs)" % elapsed
    by = {r["domain"]: r for r in rows}
    assert by["fast.vn"]["html"] == "nhanh"
    assert by["slow.vn"]["error"] == "quá hạn thu thập"


# --------------------------- bóc ảnh + địa chỉ theo từng mục --------------------------- #

def test_harvest_records_splits_evidence_per_section():
    from research.harvest import harvest_records
    body = ('<h2>1. Quán Một</h2><img src="https://x.vn/a.jpg"><p>Địa chỉ: 8 Chân Cầm, Hà Nội</p>'
            '<h2>2. Quán Hai</h2><img src="https://x.vn/b.jpg"><p>không có địa chỉ</p>')
    recs = harvest_records(body)
    assert [r["name"] for r in recs] == ["Quán Một", "Quán Hai"]
    assert recs[0]["address"] == "8 Chân Cầm, Hà Nội" and recs[1]["address"] is None
    assert recs[0]["photos"] == ["https://x.vn/a.jpg"], "không được lấy ảnh của mục kế bên"


def test_harvest_records_drops_ui_images():
    from research.harvest import harvest_records
    body = ('<h2>1. Quán Một</h2><img src="https://x.vn/logo.png">'
            '<img src="https://x.vn/icon-star.svg"><img src="https://x.vn/that.jpg">')
    assert harvest_records(body)[0]["photos"] == ["https://x.vn/that.jpg"]


def test_harvest_records_resolves_relative_urls():
    from research.harvest import harvest_records
    body = '<h2>1. Quán Một</h2><img src="/uploads/a.jpg">'
    recs = harvest_records(body, base_url="https://x.vn/bai-viet.htm")
    assert recs[0]["photos"] == ["https://x.vn/uploads/a.jpg"]


def test_harvest_records_uses_lazy_src():
    """Nhiều trang VN đặt ảnh thật ở data-src, `src` chỉ là ảnh giữ chỗ."""
    from research.harvest import harvest_records
    body = '<h2>1. Quán Một</h2><img data-src="https://x.vn/that.jpg" alt="x">'
    assert harvest_records(body)[0]["photos"] == ["https://x.vn/that.jpg"]


def test_harvest_records_drops_theme_assets():
    """HỒI QUY: ảnh giữ chỗ lazy-load của theme lọt qua khi chỉ lọc theo TÊN.

    Chạy thật 2026-08-22: `.../themes/flatsome/assets/img/lazy.png` được nhận là ảnh quán.
    Ảnh nội dung luôn nằm ở /uploads/ hoặc CDN, không bao giờ trong /themes/ hay /plugins/.
    """
    from research.harvest import harvest_records
    body = ('<h2>1. Quán Một</h2>'
            '<img src="https://x.vn/wp-content/themes/flatsome/assets/img/lazy.png">'
            '<img src="https://x.vn/wp-content/plugins/slider/blank.gif">'
            '<img src="https://x.vn/wp-content/uploads/2025/quan-that.jpg">')
    assert harvest_records(body)[0]["photos"] == [
        "https://x.vn/wp-content/uploads/2025/quan-that.jpg"]


# --------------------------- tải ảnh --------------------------- #

def test_fetch_images_returns_bytes_and_skips_failures():
    from research.acquire import fetch_images

    class _Img:
        def __init__(self, data): self.content = data

    def get(url):
        if "bad" in url:
            raise RuntimeError("404")
        return _Img(b"\x89PNG-fake")

    out = fetch_images(["https://x.vn/ok.jpg", "https://x.vn/bad.jpg"], http_get=get)
    assert out == {"https://x.vn/ok.jpg": b"\x89PNG-fake"}, "ảnh hỏng phải VẮNG MẶT"


def test_fetch_images_empty_input_safe():
    from research.acquire import fetch_images
    assert fetch_images([], http_get=lambda u: None) == {}


# --------------------------- discovery hỏng: phải nói ĐÚNG chuyện gì xảy ra --------------------------- #
#
# CHẠY THẬT 2026-08-22: DDG trả HTTP 200 nhưng KHÔNG có link nào (bị giới hạn tần suất sau
# nhiều truy vấn liên tiếp). Bản cũ trả [] lặng lẽ, không log gì, và tầng trên nói với người
# dùng "các trang lấy được đều không đọc được nội dung" — trong khi chưa tải trang nào.

def test_decode_bing_links_skips_microsoft_domains():
    from research.acquire import decode_bing_links
    html = ('<a href="https://www.bing.com/images">x</a>'
            '<a href="https://go.microsoft.com/fwlink">y</a>'
            '<a href="https://toplist.vn/abc.htm">z</a>')
    assert decode_bing_links(html) == ["https://toplist.vn/abc.htm"]


def test_discover_falls_back_to_bing_when_ddg_empty():
    """Một nguồn discovery duy nhất là điểm hỏng đơn lẻ của cả Lane 3."""
    import urllib.parse

    def get(url):
        if "duckduckgo" in url:
            return _Resp("<html>không có link nào</html>")       # bị chặn, vẫn HTTP 200
        return _Resp('<a href="https://toplist.vn/abc.htm">k</a>')

    diag = {}
    urls = discover("quán cà phê cổ", http_get=get, diag=diag)
    assert urls == ["https://toplist.vn/abc.htm"]
    assert diag["engine"] == "bing" and diag["engine_fallback"] is True


def test_discover_records_reason_when_all_engines_fail():
    diag = {}
    urls = discover("x", http_get=lambda u: _Resp("<html>rỗng</html>"), diag=diag)
    assert urls == []
    assert set(diag["discover_failed"]) == {"ddg", "bing"}
    assert "bị chặn" in diag["discover_failed"]["ddg"]


def test_acquire_marks_discovery_failure_distinctly():
    """Phải phân biệt 'không tìm kiếm được' với 'trang không đọc nổi'."""
    kept, diag = acquire("x", http_get=lambda u: _Resp("<html></html>"))
    assert kept == [] and diag["failed_at"] == "discovery" and diag["found"] == 0


def test_discover_falls_back_to_browser_when_http_blocked():
    """Đo 2026-08-22: MỌI máy tìm kiếm HTTP đều chặn sau một buổi gọi liên tục.

    DDG trả 202 (trang anomaly), Mojeek 403, Brave 429. Trình duyệt thật không bị chặn.
    """
    def blocked(url):
        class R:
            status_code = 202
            text = "<html>anomaly</html>"
        return R()

    diag = {}
    urls = discover("quán cà phê retro", http_get=blocked, diag=diag,
                    browser_search=lambda q, n: ["https://toplist.vn/a.htm",
                                                 "https://toplist.vn/b.htm",
                                                 "https://kla.vn/c.htm"])
    assert urls == ["https://toplist.vn/a.htm", "https://kla.vn/c.htm"], "vẫn một domain một suất"
    assert diag["engine"] == "browser"


def test_discover_reports_http_block_status():
    """Mã 202/403/429 phải được gọi tên là BỊ CHẶN, không phải 'không có kết quả'."""
    def blocked(url):
        class R:
            status_code = 429
            text = ""
        return R()
    diag = {}
    discover("x", http_get=blocked, diag=diag)
    assert "HTTP 429" in diag["discover_failed"]["ddg"]


def test_discover_survives_broken_browser_fallback():
    def blocked(url):
        class R:
            status_code = 403
            text = ""
        return R()

    def boom(q, n):
        raise RuntimeError("Chrome chưa kết nối")

    diag = {}
    assert discover("x", http_get=blocked, diag=diag, browser_search=boom) == []
    assert "browser" in diag["discover_failed"]


# --------------------------- mở rộng truy vấn --------------------------- #

def test_acquire_merges_pools_from_several_queries():
    """Nhiều biến thể -> một rổ URL chung, vẫn MỘT domain một suất, rồi tải MỘT lần."""
    pages = {"https://a.vn/x": _page(), "https://b.vn/x": _page(), "https://c.vn/x": _page()}

    def get(url):
        import urllib.parse
        if "duckduckgo" in url:
            # câu gốc ra a+b; biến thể "top" ra b+c -> hợp lại phải là 3 domain
            wanted = (["https://a.vn/x", "https://b.vn/x"] if "top" not in url
                      else ["https://b.vn/x", "https://c.vn/x"])
            return _Resp("".join("uddg=%s " % urllib.parse.quote(u, safe="") for u in wanted))
        return _Resp(pages[url])

    kept, diag = acquire("quán cà phê", http_get=get, extra_queries=["top quán cà phê"])
    assert sorted(k["domain"] for k in kept) == ["a.vn", "b.vn", "c.vn"]


def test_acquire_records_new_domains_per_query():
    """Biến thể không mang thêm domain nào = tiêu một lượt tìm kiếm vô ích. Phải đo được."""
    pages = {"https://a.vn/x": _page(), "https://b.vn/x": _page()}

    def get(url):
        import urllib.parse
        return (_Resp("".join("uddg=%s " % urllib.parse.quote(u, safe="") for u in pages))
                if "duckduckgo" in url else _Resp(pages[url]))

    _, diag = acquire("quán cà phê", http_get=get, extra_queries=["top quán cà phê"])
    per = diag["queries"]
    assert per["quán cà phê"]["new_domains"] == 2
    assert per["top quán cà phê"]["new_domains"] == 0, "biến thể trùng hoàn toàn -> 0 mới"


def test_acquire_ignores_duplicate_extra_query():
    pages = {"https://a.vn/x": _page()}

    def get(url):
        import urllib.parse
        return (_Resp("uddg=" + urllib.parse.quote("https://a.vn/x", safe=""))
                if "duckduckgo" in url else _Resp(pages[url]))

    _, diag = acquire("quán cà phê", http_get=get, extra_queries=["quán cà phê", ""])
    assert len(diag["queries"]) == 1


# --------------------------- trích dẫn nguyên văn (L3-5a) --------------------------- #

def test_pick_quote_takes_sentence_mentioning_the_attribute():
    from research.harvest import pick_quote
    text = ("Quán mở cửa từ 7h sáng tới 22h mỗi ngày, phục vụ cả cuối tuần. "
            "Cả sân vườn rợp bóng cây xanh nên ngồi ngoài trời rất mát. "
            "Giá đồ uống dao động từ 35.000 tới 60.000 đồng.")
    quote, hits = pick_quote(text, {"cây", "xanh", "mát"})
    assert quote == "Cả sân vườn rợp bóng cây xanh nên ngồi ngoài trời rất mát"
    assert hits == 3


def test_pick_quote_is_silent_when_nothing_mentions_the_attribute():
    """Không có câu nào nhắc thuộc tính -> None.

    Trích một câu bất kỳ cho đủ ô là bằng chứng GIẢ: nó trông như đang chứng minh điều
    gì đó trong khi không (spec §12).
    """
    from research.harvest import pick_quote
    text = "Quán mở cửa từ 7h sáng tới 22h. Giá đồ uống từ 35.000 tới 60.000 đồng."
    assert pick_quote(text, {"cây", "xanh"}) == (None, 0)
    assert pick_quote(text, set()) == (None, 0), "không có từ khoá -> không đoán"


def test_pick_quote_prefers_most_hits_then_earliest():
    from research.harvest import pick_quote
    text = ("Không gian ở đây khá xanh và thoáng đãng vào buổi sáng sớm. "
            "Khu sân sau trồng nhiều cây xanh, có cả hồ cá nhỏ rất mát mẻ.")
    quote, hits = pick_quote(text, {"cây", "xanh", "mát"})
    assert quote.startswith("Khu sân sau") and hits == 3


def test_pick_quote_clips_long_sentence_at_word_boundary():
    from research.harvest import pick_quote
    text = "Quán có rất nhiều cây xanh " + "và những góc ngồi dễ chịu " * 12 + "."
    quote, _ = pick_quote(text, {"cây", "xanh"})
    assert quote.endswith("…") and len(quote) <= 161
    assert "  " not in quote and not quote[:-1].endswith(" ")


def test_harvest_records_attaches_quote_per_section():
    from research.harvest import harvest_records
    body = ('<h2>1. Quán Một</h2><p>Sân vườn rợp bóng cây xanh, ngồi rất mát.</p>'
            '<h2>2. Quán Hai</h2><p>Quán nhỏ trong ngõ, hợp làm việc buổi tối.</p>')
    recs = harvest_records(body, quote_terms={"cây", "xanh"})
    assert recs[0]["quote"] == "Sân vườn rợp bóng cây xanh, ngồi rất mát"
    assert recs[1]["quote"] is None, "KHÔNG được mượn câu của mục kế bên"


def test_harvest_records_without_terms_has_no_quote():
    from research.harvest import harvest_records
    body = '<h2>1. Quán Một</h2><p>Sân vườn rợp bóng cây xanh, ngồi rất mát.</p>'
    assert harvest_records(body)[0]["quote"] is None


def test_pick_quote_does_not_glue_metadata_blocks_to_prose():
    """HỒI QUY (chạy thật 2026-08-23, noithattruongsa.com).

    Mỗi dòng thông tin là một `<p>` riêng và KHÔNG có dấu chấm cuối dòng. Bóc thẻ trước
    rồi mới ngắt câu thì cả khối giờ mở cửa + bảng giá dính vào câu văn kế tiếp, và trích
    dẫn hiện ra là *"Hà Nội ⏰ Giờ mở cửa: 08h00 – 23h00 💲 Giá tham khảo: 30.000... Nếu
    bạn muốn tìm một quán cafe nhiều cây xanh..."*.
    """
    from research.harvest import harvest_records
    body = ('<h2>5. The Ylang</h2>'
            '<p><span>📍 Địa chỉ: Số 2 Lê Thạch, Tràng Tiền, Hoàn Kiếm, Hà Nội</span></p>'
            '<p><span>⏰ Giờ mở cửa: 08h00 – 23h00</span></p>'
            '<p><span>💲 Giá tham khảo: 30.000 – 200.000đ/người</span></p>'
            '<p><span>Nếu bạn muốn tìm một quán cafe nhiều cây xanh ở Hà Nội thì '
            'đừng bỏ qua The Ylang.</span></p>')
    quote = harvest_records(body, quote_terms={"nhiều", "cây", "xanh"})[0]["quote"]
    assert quote.startswith("Nếu bạn muốn tìm")
    assert "Giờ mở cửa" not in quote and "Giá tham khảo" not in quote


def test_block_text_marks_boundaries_without_leaking_the_mark():
    from research.harvest import block_text, pick_quote
    text = block_text("<li>Không gian nhiều cây xanh</li><li>Chỗ để xe rộng rãi</li>")
    quote, _ = pick_quote(text, {"cây", "xanh"})
    assert quote == "Không gian nhiều cây xanh"
    assert "\x00" not in quote


def test_pick_quote_skips_related_article_links():
    """HỒI QUY (chạy thật 2026-08-23, giatheficoco.com).

    Theme chèn dòng "bài viết liên quan" ngay giữa thân bài. Nó khớp từ khoá nhưng nói
    về một chỗ hoàn toàn khác — trích nó ra là gán bằng chứng cho nhầm quán.
    """
    from research.harvest import pick_quote
    text = ("READ Hải Phòng Cải Tạo Sân Vận Động Máy Tơ Thành Công Viên Cây Xanh 2026. "
            "Khoảng sân nhỏ của quán trồng cây xanh và trải sỏi trắng.")
    quote, _ = pick_quote(text, {"cây", "xanh"})
    assert quote.startswith("Khoảng sân nhỏ")


def test_pick_quote_skips_headline_links_but_keeps_inline_ones():
    """HỒI QUY (chạy thật 2026-08-23, zalopay.vn).

    Widget "Tham khảo thêm" là `<li><a>tiêu đề bài khác</a></li>` nằm giữa thân bài. Nó
    khớp từ khoá nhưng nói về chỗ khác. Ngược lại đường dẫn NGẮN giữa câu văn là một phần
    của câu, bỏ nó đi thì mất luôn câu.
    """
    from research.harvest import harvest_records
    body = ('<h2>1. Quán Một</h2>'
            '<ul><li><a href="/x"><u>Thác Voi Đà Lạt: Vẻ đẹp, đường đi và kinh nghiệm'
            ' du lịch</u></a></li></ul>'
            '<p>Quán nằm ngay cạnh <a href="/y">Hồ Xuân Hương</a> với view rất đẹp.</p>')
    quote = harvest_records(body, quote_terms={"view", "đẹp"})[0]["quote"]
    assert quote == "Quán nằm ngay cạnh Hồ Xuân Hương với view rất đẹp"
