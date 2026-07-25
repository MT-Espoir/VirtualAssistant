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


def _run(fn):
    if not _HAS_NUMPY:
        print("SKIP (không có numpy):", fn.__name__)
        return True
    fn()
    return True


def test_ring_modulate_shape_and_dtype():
    from audio.robot_effect import ring_modulate
    rate = 22050
    t = np.arange(rate, dtype=np.float32) / rate
    tone = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)   # 1 giây 440Hz
    out = ring_modulate(tone, rate, carrier_hz=80)
    assert out.shape == tone.shape
    assert out.dtype == np.int16
    # Ring mod làm tín hiệu đổi khác (không trùng đầu vào)
    assert not np.array_equal(out, tone)


def test_ring_modulate_stereo():
    from audio.robot_effect import ring_modulate
    rate = 22050
    stereo = np.zeros((1000, 2), dtype=np.int16)
    stereo[:, 0] = 5000
    out = ring_modulate(stereo, rate, carrier_hz=60)
    assert out.shape == (1000, 2) and out.dtype == np.int16


def test_ring_modulate_empty():
    from audio.robot_effect import ring_modulate
    out = ring_modulate(np.array([], dtype=np.int16), 22050)
    assert out.size == 0


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
