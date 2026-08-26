"""Test module giọng nói: gom cấu hình + cắm giọng riêng đã fine-tune."""

import os
import tempfile
from types import SimpleNamespace

from voice import config as vcfg
from voice import piper_voice


def _cfg(**kw):
    """Giả `utils.config.config` — chỉ có những trường được truyền vào."""
    return SimpleNamespace(**kw)


# --- gom cấu hình -------------------------------------------------------------------

def test_gom_du_ca_hai_chieu():
    vc = vcfg.from_config(_cfg(STT_ENGINE="whisper", TTS_ENGINE="gtts",
                               SAMPLE_RATE=22050, TTS_SPEED=1.5))
    assert vc.nghe.engine == "whisper"
    assert vc.nghe.sample_rate == 22050
    assert vc.noi.engine == "gtts"
    assert vc.noi.speed == 1.5


def test_thieu_truong_thi_dung_mac_dinh_chu_khong_no():
    """Tham số Piper chỉ có khi người dùng khai trong .env — trợ lý phải chạy khi chưa khai."""
    vc = vcfg.from_config(_cfg())
    assert vc.noi.engine == "gtts"
    assert vc.noi.piper_model == ""
    assert vc.dung_giong_rieng is False


def test_wake_words_tach_va_bo_khoang_trang():
    vc = vcfg.from_config(_cfg(WAKE_WORDS="trợ lý, jarvis ,, alice"))
    assert vc.wake_words == ("trợ lý", "jarvis", "alice")


def test_dung_giong_rieng_khi_engine_la_piper():
    assert vcfg.from_config(_cfg(TTS_ENGINE="piper")).dung_giong_rieng is True


def test_khong_doc_thang_bien_moi_truong():
    """`utils/config.py` VẪN là nơi duy nhất đọc env — module này chỉ nhóm lại.

    Hai nơi cùng đọc env là hai nguồn sự thật, và chúng sẽ lệch nhau.

    Soi bằng AST chứ không tìm chuỗi: chính docstring của module có nhắc `os.environ` để
    giải thích điều này, tìm chuỗi sẽ bắt nhầm đúng câu văn nói rằng nó không làm vậy.
    """
    import ast

    nguon = open(os.path.join(os.path.dirname(vcfg.__file__), "config.py"),
                 encoding="utf-8").read()
    for node in ast.walk(ast.parse(nguon)):
        if isinstance(node, ast.Attribute):
            assert node.attr not in ("environ", "getenv"), "đọc env thẳng trong voice/config.py"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            ten = getattr(node, "module", None) or ""
            assert "os" not in ten.split("."), "voice/config.py không cần tới `os`"


# --- giọng riêng: báo rõ lý do thay vì im lặng ---------------------------------------

def test_chua_khai_model_thi_noi_ro():
    thieu = piper_voice.PiperVoice(vcfg.NoiConfig()).thieu_gi()
    assert any("PIPER_MODEL" in t for t in thieu)


def test_khai_model_nhung_khong_co_file_thi_noi_ro():
    thieu = piper_voice.PiperVoice(
        vcfg.NoiConfig(piper_model="C:/khong/co/that.onnx")).thieu_gi()
    assert any("không thấy file model" in t for t in thieu)


def test_co_onnx_nhung_thieu_json_thi_noi_ro():
    """Piper xuất ra CẶP file. Thiếu .json là lỗi rất dễ mắc khi copy model sang máy khác."""
    with tempfile.TemporaryDirectory() as d:
        onnx = os.path.join(d, "giong.onnx")
        open(onnx, "wb").close()
        thieu = piper_voice.PiperVoice(vcfg.NoiConfig(piper_model=onnx)).thieu_gi()
    assert any("không thấy file cấu hình" in t for t in thieu)


def test_suy_ra_duong_dan_config_tu_model():
    v = piper_voice.PiperVoice(vcfg.NoiConfig(piper_model="a/giong.onnx"))
    assert v.config == "a/giong.onnx.json"


def test_engine_khong_phai_piper_thi_tao_tra_None():
    assert piper_voice.tao(vcfg.NoiConfig(engine="gtts")) is None


def test_piper_thieu_dieu_kien_thi_tra_None_chu_khong_nem(caplog):
    """Giọng riêng hỏng chỉ nên làm trợ lý ĐỔI GIỌNG, không được làm nó câm."""
    import logging

    with caplog.at_level(logging.WARNING):
        got = piper_voice.tao(vcfg.NoiConfig(engine="piper", piper_model="/khong/co.onnx"))
    assert got is None
    assert "dùng gtts thay" in caplog.text


# --- bộ tổng hợp coi giọng riêng như một engine sinh file -----------------------------

def test_piper_dung_chung_duong_phat_voi_gtts():
    """`piper` cũng sinh file rồi phát, nên tái dùng hết barge-in / robot / chỉnh tốc độ.

    Kiểm qua thuộc tính `_phat_qua_file` — nó tồn tại để thêm engine sinh file chỉ phải
    sửa MỘT chỗ, thay vì 6 nhánh `engine_type == "gtts"` rải khắp file.
    """
    from voice.speech_synthesizer import SpeechSynthesizer

    tu = SpeechSynthesizer.__new__(SpeechSynthesizer)
    for e, mong_doi in (("gtts", True), ("piper", True), ("pyttsx3", False)):
        tu.engine_type = e
        assert tu._phat_qua_file is mong_doi, e


# --- giọng clone VieNeu: nạp nền, suy biến an toàn ------------------------------------

def test_vieneu_chua_khai_ref_thi_noi_ro():
    from voice import vieneu_voice
    thieu = vieneu_voice.VieneuVoice(vcfg.NoiConfig(engine="vieneu")).thieu_gi()
    assert any("VIENEU_REF_AUDIO" in t for t in thieu)


def test_vieneu_ref_khong_ton_tai_thi_noi_ro():
    from voice import vieneu_voice
    thieu = vieneu_voice.VieneuVoice(
        vcfg.NoiConfig(engine="vieneu", vieneu_ref_audio="C:/khong/co.wav")).thieu_gi()
    assert any("không thấy file audio mẫu" in t for t in thieu)


def test_engine_khac_thi_tao_tra_None():
    from voice import vieneu_voice
    assert vieneu_voice.tao(vcfg.NoiConfig(engine="gtts")) is None


def test_chua_nap_xong_thi_synth_tra_False_chu_khong_no():
    """~20s đầu model chưa sẵn sàng — đó là đường chạy BÌNH THƯỜNG, không phải lỗi."""
    from voice import vieneu_voice
    v = vieneu_voice.VieneuVoice(vcfg.NoiConfig(engine="vieneu", vieneu_ref_audio="x.wav"))
    assert v.san_sang is False
    assert v.synth_wav("bất kỳ", "khong_ghi_gi.wav") is False


def test_dang_nap_KHONG_bi_tat_vinh_vien():
    """Bẫy thật: `_giong_rieng_synth` tắt hẳn giọng riêng sau lần hỏng đầu.

    VieNeu nạp nền nên câu ĐẦU TIÊN luôn rơi vào lúc chưa xong. Nếu coi đó là hỏng thì
    giọng riêng không bao giờ được dùng — nạp xong cũng vô ích.
    """
    from voice.speech_synthesizer import SpeechSynthesizer

    class _DangNap:
        san_sang = False
        def synth_wav(self, text, path):
            raise AssertionError("không được gọi khi chưa sẵn sàng")

    tu = SpeechSynthesizer.__new__(SpeechSynthesizer)
    tu._giong_rieng = _DangNap()
    assert tu._giong_rieng_synth("xin chào") is None
    assert tu._giong_rieng is not None, "chưa nạp xong KHÔNG phải lý do để tắt vĩnh viễn"


def test_hong_THAT_thi_tat_vinh_vien():
    """Ngược lại: hỏng thật thì thôi, khỏi thử lại mỗi câu."""
    from voice.speech_synthesizer import SpeechSynthesizer

    class _Hong:
        san_sang = True
        def synth_wav(self, text, path):
            return False

    tu = SpeechSynthesizer.__new__(SpeechSynthesizer)
    tu._giong_rieng = _Hong()
    assert tu._giong_rieng_synth("xin chào") is None
    assert tu._giong_rieng is None


def test_vieneu_cung_dung_duong_phat_qua_file():
    from voice.speech_synthesizer import SpeechSynthesizer
    tu = SpeechSynthesizer.__new__(SpeechSynthesizer)
    for e, mong_doi in (("gtts", True), ("piper", True), ("vieneu", True), ("pyttsx3", False)):
        tu.engine_type = e
        assert tu._phat_qua_file is mong_doi, e
