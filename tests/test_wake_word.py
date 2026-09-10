"""Test logic từ khoá kích hoạt (voice.wake_word) — thuần, không I/O."""

try:
    import pytest
except ImportError:
    pytest = None

from voice.wake_word import (in_follow_up_window, match_wake_word, parse_wake_words,
                             wake_words_not_in)

WORDS = ["trợ lý", "tro ly", "jarvis", "assistant"]


# --------------------------- parse_wake_words --------------------------- #

def test_parse_splits_and_trims():
    assert parse_wake_words("a, b ,c") == ["a", "b", "c"]
    assert parse_wake_words("  x  ") == ["x"]
    assert parse_wake_words("") == []


# --------------------------- match: khớp --------------------------- #

def test_match_at_start_returns_remainder():
    ok, rest = match_wake_word("trợ lý mở nhạc", WORDS)
    assert ok and rest == "mở nhạc"


def test_match_ignores_accents():
    # STT trả không dấu vẫn khớp từ khoá "trợ lý"
    ok, rest = match_wake_word("tro ly mo youtube", WORDS)
    assert ok and rest == "mo youtube"


def test_match_strips_leading_punctuation():
    ok, rest = match_wake_word("Jarvis, tắt đèn", WORDS)
    assert ok and rest == "tắt đèn"


def test_match_wake_word_only_gives_empty_remainder():
    ok, rest = match_wake_word("trợ lý", WORDS)
    assert ok and rest == ""


def test_match_case_insensitive():
    ok, rest = match_wake_word("JARVIS mở đèn", WORDS)
    assert ok and rest == "mở đèn"


# --------------------------- match: không khớp (lời nhạc/clip) --------------------------- #

def test_no_match_for_song_lyrics():
    ok, rest = match_wake_word("lấp lánh trên bầu trời đêm nay", WORDS)
    assert not ok and rest == "lấp lánh trên bầu trời đêm nay"


def test_no_match_empty_text():
    ok, rest = match_wake_word("", WORDS)
    assert not ok and rest == ""


# --------------------------- không cấu hình từ khoá -> luôn khớp --------------------------- #

def test_empty_wake_words_always_matches():
    ok, rest = match_wake_word("bất kỳ câu gì", [])
    assert ok and rest == "bất kỳ câu gì"


# --------------------------- wake_words_not_in (lọc echo cho barge-in) --------------------------- #

def test_filters_wake_word_present_in_ai_response():
    # AI nói "trợ lý" trong câu trả lời -> loại khỏi danh sách để không tự ngắt lời
    remaining = wake_words_not_in("Tôi là trợ lý của bạn", WORDS)
    assert "trợ lý" not in remaining and "tro ly" not in remaining
    assert "jarvis" in remaining and "assistant" in remaining


def test_keeps_all_when_response_has_no_wake_word():
    remaining = wake_words_not_in("Đã mở Chrome cho bạn", WORDS)
    assert set(remaining) == set(WORDS)


def test_filter_ignores_accents():
    # câu trả lời không dấu vẫn khớp và loại được từ khoá
    remaining = wake_words_not_in("toi la tro ly cua ban", WORDS)
    assert "trợ lý" not in remaining and "tro ly" not in remaining


# --------------------------- cửa sổ nối lời (10s sau câu trả lời) --------------------------- #

def test_follow_up_open_right_after_answer():
    assert in_follow_up_window(100.0, 103.0, 10.0)


def test_follow_up_closed_after_window():
    assert not in_follow_up_window(100.0, 110.5, 10.0)


def test_follow_up_open_at_exact_edge():
    assert in_follow_up_window(100.0, 110.0, 10.0)


def test_follow_up_closed_before_first_answer():
    """Chưa trả lời lần nào -> chưa có gì để nối lời, từ khoá vẫn bắt buộc."""
    assert not in_follow_up_window(None, 100.0, 10.0)


def test_follow_up_disabled_by_zero_window():
    assert not in_follow_up_window(100.0, 100.1, 0)


def test_follow_up_counts_speech_starting_before_answer_ends():
    """Nói chen lúc trợ lý chưa dứt câu -> vẫn là nối lời, không phải câu lạ."""
    assert in_follow_up_window(100.0, 99.0, 10.0)


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print("PASS", _name)
            except Exception as _e:  # noqa: BLE001
                failures += 1
                print("FAIL", _name, "->", repr(_e))
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    raise SystemExit(1 if failures else 0)
