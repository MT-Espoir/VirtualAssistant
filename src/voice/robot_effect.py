"""
Hiệu ứng "giọng robot" bằng ring modulation.
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


def resample_speed(samples, factor):
    """Đổi tốc độ phát bằng cách nội suy lại số mẫu (giữ nguyên sample rate khi phát).

    factor > 1 -> nhanh hơn (ít mẫu hơn); factor < 1 -> chậm hơn. Nội suy tuyến tính,
    KHÔNG bảo toàn cao độ (nhanh hơn = cao giọng hơn — hợp với giọng robot). Hàm thuần.

    Args:
        samples: mảng numpy int16, shape (n,) hoặc (n, channels).
        factor: hệ số tốc độ (>0).

    Returns:
        mảng int16 cùng số kênh, độ dài ~ n/factor.
    """
    x = np.asarray(samples)
    if x.size == 0 or factor <= 0 or factor == 1.0:
        return x

    n = x.shape[0]
    new_n = max(1, int(round(n / factor)))
    idx = np.linspace(0, n - 1, new_n)
    lo = np.floor(idx).astype(np.int64)
    hi = np.minimum(lo + 1, n - 1)
    frac = (idx - lo).astype(np.float32)
    if x.ndim == 2:
        frac = frac[:, None]

    out = x[lo].astype(np.float32) * (1.0 - frac) + x[hi].astype(np.float32) * frac
    return np.clip(out, -32768, 32767).astype(np.int16)
