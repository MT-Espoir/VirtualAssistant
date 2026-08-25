"""
Test claim cache của Lane 3 (`research/claim_cache.py` + nhánh cache trong `place_research`).

Ba chế độ được khoá ở đây, và cả ba đều sinh ra từ số đo chứ không từ mong muốn có cache:

  hit       hỏi lại trong cửa sổ tươi -> KHÔNG đụng mạng lần nào
  merge     tập kết quả tìm kiếm không ổn định giữa hai lượt -> hợp nhất nguồn,
            nên ứng viên từng chỉ có một nguồn có thể đạt ngưỡng ở lượt sau
  fallback  máy tìm kiếm chặn -> vẫn trả lời được, và PHẢI nói rõ dữ liệu cũ

Không test nào chạm mạng và không test nào chạm đĩa trừ chỗ cố ý kiểm tra ghi/đọc file.
Thời gian được tiêm qua `now=` nên không có test nào phải chờ.
"""

import json
import urllib.parse

from features.places.deep_research import cache_key, research, say_age, say_research
from research.claim_cache import CACHE_VERSION, ClaimCache, merge_sources


# --------------------------- đồ dùng chung --------------------------- #

class _Resp:
    def __init__(self, text):
        self.text = text


def _listicle(names):
    items = "".join("<h2>%d. %s</h2>" % (i, n) for i, n in enumerate(names, 1))
    return ("<article>" + items + "<p>" + ("Không gian nhiều cây xanh. " * 200)
            + "</p></article>")


class _Web:
    """`http_get` giả, có ĐẾM số lần gọi — cách duy nhất để chứng minh cache hit."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if "duckduckgo" in url:
            return _Resp("".join("uddg=%s " % urllib.parse.quote(u, safe="")
                                 for u in self.pages))
        return _Resp(self.pages[url])


class _Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance_hours(self, h):
        self.t += h * 3600.0


def _run(web, cache, need="quán cà phê nhiều cây xanh", area="Hà Nội"):
    return research(need, area=area, places=None, http_get=web,
                    browser_search=None, fetch_photos=False, cache=cache)


# --------------------------- khoá --------------------------- #

def test_cache_key_ignores_accents_and_case():
    """Gõ phím có dấu và đọc bằng giọng (bộ nhận dạng trả không dấu) phải trúng cùng ô nhớ."""
    assert cache_key("Quán Cà Phê Nhiều Cây Xanh", "Hà Nội") == \
           cache_key("quan ca phe nhieu cay xanh", "ha noi")


def test_cache_key_separates_areas():
    a = cache_key("quán cà phê yên tĩnh", "Hà Nội")
    b = cache_key("quán cà phê yên tĩnh", "Đà Lạt")
    assert a != b and a and b


def test_cache_key_empty_need_has_no_key():
    assert cache_key("   ", "Hà Nội") == ""


# --------------------------- kho --------------------------- #

def test_cache_roundtrip_and_freshness():
    clock = _Clock()
    cache = ClaimCache(fresh_hours=24, ttl_days=90, now=clock)
    cache.put("k", {"a.vn": {"url": "https://a.vn/x", "records": []}})

    got = cache.get("k")
    assert got["fresh"] and got["age_hours"] < 0.01

    clock.advance_hours(30)
    got = cache.get("k")
    assert got is not None and not got["fresh"], "quá cửa sổ tươi nhưng chưa hết hạn"
    assert 29 < got["age_hours"] < 31


def test_cache_drops_entry_past_ttl():
    clock = _Clock()
    cache = ClaimCache(fresh_hours=24, ttl_days=90, now=clock)
    cache.put("k", {"a.vn": {"records": []}})
    clock.advance_hours(91 * 24)
    assert cache.get("k") is None


def test_cache_persists_to_disk(tmp_path):
    path = str(tmp_path / "claims.json")
    clock = _Clock()
    ClaimCache(path, now=clock).put("k", {"a.vn": {"records": [{"name": "Quán X"}]}})

    again = ClaimCache(path, now=clock)
    assert again.get("k")["sources"]["a.vn"]["records"][0]["name"] == "Quán X"


def test_cache_ignores_file_from_another_version(tmp_path):
    """Đổi cách bóc bản ghi -> bản nhớ cũ lệch hình dạng. Bỏ hết còn hơn trộn lẫn."""
    path = str(tmp_path / "claims.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": CACHE_VERSION + 1,
                   "entries": {"k": {"saved_at": 1, "sources": {"a.vn": {}}}}}, f)
    assert ClaimCache(path, now=_Clock()).get("k") is None


def test_cache_survives_a_corrupt_file(tmp_path):
    """Hỏng ở tầng cache không được làm hỏng lượt tìm."""
    path = str(tmp_path / "claims.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{ không phải json")
    cache = ClaimCache(path, now=_Clock())
    assert cache.get("k") is None
    cache.put("k", {"a.vn": {"records": []}})     # vẫn ghi đè được
    assert cache.get("k") is not None


def test_merge_sources_prefers_the_fresh_copy():
    """Một domain có ở cả hai bên -> bản vừa đọc thắng; hợp nhất theo DOMAIN nên một
    domain vẫn chỉ có MỘT phiếu."""
    old = {"a.vn": {"url": "https://a.vn/cu", "records": [1]},
           "b.vn": {"url": "https://b.vn/x", "records": [2]}}
    new = {"a.vn": {"url": "https://a.vn/moi", "records": [3]}}
    merged = merge_sources(old, new)
    assert set(merged) == {"a.vn", "b.vn"}
    assert merged["a.vn"]["url"] == "https://a.vn/moi"


# --------------------------- ba chế độ, xuyên tầng --------------------------- #

def test_fresh_hit_touches_no_network():
    pages = {"https://a.vn/x": _listicle(["Tropical Forest", "Bagang Café", "Annamoi"]),
             "https://b.vn/x": _listicle(["Tropical Forest", "Philo Garden", "Soranchi"])}
    cache = ClaimCache(now=_Clock())

    first = _run(_Web(pages), cache)
    assert first["outcome"] == "OK"
    assert first["diagnostics"]["cache"]["mode"] == "miss"

    web2 = _Web(pages)
    second = _run(web2, cache)
    assert web2.calls == [], "cache hit mà vẫn gọi mạng thì cache vô nghĩa"
    assert second["diagnostics"]["cache"]["mode"] == "hit"
    assert [r["name"] for r in second["results"]] == [r["name"] for r in first["results"]]


def test_merge_lets_a_second_turn_reach_consensus():
    """Đây là lý do chính để có cache: tập kết quả tìm kiếm KHÔNG ổn định.

    Lượt 1 và lượt 2 mỗi lượt chỉ thấy Tropical Forest ở MỘT nguồn, nên tự mình cả hai
    đều `NO_CONSENSUS`. Hợp nhất lại thì đó là HAI trang khác nhau cùng nhắc tới nó —
    không có gì bị thổi phồng, chỉ là không còn bị quên.
    """
    clock = _Clock()
    cache = ClaimCache(fresh_hours=24, ttl_days=90, now=clock)

    round1 = {"https://a.vn/x": _listicle(["Tropical Forest", "Bagang Café", "Annamoi"]),
              "https://b.vn/x": _listicle(["Philo Garden", "Soranchi", "La Farine"])}
    first = _run(_Web(round1), cache)
    assert first["outcome"] == "NO_CONSENSUS"

    clock.advance_hours(30)          # quá cửa sổ tươi -> vẫn đi tìm, rồi hợp nhất
    round2 = {"https://c.vn/x": _listicle(["Tropical Forest", "Treeland Coffee", "Haawa"]),
              "https://d.vn/x": _listicle(["Cheo Veooo", "Still Café", "Cây Cam Ngọt"])}
    second = _run(_Web(round2), cache)

    assert second["diagnostics"]["cache"]["mode"] == "merge"
    assert second["diagnostics"]["cache"]["from_cache"] == 2, "phải giữ cả hai nguồn cũ"
    assert second["outcome"] == "OK"
    top = second["results"][0]
    assert top["name"] == "Tropical Forest" and top["sources"] == 2


def test_fallback_answers_from_memory_and_says_it_is_old():
    """Máy tìm kiếm chặn -> vẫn trả lời, nhưng KHÔNG được giả vờ vừa đọc web."""
    clock = _Clock()
    cache = ClaimCache(fresh_hours=24, ttl_days=90, now=clock)
    pages = {"https://a.vn/x": _listicle(["Tropical Forest", "Bagang Café", "Annamoi"]),
             "https://b.vn/x": _listicle(["Tropical Forest", "Philo Garden", "Soranchi"])}
    assert _run(_Web(pages), cache)["outcome"] == "OK"

    clock.advance_hours(72)
    blocked = _run(_Web({}), cache)          # không link nào -> discovery hỏng

    assert blocked["outcome"] == "OK" and blocked["results"]
    assert blocked["diagnostics"]["cache"]["mode"] == "fallback"
    said = say_research(blocked, "quán cà phê nhiều cây xanh")
    assert "không tìm mới được" in said and "3 ngày trước" in said


def test_no_cache_behaves_exactly_as_before():
    pages = {"https://a.vn/x": _listicle(["Tropical Forest", "Bagang Café", "Annamoi"]),
             "https://b.vn/x": _listicle(["Tropical Forest", "Philo Garden", "Soranchi"])}
    out = _run(_Web(pages), None)
    assert out["outcome"] == "OK"
    assert out["diagnostics"]["cache"] == {"mode": "off"}


def test_search_failure_without_memory_still_says_search_failed():
    """Không có gì để nhớ thì không được nhận vơ — vẫn phải báo là không tìm kiếm được."""
    out = _run(_Web({}), ClaimCache(now=_Clock()))
    assert out["outcome"] == "SEARCH_FAILED" and out["results"] == []


def test_fresh_hit_says_nothing_about_the_cache():
    """Trong cửa sổ tươi thì dữ liệu coi như của bây giờ — không cần rào đón."""
    pages = {"https://a.vn/x": _listicle(["Tropical Forest", "Bagang Café", "Annamoi"]),
             "https://b.vn/x": _listicle(["Tropical Forest", "Philo Garden", "Soranchi"])}
    cache = ClaimCache(now=_Clock())
    _run(_Web(pages), cache)
    said = say_research(_run(_Web(pages), cache), "quán cà phê nhiều cây xanh")
    assert "không tìm mới được" not in said


# --------------------------- cách nói tuổi --------------------------- #

def test_say_age_reads_naturally():
    assert say_age(0.5) == "vừa nãy"
    assert say_age(5) == "5 tiếng trước"
    assert say_age(72) == "3 ngày trước"
