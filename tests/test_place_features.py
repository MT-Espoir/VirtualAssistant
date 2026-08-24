"""Bóc đặc trưng địa điểm.

Mọi chuỗi trong file này là dữ liệu THẬT bóc từ Google Maps, không phải
ví dụ tự nghĩ. Đó là điều kiện để test có ý nghĩa: parser phải chịu được dạng thật.
"""

import datetime as dt

import pytest

from actions.place_features import (extract_features, minutes_until_close,
                                    parse_category_address, parse_opening, parse_price,
                                    parse_quote, parse_rating)

OLEOLEO = ["Oleoleo Coffee & Cats", "4,8(646) · 1-100.000 ₫",
           "Quán cà phê ·  · 5t2 Ngõ 62 Nguyễn Chí Thanh",
           "Đang mở cửa · Đóng cửa vào 22:30",
           '"Đồ uống ngon', 'Quán yên tĩnh hợp học bài."']
HARU = ["HARU COFFEE & TEA 24/7", "4,7(166)", "Quán cà phê · Centre Point Toà B, Đ. D1",
        "Mở cả ngày"]
BALAN = ["Balan Coffee Roastery", "4,6(82)", "Quán cà phê ·  · S6.01 Vinhome Grand Park",
         "Sắp đóng cửa · 22:00 · Mở cửa lúc 6:30 Thứ 7"]
BOLD = ["Bold Espresso Bar", "4,8(117)", "Quán cà phê ·  · 62 D9",
        "Đã đóng cửa · Mở cửa lúc 7:00 Thứ 7"]


# --------------------------- rating ---------------------------

def test_rating_va_so_luot_tu_dong_text():
    assert parse_rating(OLEOLEO) == (4.8, 646)
    assert parse_rating(HARU) == (4.7, 166)


def test_rating_lui_ve_aria_khi_dong_text_khong_co():
    assert parse_rating(["Quán X"], ["4,5 sao 1.970 bài đánh giá"]) == (4.5, 1970)


def test_khong_co_rating_thi_tra_None_chu_khong_doan():
    assert parse_rating(["Quán X", "Quán cà phê · 12 Nguyễn Trãi"]) == (None, None)


def test_dau_phan_cach_nghin_khong_lam_sai_so_luot():
    assert parse_rating(["4,5(1.970)"]) == (4.5, 1970)


# --------------------------- giá ---------------------------

def test_dai_gia_hai_dang_viet():
    assert parse_price(OLEOLEO)["max"] == 100000
    assert parse_price(["Quán X"], ["1 ₫ – 100.000 ₫"])["max"] == 100000


def test_thieu_dai_gia_la_None_khong_phai_0():
    """Thiếu dữ liệu KHÁC với rẻ — trả 0 sẽ làm ranking hiểu sai."""
    assert parse_price(HARU) is None


# --------------------------- loại + địa chỉ ---------------------------

def test_loai_va_dia_chi():
    assert parse_category_address(OLEOLEO) == ("Quán cà phê", "5t2 Ngõ 62 Nguyễn Chí Thanh")


def test_khong_nham_dong_rating_hay_dong_gio_thanh_dia_chi():
    """Cả hai dòng đó đều chứa dấu '·' nên rất dễ bị bóc nhầm."""
    cat, addr = parse_category_address(["4,8(646) · 1-100.000 ₫",
                                        "Đang mở cửa · Đóng cửa vào 22:30",
                                        "Quán cà phê · 62 D9"])
    assert cat == "Quán cà phê" and addr == "62 D9"


# --------------------------- giờ mở cửa ---------------------------

@pytest.mark.parametrize("lines,state", [
    (HARU, "open_24h"),
    (OLEOLEO, "open"),
    (BALAN, "closing_soon"),
    (BOLD, "closed"),
    (["Quán cà phê · 62 D9"], "unknown"),
])
def test_trang_thai_mo_cua(lines, state):
    """'Sắp đóng cửa' và 'Đã đóng cửa' đều chứa 'đóng cửa'; 'Đang mở cửa' chứa 'mở cửa'
    — thứ tự kiểm cụm sai là phân loại nhầm hết."""
    assert parse_opening(lines)["state"] == state


def test_gio_dong_va_gio_mo_duoc_tach_dung():
    o = parse_opening(BALAN)
    assert o["closes_at"] == (22, 0) and o["opens_at"] == (6, 30)
    assert parse_opening(OLEOLEO)["closes_at"] == (22, 30)
    assert parse_opening(BOLD)["opens_at"] == (7, 0) and parse_opening(BOLD)["closes_at"] is None


def test_con_bao_nhieu_phut_nua_dong_cua():
    now = dt.datetime(2026, 8, 21, 21, 40)
    assert minutes_until_close(parse_opening(OLEOLEO), now) == 50
    assert minutes_until_close(parse_opening(BALAN), now) == 20
    assert minutes_until_close(parse_opening(HARU), now) is None      # mở cả ngày


def test_qua_nua_dem_khong_ra_so_am():
    now = dt.datetime(2026, 8, 21, 23, 50)
    o = parse_opening(["Đang mở cửa · Đóng cửa vào 00:30"])
    assert minutes_until_close(o, now) == 40


# --------------------------- trích đoạn review ---------------------------

def test_trich_doan_review_la_bang_chung_duy_nhat_cho_thuoc_tinh_mem():
    q = parse_quote(OLEOLEO)
    assert q and "yên tĩnh" in q


def test_khong_co_trich_doan_thi_None():
    """Không có bằng chứng -> không được nhắc tới thuộc tính mềm."""
    assert parse_quote(HARU) is None


# --------------------------- gộp ---------------------------

def test_extract_features_gop_du_truong():
    f = extract_features({"name": "Oleoleo", "url": "u", "lat": 1.0, "lng": 2.0,
                          "lines": OLEOLEO, "aria": ["4,8 sao 646 bài đánh giá",
                                                     "Lối vào cho xe lăn"]})
    assert f["rating"] == 4.8 and f["reviews"] == 646
    assert f["category"] == "Quán cà phê"
    assert f["price"]["max"] == 100000
    assert f["opening"]["state"] == "open"
    assert f["wheelchair"] is True
    assert "lines" not in f and "aria" not in f       # dữ liệu thô không rò ra ngoài


def test_the_rong_khong_lam_vo_va_khong_bia_gi():
    f = extract_features({"name": "X", "url": "u", "lat": 1.0, "lng": 2.0})
    assert f["rating"] is None and f["price"] is None and f["quote"] is None
    assert f["opening"]["state"] == "unknown"
    assert f["wheelchair"] is False


def test_khong_co_loi_khoi_xe_lan_thi_khong_tinh_la_co():
    f = extract_features({"name": "X", "url": "u", "lat": 1.0, "lng": 2.0,
                          "lines": ["X"], "aria": ["Không có lối vào cho xe lăn"]})
    assert f["wheelchair"] is False
