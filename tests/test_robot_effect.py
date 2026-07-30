"""
Test hiệu ứng giọng robot (ring modulation) — hàm DSP thuần.

Cần numpy; nếu môi trường chưa có numpy thì bỏ qua (không tính là lỗi).
"""

try:
    import pytest
except ImportError:
    pytest = None

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# Thiếu numpy -> bỏ qua cả file (thay vì báo lỗi) khi chạy bằng pytest.
if pytest is not None:
    pytestmark = pytest.mark.skipif(not _HAS_NUMPY, reason="cần numpy cho DSP âm thanh")


def _run(fn):
    if not _HAS_NUMPY:
        print("SKIP (không có numpy):", fn.__name__)
        return True
    fn()
    return True


def test_ring_modulate_shape_and_dtype():
    from voice.robot_effect import ring_modulate
    rate = 22050
    t = np.arange(rate, dtype=np.float32) / rate
    tone = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)   # 1 giây 440Hz
    out = ring_modulate(tone, rate, carrier_hz=80)
    assert out.shape == tone.shape
    assert out.dtype == np.int16
    # Ring mod làm tín hiệu đổi khác (không trùng đầu vào)
    assert not np.array_equal(out, tone)


def test_ring_modulate_stereo():
    from voice.robot_effect import ring_modulate
    rate = 22050
    stereo = np.zeros((1000, 2), dtype=np.int16)
    stereo[:, 0] = 5000
    out = ring_modulate(stereo, rate, carrier_hz=60)
    assert out.shape == (1000, 2) and out.dtype == np.int16


def test_ring_modulate_empty():
    from voice.robot_effect import ring_modulate
    out = ring_modulate(np.array([], dtype=np.int16), 22050)
    assert out.size == 0


# --------------------------- resample_speed --------------------------- #

def test_resample_speed_shortens_when_faster():
    from voice.robot_effect import resample_speed
    x = np.arange(1000, dtype=np.int16)
    out = resample_speed(x, 2.0)                 # nhanh gấp đôi -> ~1/2 số mẫu
    assert out.dtype == np.int16
    assert abs(out.shape[0] - 500) <= 1


def test_resample_speed_lengthens_when_slower():
    from voice.robot_effect import resample_speed
    x = np.arange(1000, dtype=np.int16)
    out = resample_speed(x, 0.5)                 # chậm nửa -> ~gấp đôi số mẫu
    assert abs(out.shape[0] - 2000) <= 1


def test_resample_speed_factor_one_unchanged():
    from voice.robot_effect import resample_speed
    x = np.arange(50, dtype=np.int16)
    assert np.array_equal(resample_speed(x, 1.0), x)


def test_resample_speed_stereo_keeps_channels():
    from voice.robot_effect import resample_speed
    x = np.zeros((1000, 2), dtype=np.int16)
    out = resample_speed(x, 1.5)
    assert out.ndim == 2 and out.shape[1] == 2


def test_resample_speed_empty_and_bad_factor():
    from voice.robot_effect import resample_speed
    assert resample_speed(np.array([], dtype=np.int16), 2.0).size == 0
    x = np.arange(10, dtype=np.int16)
    assert np.array_equal(resample_speed(x, 0), x)      # factor không hợp lệ -> giữ nguyên


if __name__ == "__main__":
    if pytest is not None and _HAS_NUMPY:
        raise SystemExit(pytest.main([__file__, "-v"]))
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _run(_fn)
                print("PASS", _name)
            except Exception as _e:  # noqa: BLE001
                failures += 1
                print("FAIL", _name, "->", repr(_e))
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    raise SystemExit(1 if failures else 0)
