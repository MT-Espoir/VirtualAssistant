"""Test bộ nhớ NGẮN HẠN (ShortTermMemory) + trích sự thật khi củng cố sang dài hạn."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.short_term import ShortTermMemory
from memory.consolidation import parse_extracted_facts


# --------------------------- ShortTermMemory --------------------------- #

def test_add_keeps_recent_and_returns_evicted():
    stm = ShortTermMemory(max_turns=2)          # cap = 4 message
    assert stm.add("u1", "a1") == []            # 2 msg, chưa vượt
    assert stm.add("u2", "a2") == []            # 4 msg
    evicted = stm.add("u3", "a3")               # 6 -> đẩy 2 cũ nhất
    assert [m.text for m in evicted] == ["u1", "a1"]
    assert [m.text for m in stm.messages()] == ["u2", "a2", "u3", "a3"]


def test_messages_is_copy():
    stm = ShortTermMemory(max_turns=5)
    stm.add("u", "a")
    got = stm.messages()
    got.clear()
    assert len(stm.messages()) == 2             # sửa bản sao không ảnh hưởng gốc


def test_clear_empties():
    stm = ShortTermMemory(max_turns=5)
    stm.add("u", "a")
    stm.clear()
    assert stm.messages() == []


def test_zero_max_turns_keeps_nothing():
    stm = ShortTermMemory(max_turns=0)
    evicted = stm.add("u", "a")
    assert stm.messages() == [] and len(evicted) == 2


def test_session_only_by_default_no_file(tmp_path=None):
    stm = ShortTermMemory(max_turns=3)          # path=None
    stm.add("u", "a")
    assert stm.path is None                     # không lưu ra đâu cả


def test_persist_roundtrip_when_path_given():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd); os.unlink(path)
    try:
        s1 = ShortTermMemory(max_turns=5, path=path)
        s1.add("xin chào", "chào bạn")
        s2 = ShortTermMemory(max_turns=5, path=path)
        assert [m.text for m in s2.messages()] == ["xin chào", "chào bạn"]
    finally:
        if os.path.exists(path):
            os.unlink(path)


# --------------------------- parse_extracted_facts --------------------------- #

def test_parse_none_returns_empty():
    assert parse_extracted_facts("NONE") == []
    assert parse_extracted_facts("") == []
    assert parse_extracted_facts(None) == []


def test_parse_strips_bullets_and_numbers():
    text = "- Thích cà phê sữa\n2. Làm việc ban đêm\n* Ở Đà Nẵng"
    assert [f["text"] for f in parse_extracted_facts(text)] == [
        "Thích cà phê sữa", "Làm việc ban đêm", "Ở Đà Nẵng"]


def test_parse_caps_count_and_length():
    text = "\n".join(f"sự thật {i}" for i in range(10))
    facts = parse_extracted_facts(text, max_facts=3)
    assert len(facts) == 3
    long = "x" * 500
    assert len(parse_extracted_facts(long, max_len=50)[0]["text"]) == 50


# --------------------- phân loại bền vững vs sự kiện có thời hạn --------------------- #

def test_parse_marks_durable_by_default():
    """Không có tiền tố -> BỀN VỮNG (chiều an toàn: coi nhầm thành sự kiện sẽ mất trí nhớ)."""
    f = parse_extracted_facts("Thích cà phê sữa")[0]
    assert f["kind"] == "durable" and f["when"] is None


def test_parse_reads_durable_prefix():
    f = parse_extracted_facts("[BEN] Thích cà phê sữa")[0]
    assert f == {"text": "Thích cà phê sữa", "kind": "durable", "when": None}


def test_parse_reads_event_with_time():
    f = parse_extracted_facts("[SUKIEN 2026-08-08T14:00] Phỏng vấn với anh Nam")[0]
    assert f["kind"] == "event" and f["when"] == "2026-08-08T14:00"
    assert f["text"] == "Phỏng vấn với anh Nam"


def test_parse_reads_event_without_time():
    f = parse_extracted_facts("[SUKIEN] Đi khám răng")[0]
    assert f["kind"] == "event" and f["when"] is None


def test_parse_prefix_is_case_insensitive():
    assert parse_extracted_facts("[sukien] đi họp")[0]["kind"] == "event"


def test_parse_skips_line_with_only_prefix():
    assert parse_extracted_facts("[BEN]   \n[BEN] Thật sự") == [
        {"text": "Thật sự", "kind": "durable", "when": None}]
