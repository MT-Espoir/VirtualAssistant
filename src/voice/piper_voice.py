"""
Chạy GIỌNG RIÊNG đã fine-tune (Piper / VITS) — sinh file WAV từ câu chữ.

Piper xuất giọng ra CẶP file:
    <tên>.onnx        trọng số model
    <tên>.onnx.json   cấu hình: bảng phoneme, sample rate, số giọng

Suy luận cần hai bước: chữ -> phoneme -> sóng âm. Bước phoneme phụ thuộc `piper-tts`
(hoặc `piper-phonemize`); bước sóng âm chỉ cần `onnxruntime`, vốn đã có sẵn trong máy.

THIẾT KẾ CÓ CHỦ ĐÍCH: module này KHÔNG import gì ở cấp module. Trợ lý phải chạy được
khi chưa cài Piper và chưa có giọng riêng — đó là trạng thái mặc định của mọi người
dùng. Thiếu thư viện hay thiếu file thì `kha_dung()` trả False và người gọi rơi về gtts.

Xem `docs/voice_finetune_spec.md` cho phần huấn luyện.
"""

import os
import wave

from utils.logger import get_logger

logger = get_logger(__name__)


class PiperVoice:
    """Bọc một giọng Piper đã xuất. Dựng xong phải kiểm `kha_dung()` trước khi dùng."""

    def __init__(self, cfg):
        """`cfg`: `voice.config.NoiConfig`."""
        self.model = cfg.piper_model
        self.config = cfg.piper_config or (f"{cfg.piper_model}.json" if cfg.piper_model else "")
        self.speaker = cfg.piper_speaker
        self.length_scale = cfg.piper_length_scale
        self.noise_scale = cfg.piper_noise_scale
        self._voice = None
        self._ly_do = None

    # --- kiểm tra trước khi dùng --------------------------------------------------

    def thieu_gi(self):
        """Liệt kê thứ còn thiếu để chạy được. Rỗng = sẵn sàng.

        Trả LÝ DO CỤ THỂ chứ không chỉ True/False: người dùng vừa huấn luyện xong một
        giọng mà nó im lặng rơi về Google thì rất khó đoán vì sao.
        """
        thieu = []
        if not self.model:
            thieu.append("chưa khai PIPER_MODEL trong .env")
        elif not os.path.exists(self.model):
            thieu.append(f"không thấy file model: {self.model}")
        elif not os.path.exists(self.config):
            thieu.append(f"không thấy file cấu hình: {self.config} "
                         "(Piper xuất ra CẶP .onnx + .onnx.json)")
        try:
            import piper  # noqa: F401
        except ImportError:
            thieu.append("chưa cài `piper-tts` (pip install piper-tts)")
        return thieu

    def kha_dung(self) -> bool:
        thieu = self.thieu_gi()
        if thieu:
            self._ly_do = "; ".join(thieu)
        return not thieu

    def ly_do_khong_dung_duoc(self):
        return self._ly_do

    # --- tổng hợp ------------------------------------------------------------------

    def _nap(self):
        if self._voice is None:
            from piper import PiperVoice as _PV
            self._voice = _PV.load(self.model, config_path=self.config)
            logger.info("🎙 giọng riêng: đã nạp %s", os.path.basename(self.model))
        return self._voice

    def synth_wav(self, text: str, duong_dan: str) -> bool:
        """Sinh `text` ra file WAV tại `duong_dan`. Trả False nếu lỗi (người gọi rơi về gtts).

        Không ném lỗi ra ngoài: mất giọng riêng chỉ nên làm trợ lý đổi giọng, không nên
        làm nó câm.
        """
        try:
            voice = self._nap()
            with wave.open(duong_dan, "wb") as f:
                voice.synthesize(text, f,
                                 speaker_id=self.speaker or None,
                                 length_scale=self.length_scale,
                                 noise_scale=self.noise_scale)
            return True
        except Exception as e:
            logger.error("Giọng riêng lỗi (%s) — quay về giọng mặc định.", e)
            return False


def tao(cfg):
    """Dựng `PiperVoice` nếu dùng được; None kèm log giải thích nếu không.

    Người gọi chỉ cần: `giong = piper_voice.tao(cfg) or None` rồi rơi về engine cũ.
    """
    if cfg.engine != "piper":
        return None
    v = PiperVoice(cfg)
    if v.kha_dung():
        return v
    logger.warning("TTS_ENGINE=piper nhưng chưa dùng được: %s — dùng gtts thay.",
                   v.ly_do_khong_dung_duoc())
    return None
