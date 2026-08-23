"""
Test panel kết quả địa điểm (`ui/place_panel.py`) — L3-4.

Chỉ test phần THUẦN (`card_text`, `panel_title`). Phần vẽ Tk không test tự động được;
nó cố ý mỏng và không chứa luật nào.

Ràng buộc được khoá ở đây là quy tắc chống bịa của spec §12: chỉ hiện trường CÓ dữ liệu
thật, số nguồn hiện dưới dạng CON SỐ chứ không phải tính từ, và panel không được khẳng
định quán có tính chất được hỏi.
"""

from ui.place_panel import card_text, panel_title


# --------------------------- chỉ hiện thứ CÓ dữ liệu --------------------------- #

def test_card_shows_only_known_fields():
    data = card_text({"name": "Tropical Forest", "sources": 3})
    assert data["title"] == "Tropical Forest"
    assert data["meta"] == [], "không có khoảng cách/điểm/giờ thì phải im lặng"


def test_card_omits_distance_when_unresolved():
    """Chưa tra được toạ độ -> KHÔNG được bịa khoảng cách."""
    data = card_text({"name": "KAT Coffee", "sources": 2, "resolved": False})
    assert not any("cách" in m for m in data["meta"])
    assert "(chưa tra được trên bản đồ)" in data["evidence"]


def test_card_shows_distance_when_known():
    data = card_text({"name": "X", "sources": 2, "distance_km": 1.2})
    assert any("1.2 km" in m or "1,2" in m for m in data["meta"])


def test_card_rating_always_carries_review_count():
    """4,8 với 3 lượt khác hẳn 4,8 với 646 lượt (F1.5 §7) — không được giấu số lượt."""
    data = card_text({"name": "X", "rating": 4.8, "reviews": 646})
    assert any("646" in m for m in data["meta"])


def test_card_opening_states():
    for state, expect in (("open_24h", "mở cả ngày"), ("closing_soon", "sắp đóng cửa"),
                          ("closed", "đang đóng cửa"), ("open", "đang mở cửa")):
        data = card_text({"name": "X", "opening": {"state": state}})
        assert expect in data["meta"]


def test_card_unknown_opening_is_silent():
    data = card_text({"name": "X", "opening": {"state": "unknown"}})
    assert data["meta"] == []


# --------------------------- quy tắc chống bịa --------------------------- #

def test_card_states_source_count_as_a_number():
    """CẤM tính từ ('rất nổi tiếng'). Người đọc phải tự cân được sức nặng bằng chứng."""
    data = card_text({"name": "X", "sources": 3}, need="quán nhiều cây xanh")
    line = data["evidence"][0]
    assert line.startswith("3 nguồn nhắc tới")
    assert "nổi tiếng" not in line and "rất" not in line


def test_card_never_asserts_the_quality():
    """Panel KHÔNG được nói quán có tính chất đó — nó chưa kiểm chứng gì (I-L3-3)."""
    data = card_text({"name": "Tropical Forest", "sources": 3},
                     need="quán cà phê nhiều cây xanh")
    blob = " ".join([data["title"]] + data["meta"] + data["evidence"]).lower()
    assert "nhắc tới" in blob
    assert "quán này nhiều cây" not in blob


def test_card_quote_is_shown_verbatim_in_quotes():
    data = card_text({"name": "X", "sources": 2, "quote": "sân vườn rợp bóng cây"})
    assert any("sân vườn rợp bóng cây" in e and e.startswith("“") for e in data["evidence"])


def test_card_no_sources_no_evidence_line():
    data = card_text({"name": "X"})
    assert not any("nguồn" in e for e in data["evidence"])


def test_card_missing_name_is_explicit():
    assert card_text({})["title"] == "(không rõ tên)"


def test_card_photos_default_empty():
    """Nguồn ảnh chưa có (L3-5 còn chờ §14) — khoá `photos` phải tồn tại và rỗng."""
    assert card_text({"name": "X"})["photos"] == []


def test_card_photos_passed_through():
    data = card_text({"name": "X", "photos": ["a.jpg", "b.jpg"]})
    assert data["photos"] == ["a.jpg", "b.jpg"]


# --------------------------- tiêu đề panel --------------------------- #

def test_panel_title_counts_without_judging():
    title = panel_title("quán nhiều cây xanh", [{"name": "A"}, {"name": "B"}])
    assert "2 chỗ" in title and "quán nhiều cây xanh" in title
    assert "tốt nhất" not in title and "đẹp" not in title


def test_panel_title_when_empty():
    assert "Không có" in panel_title("quán cổ", [])


def test_card_prefers_downloaded_bytes_over_url():
    """Panel không được gọi mạng: có bytes tải sẵn thì dùng bytes."""
    data = card_text({"name": "X", "photos": ["https://a.vn/1.jpg"],
                      "photo_data": [b"\x89PNG"]})
    assert data["photos"] == [b"\x89PNG"]


def test_card_falls_back_to_url_when_no_bytes():
    data = card_text({"name": "X", "photos": ["https://a.vn/1.jpg"]})
    assert data["photos"] == ["https://a.vn/1.jpg"]


def test_card_shows_quote_with_its_source():
    """Trích dẫn vô danh thì người dùng không lần lại được — mà thẻ tồn tại để họ tự kiểm."""
    data = card_text({"name": "X", "sources": 2, "quote": "sân vườn rợp bóng cây",
                      "quote_source": "toplist.vn"})
    assert any(line.startswith("“") and line.endswith("— toplist.vn")
               for line in data["evidence"])


def test_card_quote_without_source_has_no_dangling_dash():
    data = card_text({"name": "X", "sources": 2, "quote": "sân vườn rợp bóng cây"})
    assert "“sân vườn rợp bóng cây”" in data["evidence"]
