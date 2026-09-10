"""Test Persona: character card thích nghi provider, MoodState công thức, chấm cảm xúc."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.persona import (PersonaState, MoodState, score_user_valence,
                           score_fluster, parse_trait_nudges)


# --------------------------- PersonaState --------------------------- #

def test_render_slim_for_local_provider():
    p = PersonaState(provider="ollama", persist=False)
    card = p.render()
    assert "ấm áp" in card and "Văn phong" in card
    assert "Ví dụ" not in card                # local -> KHÔNG few-shot


def test_render_full_with_fewshot_for_strong_provider():
    p = PersonaState(provider="gemini", persist=False)
    card = p.render()
    assert "Ví dụ cách bạn trò chuyện" in card  # model mạnh -> có few-shot
    assert "Người dùng:" in card


def test_baselines_from_traits():
    p = PersonaState(provider="ollama", persist=False)
    assert 0.3 <= p.baseline_valence() <= 0.4     # warmth cao -> baseline tích cực
    assert 0.3 <= p.baseline_arousal() <= 0.75


def test_adjust_trait_is_bounded():
    p = PersonaState(provider="ollama", persist=False)
    for _ in range(20):
        p.adjust("humor", 0.15)
    assert p._trait("humor") == 1.0               # kẹp tối đa 1.0
    for _ in range(20):
        p.adjust("humor", -0.15)
    assert p._trait("humor") == 0.0               # kẹp tối thiểu 0.0


def test_reset_traits_restores_default_but_keeps_rapport():
    p = PersonaState(provider="ollama", persist=False)
    p.record_interaction(); p.record_interaction()
    fam = p.familiarity()
    p.adjust("formality", 0.15)
    p.reset_traits()
    assert p._trait("formality") == 0.25          # về baseline
    assert p.familiarity() == fam                 # GIỮ quan hệ


def test_record_interaction_grows_familiarity():
    p = PersonaState(provider="ollama", persist=False)
    start = p.familiarity()
    for _ in range(10):
        p.record_interaction()
    assert p.familiarity() > start
    assert p.data["rapport"]["interaction_count"] == 10


def test_mood_set_baseline_shifts_resting_point():
    m = MoodState(baseline_valence=0.2)
    m.set_baseline(0.6, 0.7)
    m.update()                                     # phai về baseline mới
    assert m.valence > 0.2


def test_persona_roundtrip():
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd); os.unlink(path)
    try:
        p = PersonaState(path=path, provider="gemini")
        p.data["identity"] = "một trợ lý điềm đạm"
        p._save()
        assert "điềm đạm" in PersonaState(path=path).render()
    finally:
        if os.path.exists(path):
            os.unlink(path)


# --------------------------- MoodState --------------------------- #

def test_mood_starts_at_baseline():
    m = MoodState(baseline_valence=0.2, baseline_arousal=0.5)
    assert m.valence == 0.2 and m.to_pose() == "neutral"


def test_positive_signal_makes_happy():
    m = MoodState(baseline_valence=0.2)
    m.update(user_valence=1.0, outcome=1.0)
    assert m.valence > 0.5 and m.to_pose() == "happy"


def test_negative_signal_makes_sad():
    m = MoodState(baseline_valence=0.2)
    m.update(user_valence=-1.0, outcome=-1.0)
    assert m.valence < -0.2 and m.to_pose() == "sad"


def test_mood_decays_back_toward_baseline():
    m = MoodState(baseline_valence=0.2, decay=0.5)
    m.update(user_valence=1.0, outcome=1.0)          # bốc lên
    high = m.valence
    m.update()                                        # không tín hiệu -> phai về baseline
    assert m.valence < high


def test_mood_label_vietnamese():
    m = MoodState(baseline_valence=0.6, baseline_arousal=0.7)
    lbl = m.label()
    assert "vui" in lbl and "," in lbl


# --------------------------- ngượng (fluster) --------------------------- #

def test_khen_thang_vao_tro_ly_gay_nguong():
    assert score_fluster("em dễ thương quá") > 0
    assert score_fluster("giỏi quá đi") > 0


def test_tha_thinh_va_to_tinh_nguong_hon_loi_khen():
    assert score_fluster("anh yêu em") > score_fluster("giỏi quá")


def test_khen_viec_khong_gay_nguong():
    # Đây là địa hạt của _POS_WORDS -> happy, không phải shy.
    for cau in ("cảm ơn nhé", "hay quá, tốt lắm", "ổn rồi", "tuyệt vời"):
        assert score_fluster(cau) == 0.0, cau


def test_khong_bat_nham_cau_sai_viec():
    # Bỏ dấu xong 'nhờ em' -> "nho em", 'yêu cầu' -> "yeu cau": hai cái bẫy đã né.
    for cau in ("nhờ em mở nhạc", "yêu cầu của tôi là gì", "nhớ em bé nhà tôi",
                "mở giúp tôi cái này", "hôm nay thế nào"):
        assert score_fluster(cau) == 0.0, cau


def test_nguong_de_len_vui():
    m = MoodState(baseline_valence=0.2)
    m.update(user_valence=1.0, outcome=1.0, fluster=score_fluster("em dễ thương quá"))
    assert m.valence >= 0.25          # vẫn đang vui...
    assert m.to_pose() == "shy"       # ...nhưng ngượng thắng vì nó cụ thể hơn


def test_vui_khong_bi_nguong_cuop_mat():
    m = MoodState(baseline_valence=0.2)
    m.update(user_valence=1.0, outcome=1.0, fluster=score_fluster("cảm ơn, tốt lắm"))
    assert m.to_pose() == "happy"


def test_nguong_phai_het_khi_het_tac_nhan():
    m = MoodState(baseline_valence=0.2, decay=0.5)
    m.update(fluster=score_fluster("em dễ thương quá"))
    assert m.to_pose() == "shy"
    m.update()                        # lượt sau không còn tác nhân
    assert m.to_pose() != "shy"
    assert m.fluster < 0.35


def test_nguong_hien_trong_label_de_loi_le_khop_mat():
    m = MoodState()
    m.update(fluster=1.0)
    assert "ngượng" in m.label()


# --------------------------- score_user_valence --------------------------- #

def test_score_positive():
    assert score_user_valence("cảm ơn nhé, hay quá") > 0


def test_score_negative():
    assert score_user_valence("chán quá, tệ thật") < 0


def test_score_neutral_and_no_false_positive():
    assert score_user_valence("mở youtube giúp tôi") == 0.0
    # 'không' KHÔNG được hiểu nhầm là tích cực (bug 'on' trong 'khong')
    assert score_user_valence("không") == 0.0


# --------------------------- parse_trait_nudges (Phase 2) --------------------------- #

def test_parse_nudges_signs():
    n = parse_trait_nudges("humor: +\nformality: -\nwarmth: 0\nenergy: +")
    assert n["humor"] > 0 and n["formality"] < 0 and n["energy"] > 0
    assert "warmth" not in n                       # '0' -> giữ nguyên


def test_parse_nudges_ignores_unknown_and_junk():
    n = parse_trait_nudges("badtrait: +\nlung tung\nhumor = +")
    assert n == {"humor": parse_trait_nudges("humor: +")["humor"]}


def test_parse_nudges_empty():
    assert parse_trait_nudges("") == {} and parse_trait_nudges(None) == {}
