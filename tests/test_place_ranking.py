"""Xếp hạng + giải thích có căn cứ."""

import datetime as dt

import pytest

from actions.place_explain import build_evidence, explain
from actions.place_ranking import (DEFAULT_WEIGHTS, RATING_PRIOR_MEAN, bayesian_quality,
                                   distance_score, evidence_score, intent_keys,
                                   open_score, rank, score_place)

NOW = dt.datetime(2026, 8, 21, 21, 40)


def _p(name, **kw):
    base = {"name": name, "distance_km": 0.5, "rating": None, "reviews": None,
            "opening": {"state": "unknown"}, "price": None, "quote": None}
    base.update(kw)
    return base


# --------------------------- trung bình Bayes ---------------------------

def test_it_luot_danh_gia_KHONG_duoc_de_nhieu_luot():
    """Điểm cao với rất ít lượt KHÔNG được đè điểm thấp hơn với rất nhiều lượt."""
    it = bayesian_quality(5.0, 3, RATING_PRIOR_MEAN)
    nhieu = bayesian_quality(4.7, 166, RATING_PRIOR_MEAN)
    assert nhieu > it


def test_prior_khong_duoc_lay_trung_binh_cua_tap_ung_vien():
    """Tập ứng viên là mẫu ĐÃ CHỌN LỌC (Maps chỉ trả quán điểm cao) — lấy trung bình của
    nó làm prior thì bằng chứng mỏng không bị phạt, và tiêu chí trên sẽ vỡ."""
    prior_lech = 4.833                     # trung bình một tập ứng viên thật
    assert bayesian_quality(5.0, 3, prior_lech) > bayesian_quality(4.7, 166, prior_lech)
    assert RATING_PRIOR_MEAN < prior_lech


def test_nhieu_luot_thi_diem_bam_sat_rating_that():
    assert abs(bayesian_quality(4.8, 600, RATING_PRIOR_MEAN) - 4.8) < 0.05


def test_khong_co_rating_thi_khong_cham_bua():
    assert bayesian_quality(None, 10, 4.2) is None


# --------------------------- thành phần điểm ---------------------------

def test_thieu_du_lieu_la_TRUNG_TINH_khong_phai_0():
    """Cho 0 sẽ đẩy mọi quán thiếu trường xuống đáy một cách vô lý."""
    score, known = distance_score(None, 5)
    assert score == 0.5 and known is False
    score2, known2 = open_score(_p("X"), NOW)
    assert score2 == 0.5 and known2 is False


def test_cang_gan_diem_cang_cao():
    assert distance_score(0.1, 5)[0] > distance_score(4.0, 5)[0]


def test_sap_dong_cua_bi_phat_nang():
    sap = open_score(_p("X", opening={"state": "closing_soon", "closes_at": (22, 0)}), NOW)[0]
    con_lau = open_score(_p("Y", opening={"state": "open", "closes_at": (23, 30)}), NOW)[0]
    assert sap < 0.3 < con_lau


def test_dang_dong_cua_thi_diem_0():
    assert open_score(_p("X", opening={"state": "closed"}), NOW)[0] == 0.0


def test_mo_ca_ngay_diem_toi_da():
    assert open_score(_p("X", opening={"state": "open_24h"}), NOW)[0] == 1.0


def test_bang_chung_review_chi_tinh_khi_nguoi_dung_neu_y_dinh():
    p = _p("X", quote="Quán yên tĩnh hợp học bài")
    assert evidence_score(p, [])[1] is False                 # không nêu ý định -> không xét
    score, known = evidence_score(p, ["hoc_lam_viec"])
    assert known and score == 1.0


def test_khong_co_trich_doan_thi_trung_tinh_khong_phai_kem():
    score, known = evidence_score(_p("X"), ["hoc_lam_viec"])
    assert score == 0.5 and known is False


def test_nhan_dien_y_dinh_tu_cau_nguoi_dung():
    assert "hoc_lam_viec" in intent_keys("quán cà phê học bài")
    assert "yen_tinh" in intent_keys("chỗ nào chill yên tĩnh")
    assert intent_keys("quán cà phê") == []


# --------------------------- xếp hạng tổng ---------------------------

def test_sap_dong_cua_bi_day_xuong_du_gan_nhat_va_diem_cao_nhat():
    ps = [_p("Sắp đóng", distance_km=0.1, rating=4.8, reviews=600,
             opening={"state": "closing_soon", "closes_at": (22, 0)}),
          _p("Mở cả ngày", distance_km=0.6, rating=4.7, reviews=166,
             opening={"state": "open_24h"})]
    assert rank(ps, {"radius_km": 5, "now": NOW})[0]["name"] == "Mở cả ngày"


def test_ranking_khong_sua_du_lieu_dau_vao():
    ps = [_p("A", rating=4.5, reviews=10)]
    rank(ps, {"radius_km": 5, "now": NOW})
    assert "ranking" not in ps[0]


def test_trong_so_doi_duoc_va_co_hieu_luc():
    ps = [_p("Gần nhưng kém", distance_km=0.1, rating=3.5, reviews=500,
             opening={"state": "open_24h"}),
          _p("Xa nhưng tốt", distance_km=3.0, rating=4.9, reviews=500,
             opening={"state": "open_24h"})]
    uu_tien_gan = {"distance": 0.9, "quality": 0.1, "open": 0.0, "evidence": 0.0}
    uu_tien_tot = {"distance": 0.1, "quality": 0.9, "open": 0.0, "evidence": 0.0}
    assert rank(ps, {"radius_km": 5, "now": NOW, "weights": uu_tien_gan})[0]["name"] == "Gần nhưng kém"
    assert rank(ps, {"radius_km": 5, "now": NOW, "weights": uu_tien_tot})[0]["name"] == "Xa nhưng tốt"


def test_moi_thanh_phan_deu_co_trong_so_mac_dinh():
    comp = score_place(_p("X"), {"radius_km": 5, "now": NOW})["components"]
    assert set(comp) == set(DEFAULT_WEIGHTS)


# ============ GIẢI THÍCH CÓ CĂN CỨ — bất biến chống bịa ============

_KHANG_DINH_CAM = ("quán này yên tĩnh", "quán yên tĩnh", "không đông", "quán này vắng",
                   "chắc chắn", "rất hợp")


def test_khong_co_du_lieu_thi_KHONG_co_nhan_dinh_nao():
    """Không được 'làm tròn' thành 'chưa rõ giá' hay bịa lý do cho đủ câu."""
    items = build_evidence(_p("Trống", distance_km=None), {})
    assert items == []
    câu = explain(_p("Trống", distance_km=None), {})
    assert "chưa có thêm thông tin" in câu.lower()


def test_thuoc_tinh_mem_chi_xuat_hien_khi_co_trich_doan_review():
    khong_quote = build_evidence(_p("X", quote=None), {"intent_keys": ["yen_tinh"]})
    assert not any("review" in i["claim"] for i in khong_quote)

    co_quote = build_evidence(_p("Y", quote="Không gian yên tĩnh, dễ chịu"),
                              {"intent_keys": ["yen_tinh"]})
    assert any("review có nhắc" in i["claim"] for i in co_quote)


def test_thuoc_tinh_mem_phai_phat_ngon_dang_SUY_DOAN():
    """Cấm 'quán này yên tĩnh' — không kiểm chứng được, chỉ có một câu review."""
    câu = explain(_p("Y", quote="Không gian yên tĩnh, dễ chịu để ngồi lâu"),
                  {"intent_keys": ["yen_tinh"]}).lower()
    assert "review có nhắc" in câu
    for cụm in _KHANG_DINH_CAM:
        assert cụm not in câu


def test_bang_chung_mem_phai_kem_TRICH_DAN_NGUYEN_VAN():
    items = build_evidence(_p("Y", quote="Quán yên tĩnh hợp học bài"),
                           {"intent_keys": ["hoc_lam_viec"]})
    soft = [i for i in items if "review" in i["claim"]][0]
    assert "Quán yên tĩnh hợp học bài" in soft["evidence"]


def test_nhan_dinh_theo_Y_DINH_khong_bi_cat_khi_rut_gon():
    """Nó trả lời đúng câu hỏi — quan trọng hơn khoảng cách hay điểm số."""
    p = _p("X", distance_km=0.1, rating=4.8, reviews=646, price={"raw": "1-100.000 ₫"},
           opening={"state": "open_24h"}, quote="Quán yên tĩnh hợp học bài")
    câu = explain(p, {"intent_keys": ["hoc_lam_viec"], "nearest_km": 0.1}, max_plus=2)
    assert "review có nhắc" in câu


def test_do_dong_chi_noi_khi_nguoi_dung_HOI_va_phai_ghi_ro_la_proxy():
    p = _p("X", rating=4.8, reviews=646)
    khong_hoi = explain(p, {})
    assert "đông" not in khong_hoi.lower()

    co_hoi = explain(p, {"asked_about_crowd": True})
    assert "có thể đông" in co_hoi                    # suy đoán, không khẳng định
    assert "lượt đánh giá" in co_hoi                  # nói rõ dựa trên cái gì


def test_luon_kem_SO_LUOT_khi_noi_ve_diem():
    """4,8 với 3 lượt và 4,8 với 646 lượt không cùng độ tin cậy — phải cho người nghe biết."""
    items = build_evidence(_p("X", rating=4.8, reviews=646), {})
    rating_claim = [i for i in items if "đánh giá tốt" in i["claim"]][0]
    assert "646" in rating_claim["evidence"]


def test_sap_dong_cua_la_LUU_Y_chu_khong_phai_diem_cong():
    items = build_evidence(_p("X", opening={"state": "closing_soon", "closes_at": (22, 0)}), {})
    closing = [i for i in items if "đóng cửa" in i["claim"]][0]
    assert closing["kind"] == "caveat"
    assert "Lưu ý" in explain(_p("X", distance_km=0.2,
                                 opening={"state": "closing_soon", "closes_at": (22, 0)}), {})


def test_gan_nhat_chi_noi_khi_dung_la_gan_nhat():
    ctx = {"nearest_km": 0.1}
    gan = build_evidence(_p("A", distance_km=0.1), ctx)[0]
    xa = build_evidence(_p("B", distance_km=0.9), ctx)[0]
    assert gan["claim"] == "gần nhất trong nhóm" and xa["claim"] == "ở gần"


def test_khoang_cach_rat_gan_khong_doc_thanh_0_met():
    from utils.units import say_distance
    assert say_distance(0.04) == "ngay gần đây"
    assert say_distance(0.35) == "cách 350 mét"
