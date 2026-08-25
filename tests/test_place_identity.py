"""
Test danh tính địa điểm (`actions/place_identity.py`).

Hai tầng phải tách được: nhận định thẩm mỹ đúng ở cấp THƯƠNG HIỆU, khoảng cách chỉ đúng
ở cấp CHI NHÁNH. Có test khoá cả GIỚI HẠN đã biết của `brand_key` — nó không tách được
dạng "<Thương hiệu> <Tên đường>" viết liền, và điều đó phải hiển hiện trong test chứ
không nấp trong docstring.
"""

from features.places.identity import (brand_key, canonical_id, coord_cell, merge_duplicates,
                                    normalize_name, same_place)


# --------------------------- ô lưới toạ độ --------------------------- #

def test_coord_cell_same_for_points_within_20m():
    a = coord_cell(21.03130, 105.79640)
    b = coord_cell(21.03135, 105.79642)          # lệch ~6 m
    assert a == b


def test_coord_cell_differs_for_far_points():
    assert coord_cell(21.0313, 105.7964) != coord_cell(21.0400, 105.7964)


def test_coord_cell_scales_longitude_by_latitude():
    """Kinh độ co theo cos(lat) -> ở vĩ độ 21 (VN), MỘT ĐỘ kinh ngắn hơn ở xích đạo.

    Nên bước lưới tính theo ĐỘ phải RỘNG hơn, và cùng một khoảng cách theo độ sẽ rơi vào
    ít ô hơn. Dùng chung một bước cho cả lat/lng sẽ cho ô dẹt ~10m theo chiều đông-tây.
    """
    cells_at_equator = coord_cell(0.0, 0.001)[1]
    cells_at_vietnam = coord_cell(21.0, 0.001)[1]
    assert cells_at_vietnam < cells_at_equator


def test_coord_cell_none_when_missing():
    assert coord_cell(None, 105.0) is None and coord_cell(21.0, None) is None


# --------------------------- chuẩn hoá tên --------------------------- #

def test_normalize_name_drops_category_words():
    """'Quán cà phê Trill' và 'Trill Bistro' phải cùng khoá phần đặc trưng."""
    assert "trill" in normalize_name("Quán cà phê Trill")
    assert "trill" in normalize_name("Trill Bistro")


def test_normalize_name_strips_accents():
    assert normalize_name("Ưu Đàm Chay") == normalize_name("Uu Dam Chay")


def test_normalize_name_empty_for_all_generic():
    assert normalize_name("quán cafe") == ""


# --------------------------- khoá thương hiệu --------------------------- #

def test_brand_key_cuts_at_separator():
    assert brand_key("Cộng Cà Phê – Triệu Việt Vương") == brand_key("Cộng Cà Phê")


def test_brand_key_cuts_explicit_branch_marker():
    assert brand_key("Highlands Coffee chi nhánh Nguyễn Huệ") == brand_key("Highlands Coffee")


def test_brand_key_known_limitation_bare_street_suffix():
    """GIỚI HẠN ĐÃ BIẾT, khoá lại để không ai tưởng nó đã được giải quyết.

    'Cộng Cà Phê Triệu Việt Vương' không có dấu hiệu tách nào -> hàm trả về CẢ CỤM, nên
    khác khoá với 'Cộng Cà Phê'. Danh tính chuỗi đáng tin phải đến từ trường chain/brand
    của nhà cung cấp, không phải từ việc bổ chuỗi.
    """
    assert brand_key("Cộng Cà Phê Triệu Việt Vương") != brand_key("Cộng Cà Phê")


def test_brand_key_empty_safe():
    assert brand_key("") == "" and brand_key(None) == ""


# --------------------------- canonical id --------------------------- #

def test_canonical_id_same_for_nearby_same_name():
    a = canonical_id("Tropical Forest", 21.03130, 105.79640)
    b = canonical_id("Tropical Forest", 21.03134, 105.79641)
    assert a == b and a.startswith("geo:")


def test_canonical_id_differs_per_branch():
    """Hai chi nhánh cùng tên, khác chỗ -> khoá chi nhánh KHÁC nhau."""
    a = canonical_id("Cộng Cà Phê", 21.0313, 105.7964)
    b = canonical_id("Cộng Cà Phê", 21.0450, 105.8100)
    assert a != b


def test_canonical_id_marks_missing_coords():
    """Thiếu toạ độ -> khoá kém tin cậy hơn, phải gọi tên ra để tầng trên biết."""
    assert canonical_id("Tropical Forest").startswith("name:")


# --------------------------- so cùng một chỗ --------------------------- #

def test_same_place_needs_both_name_and_distance():
    a = {"name": "Tropical Forest", "lat": 21.0313, "lng": 105.7964}
    near_other = {"name": "KAT Coffee", "lat": 21.0313, "lng": 105.7964}
    far_same = {"name": "Tropical Forest", "lat": 21.0450, "lng": 105.8100}
    assert not same_place(a, near_other), "cùng toạ độ mà khác tên -> không phải một chỗ"
    assert not same_place(a, far_same), "cùng tên mà xa nhau -> hai chi nhánh"


def test_same_place_tolerates_name_variants():
    """Tên rút gọn ở cùng một chỗ vẫn phải nhận ra — blog và Maps hiếm khi viết y hệt."""
    a = {"name": "Tropical Forest Coffee", "lat": 21.0313, "lng": 105.7964}
    b = {"name": "Tropical Forest", "lat": 21.03133, "lng": 105.79641}
    assert same_place(a, b)


def test_same_place_known_limitation_category_word_lowers_score():
    """GIỚI HẠN: 'Coffee' không nằm trong GENERIC_TOKENS (chỉ có 'cafe'/'ca'/'phe'), nên
    nó bị tính là token ĐẶC TRƯNG. Tên càng ngắn thì thiếu nó càng hạ điểm mạnh.

    Khoá lại để thấy được: nếu sau này thêm 'coffee' vào GENERIC_TOKENS thì test này đổi,
    và đó là thay đổi CÓ Ý THỨC chứ không phải trôi đi lúc nào không hay.
    """
    a = {"name": "AN's Garden Coffee", "lat": 21.0313, "lng": 105.7964}
    b = {"name": "AN Garden", "lat": 21.03133, "lng": 105.79641}
    assert not same_place(a, b)


def test_same_place_without_coords_requires_exact_name():
    """Không có toạ độ thì chỉ nhận khi tên khớp HOÀN TOÀN — thiếu dữ liệu không được
    biến thành phỏng đoán."""
    assert same_place({"name": "Tropical Forest"}, {"name": "Tropical Forest"})
    assert not same_place({"name": "Tropical Forest"}, {"name": "Tropical Garden"})


def test_same_place_none_safe():
    assert not same_place(None, {"name": "X"}) and not same_place({}, None)


# --------------------------- gộp trùng --------------------------- #

def test_merge_duplicates_collects_aliases():
    rows = [
        {"name": "Cà phê Cộng", "lat": 21.0313, "lng": 105.7964, "source": "blog"},
        {"name": "Cộng Cà Phê", "lat": 21.03132, "lng": 105.79641, "source": "maps"},
        {"name": "KAT Coffee", "lat": 21.0400, "lng": 105.8000, "source": "blog"},
    ]
    out = merge_duplicates(rows)
    assert len(out) == 2
    assert out[0]["source"] == "blog", "giữ bản ghi ĐẦU TIÊN của nhóm"
    assert "Cộng Cà Phê" in out[0]["aliases"]


def test_merge_duplicates_adds_keys():
    out = merge_duplicates([{"name": "Tropical Forest", "lat": 21.0313, "lng": 105.7964}])
    assert out[0]["canonical_id"].startswith("geo:") and out[0]["brand_key"]


def test_merge_duplicates_does_not_mutate_input():
    rows = [{"name": "X", "lat": 21.0, "lng": 105.0}]
    merge_duplicates(rows)
    assert "canonical_id" not in rows[0]


def test_merge_duplicates_empty_safe():
    assert merge_duplicates([]) == [] and merge_duplicates(None) == []
