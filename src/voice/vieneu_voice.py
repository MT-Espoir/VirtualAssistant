"""
Giọng riêng bằng VieNeu-TTS — clone từ một đoạn thu ngắn, KHÔNG huấn luyện.

Khác `piper_voice.py` ở chỗ căn bản: Piper cần một model đã fine-tune cho riêng giọng
này; VieNeu clone thẳng từ ~3 giây audio mẫu. Đo 2026-08-26 trên máy này (xem
`docs/voice_finetune_spec.md` §4g):

    tiếng đầu (streaming)   1,36-1,50s, gần như không đổi theo độ dài câu
    RTF câu vừa/dài         0,73-0,88  -> sinh luôn chạy trước phát, không vấp
    nạp model               13-14,5s
    lượt suy luận đầu       5,7s  (khởi tạo ONNX session)

## Vì sao nạp NỀN

~20s cộng lại. Chặn khởi động ngần ấy thì câu đầu tiên người dùng nói phải chờ 20 giây —
không chấp nhận được. Nên nạp trong thread nền và trả False khi CHƯA sẵn sàng; người gọi
tự rơi về gtts. Trợ lý nói được ngay từ giây đầu, rồi tự đổi sang giọng riêng khi model
xong. Người dùng thấy giọng đổi giữa chừng, nhưng không bao giờ thấy im lặng.

MODE `v3turbo` (mặc định) chạy ONNX Runtime, KHÔNG cần torch, KHÔNG cần llama_cpp.
"""

import os
import threading
import wave

from utils.logger import get_logger

logger = get_logger(__name__)


class VieneuVoice:
    """Bọc một giọng clone. Dựng xong kiểm `thieu_gi()`; model tự nạp nền."""

    def __init__(self, cfg):
        """`cfg`: `voice.config.NoiConfig`."""
        self.ref_audio = cfg.vieneu_ref_audio
        self.precision = cfg.vieneu_precision
        self.mode = cfg.vieneu_mode
        self._tts = None
        self._loi_nap = None
        self._ly_do = None
        self._thread = None

    # --- kiểm tra trước khi dùng --------------------------------------------------

    def thieu_gi(self):
        """Liệt kê thứ còn thiếu. Rỗng = dùng được.

        Trả LÝ DO CỤ THỂ chứ không chỉ True/False — cùng lý lẽ như `piper_voice`: một
        giọng im lặng không hoạt động thì rất khó đoán vì sao.
        """
        thieu = []
        if not self.ref_audio:
            thieu.append("chưa khai VIENEU_REF_AUDIO trong .env")
        elif not os.path.exists(self.ref_audio):
            thieu.append(f"không thấy file audio mẫu: {self.ref_audio}")
        try:
            import vieneu  # noqa: F401
        except ImportError:
            thieu.append("chưa cài `vieneu` (xem docs/voice_finetune_spec.md §4g — "
                         "nhớ dùng --no-deps, gói này kéo theo cả gradio)")
        return thieu

    def kha_dung(self) -> bool:
        thieu = self.thieu_gi()
        if thieu:
            self._ly_do = "; ".join(thieu)
        return not thieu

    def ly_do_khong_dung_duoc(self):
        return self._ly_do

    # --- nạp nền -------------------------------------------------------------------

    def nap_nen(self):
        """Bắt đầu nạp model ở thread nền. Gọi ngay lúc trợ lý khởi động."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._nap, daemon=True)
        self._thread.start()

    def _nap(self):
        import time
        try:
            from vieneu import Vieneu

            t0 = time.time()
            tts = Vieneu(mode=self.mode, precision=self.precision)
            # Lượt đầu tốn ~5,7s khởi tạo ONNX session. Trả giá NGAY tại đây, trong thread
            # nền, để câu thật đầu tiên của người dùng không phải gánh.
            tts.infer(text="Xin chào.", ref_audio=self.ref_audio)
            self._tts = tts
            logger.info("🎙 giọng riêng (VieNeu) sẵn sàng sau %.1fs", time.time() - t0)
        except Exception as e:
            self._loi_nap = e
            logger.error("Không nạp được giọng riêng (%s) — dùng giọng mặc định.", e)

    @property
    def san_sang(self) -> bool:
        return self._tts is not None

    # --- tổng hợp ------------------------------------------------------------------

    def synth_wav(self, text: str, duong_dan: str) -> bool:
        """Sinh `text` ra WAV. False = chưa sẵn sàng hoặc lỗi -> người gọi dùng gtts.

        Trả False lúc model chưa nạp xong là đường chạy BÌNH THƯỜNG trong ~20s đầu, không
        phải lỗi — nên không ghi log ầm ĩ ở đó.
        """
        if not self.san_sang:
            return False
        try:
            audio = self._tts.infer(text=text, ref_audio=self.ref_audio)
            self._tts.save(audio, duong_dan)
            if os.path.getsize(duong_dan) < 1024:
                logger.error("Giọng riêng sinh ra file rỗng — quay về giọng mặc định.")
                return False
            return True
        except Exception as e:
            logger.error("Giọng riêng lỗi (%s) — quay về giọng mặc định.", e)
            return False

    def dong(self):
        if self._tts is not None:
            try:
                self._tts.close()
            except Exception:
                pass
            self._tts = None


def tao(cfg):
    """Dựng `VieneuVoice` và bắt đầu nạp nền; None kèm log nếu không dùng được."""
    if cfg.engine != "vieneu":
        return None
    v = VieneuVoice(cfg)
    if not v.kha_dung():
        logger.warning("TTS_ENGINE=vieneu nhưng chưa dùng được: %s — dùng gtts thay.",
                       v.ly_do_khong_dung_duoc())
        return None
    v.nap_nen()
    logger.info("🎙 đang nạp giọng riêng ở nền (~20s) — tạm nói bằng giọng mặc định.")
    return v
