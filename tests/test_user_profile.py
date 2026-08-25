"""Test bộ nhớ NGƯỜI DÙNG bền vững: cập nhật/tóm tắt thuần + roundtrip file + wire weather."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.profile import (UserProfile, apply_update, summarize,
                                          _relevant_facts)

from conftest import registry_with


# --------------------------- logic thuần --------------------------- #

def test_apply_update_sets_fields_and_reports_changes():
    data, changes = apply_update(None, name="Nam", location="Đà Nẵng")
    assert data["name"] == "Nam"
    assert data["preferences"]["default_location"] == "Đà Nẵng"
    assert any("Nam" in c for c in changes) and any("Đà Nẵng" in c for c in changes)


def test_apply_update_does_not_mutate_original():
    base = {"name": "Cũ", "preferences": {"default_location": "Hà Nội"}, "notes": []}
    data, _ = apply_update(base, name="Mới")
    assert base["name"] == "Cũ" and data["name"] == "Mới"      # bản gốc không đổi


def test_apply_update_empty_fields_no_change():
    _, changes = apply_update(None, name="   ", note="")
    assert changes == []


def test_apply_update_dedupes_notes():
    data, _ = apply_update(None, note="thích cà phê")
    data, _ = apply_update(data, note="thích cà phê")
    assert data["notes"] == ["thích cà phê"]


def test_summarize_empty_is_blank():
    assert summarize(None) == "" and summarize({}) == ""


def test_summarize_includes_known_fields():
    data, _ = apply_update(None, name="Nam", address_form="sếp", location="Huế")
    s = summarize(data)
    assert "Nam" in s and "sếp" in s and "Huế" in s


def test_summarize_includes_auto_facts():
    data = {"auto_facts": ["Thích cà phê"], "notes": [], "preferences": {}}
    assert "Thích cà phê" in summarize(data) and "Quan sát" in summarize(data)


# --------------------------- retrieval phẳng top-K --------------------------- #

def test_relevant_facts_picks_by_overlap():
    facts = ["thích cà phê sữa", "hay chạy bộ buổi sáng", "làm nghề lập trình"]
    picked = _relevant_facts(facts, "sáng nay chạy bộ không", 2)
    assert "hay chạy bộ buổi sáng" in picked


def test_summarize_retrieves_only_relevant_when_many():
    data = {"notes": [f"ghi chú {i}" for i in range(4)],
            "auto_facts": ["thích trà xanh", "chơi cầu lông", "xem phim kinh dị", "nghe nhạc vàng"],
            "preferences": {}}                       # tổng 8 > ngưỡng 6 -> truy hồi
    s = summarize(data, query="tối nay xem phim gì")
    assert "Liên quan lúc này" in s and "phim" in s
    # câu không liên quan -> không bơm dòng fact nào
    assert "Liên quan lúc này" not in summarize(data, query="tăng âm lượng")


def test_summarize_dumps_all_when_few_facts():
    data = {"notes": ["thích cà phê"], "auto_facts": [], "preferences": {}}
    assert "Cần nhớ" in summarize(data, query="bất kỳ câu gì")   # dưới ngưỡng -> bơm hết


# --------------------------- UserProfile (I/O) --------------------------- #

def test_profile_roundtrip_persists():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd); os.unlink(path)
    try:
        p1 = UserProfile(path)
        msg = p1.remember(name="Lan", location="Cần Thơ")
        assert "Đã nhớ" in msg
        p2 = UserProfile(path)                    # đọc lại từ file
        assert p2.data["name"] == "Lan"
        assert p2.get_default_location() == "Cần Thơ"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_add_auto_fact_dedupes_and_skips_explicit_notes():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd); os.unlink(path)
    try:
        p = UserProfile(path)
        p.remember(note="đã biết tường minh")
        p.add_auto_fact("thích trà")
        p.add_auto_fact("thích trà")             # trùng -> không thêm lại
        p.add_auto_fact("đã biết tường minh")    # trùng note tường minh -> bỏ
        p.add_auto_fact("   ")                    # rỗng -> bỏ
        assert p.data["auto_facts"] == ["thích trà"]
        p2 = UserProfile(path)                    # bền vững qua đọc lại
        assert p2.data["auto_facts"] == ["thích trà"]
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_profile_remember_nothing_asks_back():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd); os.unlink(path)
    try:
        p = UserProfile(path)
        msg = p.remember()
        assert "nhớ điều gì" in msg and not os.path.exists(path)   # không lưu file rỗng
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_profile_corrupt_file_degrades_safely():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ không phải json hợp lệ")
        p = UserProfile(path)                     # không được ném lỗi
        assert p.data.get("name") is None
    finally:
        os.unlink(path)


# --------------------------- wire vào registry --------------------------- #

def test_weather_uses_profile_default_location():
    actions = MagicMock(); actions.get_weather.return_value = "trời đẹp"

    class _P:
        def get_default_location(self): return "Đà Lạt"
        def summary(self): return ""
    reg = registry_with(actions=actions, profile=_P())
    reg.run("get_weather", {})                    # không truyền location -> lấy từ hồ sơ
    actions.get_weather.assert_called_once_with("Đà Lạt")


def test_remember_tool_registered_only_with_profile():
    reg_no = registry_with(actions=MagicMock())
    assert not reg_no.has("remember_about_user")

    class _P:
        def get_default_location(self): return None
        def summary(self): return ""
        def remember(self, **kw): return "Đã nhớ."
    reg_yes = registry_with(profile=_P())
    assert reg_yes.has("remember_about_user")
    assert reg_yes.run("remember_about_user", {"name": "Nam"}) == "Đã nhớ."
