"""Test split_text_for_tts — chia text dài cho gTTS (thuần). Bỏ qua nếu thiếu deps nặng
(pyttsx3/gtts/pygame) vì module import chúng ở cấp cao."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from voice import speech_synthesizer as ss
except Exception:                      # thiếu pyttsx3/pygame/gtts -> bỏ qua cả file
    pytest.skip("Thiếu phụ thuộc TTS (pyttsx3/gtts/pygame)", allow_module_level=True)

split = ss.split_text_for_tts
clean = ss.clean_for_speech


# --------------------------- dọn markdown trước khi đọc --------------------------- #

def test_strips_bold_and_italic():
    assert clean("Đây là **quan trọng** và *nghiêng*") == "Đây là quan trọng và nghiêng"


def test_strips_bullet_markers():
    out = clean("* Quản lý lịch\n* Hỗ trợ công việc")
    assert "*" not in out
    assert "Quản lý lịch" in out and "Hỗ trợ công việc" in out


def test_keeps_numbered_list():
    """Fix 7.1: người dùng phải NGHE được số để chọn kết quả tìm web."""
    out = clean("1. Trạm vũ trụ Quốc tế\n2. Trạm ISS")
    assert "1." in out and "2." in out


def test_strips_headings_and_code():
    assert clean("# Tiêu đề") == "Tiêu đề"
    assert clean("chạy `lệnh này`") == "chạy lệnh này"


def test_strips_links_keeping_text():
    assert clean("xem [trang chủ](https://a.b/c) nhé") == "xem trang chủ nhé"


def test_collapses_blank_lines():
    """Dòng trống = thêm ranh giới đoạn = thêm khoảng lặng khi đọc."""
    assert "\n\n" not in clean("Câu một.\n\n\nCâu hai.")


def test_keeps_plain_text_unchanged():
    assert clean("Chào anh Nam, hôm nay trời đẹp.") == "Chào anh Nam, hôm nay trời đẹp."


def test_handles_empty():
    assert clean("") == "" and clean(None) == ""


def test_asterisk_inside_word_is_kept():
    """Không được ăn nhầm dấu * không phải markdown (vd biểu thức 2*3)."""
    assert "2*3" in clean("kết quả 2*3 là 6")


def test_empty_returns_empty_list():
    assert split("") == []
    assert split("   ") == []


def test_short_text_single_chunk():
    assert split("Xin chào Minh.") == ["Xin chào Minh."]


def test_splits_on_sentence_boundary():
    text = "Câu một. Câu hai! Câu ba?"
    chunks = split(text, max_len=12)
    assert chunks == ["Câu một.", "Câu hai!", "Câu ba?"]


def test_groups_sentences_under_max_len():
    text = "A ngắn. B ngắn. C ngắn."
    # max_len đủ lớn để gộp 2 câu đầu nhưng không cả 3
    chunks = split(text, max_len=16)
    assert all(len(c) <= 16 for c in chunks)
    assert "".join(chunks).replace(" ", "") == "Angắn.Bngắn.Cngắn."


def test_hard_splits_overlong_sentence():
    long_sentence = "từ " * 100          # một 'câu' rất dài, không dấu kết câu
    chunks = split(long_sentence, max_len=50)
    assert len(chunks) > 1
    assert all(len(c) <= 50 for c in chunks)


def test_no_content_lost_for_normal_text():
    text = "Ngày xửa ngày xưa. Có một cậu bé tên Lâm! Cậu rất chăm chỉ."
    joined = " ".join(split(text, max_len=20))
    for word in ("Lâm", "chăm", "chỉ", "xửa"):
        assert word in joined
