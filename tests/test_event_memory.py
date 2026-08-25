"""Test trí nhớ có MỐC THỜI GIAN — chống bug 'nhắc việc đã xong như sắp diễn ra'.

Bối cảnh thật: người dùng cho trợ lý tự giới thiệu trong buổi phỏng vấn lúc trưa; tối
cùng ngày trợ lý vẫn nhắc buổi phỏng vấn như sắp tới. Nguyên nhân: (1) prompt không có
ngày giờ hiện tại nên model không có gì để so, (2) ghi chú lưu dạng chuỗi trần không mốc
thời gian nên "Đang phỏng vấn..." bị đóng băng vĩnh viễn.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.timefmt import (describe_age, format_now, is_past,          # noqa: E402
                           older_than_days, parse_iso)
from memory.profile import (UserProfile, apply_update, describe_events, find_memories,   # noqa: E402
                                          make_event, prune_events, summarize)

NOON = datetime(2026, 8, 8, 12, 0)
EVENING = datetime(2026, 8, 8, 22, 0)


# --------------------------- mốc thời gian --------------------------- #

def test_format_now_has_date_time_and_weekday():
    s = format_now(datetime(2026, 8, 8, 21, 45))     # 08/08/2026 là thứ Bảy
    assert "21:45" in s and "08/08/2026" in s and "thứ Bảy" in s


def test_parse_iso_tolerates_garbage():
    assert parse_iso("khong-phai-ngay") is None
    assert parse_iso("") is None and parse_iso(None) is None
    assert parse_iso("2026-08-08T12:00") == NOON


def test_event_is_not_past_right_after_it_starts():
    """Phỏng vấn 12h thì 12h30 vẫn đang diễn ra — đừng vội coi là xong."""
    assert is_past(NOON.isoformat(), now=NOON + timedelta(minutes=30)) is False


def test_event_is_past_later_the_same_day():
    """Đây chính là kịch bản đã lỗi: trưa phỏng vấn, tối phải biết là đã qua."""
    assert is_past(NOON.isoformat(), now=EVENING) is True


def test_unknown_time_is_never_past():
    """Không rõ giờ -> giữ lại (thà thừa còn hơn xoá nhầm việc sắp tới)."""
    assert is_past(None, now=EVENING) is False


def test_describe_age_reads_naturally():
    assert describe_age(NOON.isoformat(), now=EVENING) == "hôm nay"
    assert describe_age(NOON.isoformat(), now=NOON + timedelta(days=1)) == "hôm qua"
    assert describe_age(NOON.isoformat(), now=NOON + timedelta(days=3)) == "3 ngày trước"


def test_older_than_days():
    assert older_than_days(NOON.isoformat(), 7, now=NOON + timedelta(days=8)) is True
    assert older_than_days(NOON.isoformat(), 7, now=EVENING) is False
    assert older_than_days(None, 7, now=EVENING) is False


# --------------------------- ghi sự kiện --------------------------- #

def test_note_with_when_becomes_event_not_durable_note():
    data, changes = apply_update({}, note="phỏng vấn với anh Nam", when=NOON.isoformat(),
                                 now=NOON)
    assert data["notes"] == []                       # KHÔNG vào kho bền vững
    assert len(data["events"]) == 1
    assert data["events"][0]["text"] == "phỏng vấn với anh Nam"
    assert "sự kiện" in changes[0]


def test_recording_a_long_past_event_still_stores_it():
    """Kể lại việc đã qua lâu vẫn phải vào kho — không thể báo "đã nhớ" mà kho rỗng."""
    old = (NOON - timedelta(days=30)).isoformat()
    data, changes = apply_update({}, note="phỏng vấn cũ", when=old, now=NOON)
    assert len(data["events"]) == 1 and "sự kiện" in changes[0]


def test_note_without_when_stays_durable():
    data, _ = apply_update({}, note="thích cà phê")
    assert data["notes"] == ["thích cà phê"] and data["events"] == []


def test_make_event_tolerates_bad_time():
    e = make_event("đi khám", when="chiều nay", now=NOON)
    assert e["when"] is None and e["created_at"].startswith("2026-08-08")


# --------------------------- render theo trạng thái --------------------------- #

def test_past_event_is_labelled_past():
    events = [make_event("phỏng vấn với anh Nam", NOON.isoformat(), now=NOON)]
    upcoming, past = describe_events(events, now=EVENING)
    assert upcoming == [] and len(past) == 1
    assert "phỏng vấn với anh Nam" in past[0] and "hôm nay" in past[0]


def test_upcoming_event_shows_time():
    events = [make_event("họp nhóm", (EVENING).isoformat(), now=NOON)]
    upcoming, past = describe_events(events, now=NOON)
    assert past == [] and "22:00" in upcoming[0]


def test_summary_warns_not_to_mention_past_event_as_upcoming():
    """Câu bơm vào prompt phải NÓI RÕ là việc cũ, nếu không model lại nhắc như sắp tới."""
    data = {"events": [make_event("phỏng vấn với anh Nam", NOON.isoformat(), now=NOON)]}
    s = summarize(data, now=EVENING)
    assert "ĐÃ QUA" in s and "đừng nhắc như sắp" in s


def test_summary_separates_upcoming_from_past():
    data = {"events": [
        make_event("phỏng vấn", NOON.isoformat(), now=NOON),
        make_event("họp tối", EVENING.isoformat(), now=NOON),
    ]}
    s = summarize(data, now=NOON + timedelta(hours=4))    # 16h: phỏng vấn qua, họp chưa
    assert "Sắp tới" in s and "ĐÃ QUA" in s


def test_events_are_injected_even_when_query_unrelated():
    """Sự kiện KHÔNG đi qua truy hồi theo từ khoá — mọi lượt đều cần biết việc nào đã xong."""
    data = {"notes": [f"ghi chú {i}" for i in range(8)],
            "events": [make_event("phỏng vấn", NOON.isoformat(), now=NOON)]}
    s = summarize(data, query="tăng âm lượng lên", now=EVENING)
    assert "phỏng vấn" in s


# --------------------------- tự dọn --------------------------- #

def test_prune_drops_events_older_than_keep_days():
    old = make_event("việc cũ", (NOON - timedelta(days=30)).isoformat(), now=NOON)
    fresh = make_event("việc mới", NOON.isoformat(), now=NOON)
    kept = prune_events([old, fresh], now=EVENING, keep_days=7)
    assert [e["text"] for e in kept] == ["việc mới"]


def test_prune_keeps_recent_past_event_for_follow_up():
    """Giữ vài ngày để còn hỏi thăm 'hôm qua phỏng vấn sao rồi?'."""
    e = make_event("phỏng vấn", NOON.isoformat(), now=NOON)
    assert prune_events([e], now=NOON + timedelta(days=2), keep_days=7) == [e]


# --------------------------- quên (forget) --------------------------- #

def _profile(tmp_path, **data):
    p = UserProfile(path=str(tmp_path / "p.json"))
    p.data = {"notes": [], "auto_facts": [], "events": [], "preferences": {}, **data}
    return p


def test_find_memories_matches_across_all_stores():
    data = {"notes": ["thích cà phê"], "auto_facts": ["hay thức khuya"],
            "events": [make_event("phỏng vấn với anh Nam", NOON.isoformat(), now=NOON)]}
    assert len(find_memories(data, "phỏng vấn")) == 1
    assert find_memories(data, "cà phê")[0][0] == "notes"
    assert find_memories(data, "thức khuya")[0][0] == "auto_facts"


def test_find_memories_ignores_accents_and_case():
    data = {"notes": ["Đang phỏng vấn với anh Nam"]}
    assert len(find_memories(data, "PHONG VAN")) == 1


def test_find_memories_empty_keyword_matches_nothing():
    """Từ khoá rỗng KHÔNG được khớp tất cả — sẽ xoá nhầm sạch trí nhớ."""
    assert find_memories({"notes": ["a", "b"]}, "") == []
    assert find_memories({"notes": ["a"]}, None) == []


def test_forget_removes_matching_note(tmp_path):
    p = _profile(tmp_path, notes=["Đang phỏng vấn với anh Nam"])
    assert "Đã quên" in p.forget("phỏng vấn")
    assert p.data["notes"] == []


def test_forget_removes_matching_event(tmp_path):
    p = _profile(tmp_path,
                 events=[make_event("phỏng vấn", NOON.isoformat(), now=NOON)])
    assert "Đã quên" in p.forget("phỏng vấn")
    assert p.data["events"] == []


def test_forget_asks_back_when_many_match(tmp_path):
    """Khớp nhiều -> HỎI LẠI, không đoán: xoá nhầm trí nhớ không khôi phục được."""
    p = _profile(tmp_path, notes=["phỏng vấn ở A", "phỏng vấn ở B"])
    out = p.forget("phỏng vấn")
    assert "muốn tôi quên điều nào" in out
    assert len(p.data["notes"]) == 2            # chưa xoá gì cả


def test_forget_reports_when_nothing_matches(tmp_path):
    p = _profile(tmp_path, notes=["thích cà phê"])
    assert "không nhớ" in p.forget("bóng đá").lower()


def test_forget_persists(tmp_path):
    p = _profile(tmp_path, notes=["thích cà phê"])
    p.forget("cà phê")
    assert UserProfile(path=p.path).data["notes"] == []


def test_forget_tool_is_destructive():
    """Xoá trí nhớ phải qua cổng xác nhận."""
    from unittest.mock import MagicMock
    from conftest import registry_with
    reg = registry_with(profile=MagicMock())
    assert reg.has("forget_about_user")
    assert reg.get("forget_about_user").destructive is True
