"""Test tiện ích STT thuần (voice.stt_utils)."""

try:
    import pytest
except ImportError:
    pytest = None

from voice.stt_utils import whisper_lang_code


def test_strips_region_suffix():
    assert whisper_lang_code("vi-VN") == "vi"
    assert whisper_lang_code("en-US") == "en"


def test_plain_code_lowercased():
    assert whisper_lang_code("VI") == "vi"
    assert whisper_lang_code("en") == "en"


def test_empty_or_none_returns_none():
    assert whisper_lang_code("") is None
    assert whisper_lang_code(None) is None


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
