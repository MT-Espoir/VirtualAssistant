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
