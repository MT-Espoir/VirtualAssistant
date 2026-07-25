"""
Hiệu ứng "giọng robot" bằng ring modulation.

Nhân tín hiệu âm thanh với một sóng mang hình sin tần số thấp (~50-100Hz) tạo chất
giọng kim loại/robot kinh điển mà VẪN giữ phát âm gốc (tiếng Việt của gTTS).

ring_modulate() là hàm thuần trên mảng numpy — không phụ thuộc pygame/thiết bị âm
thanh, nên test được.
"""

import numpy as np


def ring_modulate(samples, rate, carrier_hz=80.0):
    """Áp ring modulation lên mẫu âm thanh int16 (mono hoặc stereo).

    Args:
        samples: mảng numpy int16, shape (n,) hoặc (n, channels).
        rate: tần số lấy mẫu (Hz).
        carrier_hz: tần số sóng mang; càng thấp càng "robot".

    Returns:
        mảng int16 cùng shape đã áp hiệu ứng.
    """
    x = np.asarray(samples)
    if x.size == 0:
        return x

    n = x.shape[0]
    t = np.arange(n, dtype=np.float32) / float(rate)
    carrier = np.sin(2.0 * np.pi * carrier_hz * t).astype(np.float32)
    if x.ndim == 2:                       # stereo -> broadcast theo kênh
        carrier = carrier[:, None]

    out = x.astype(np.float32) * carrier
    return np.clip(out, -32768, 32767).astype(np.int16)
