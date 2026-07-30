"""Test lớp sửa lỗi nhận dạng (voice.corrections) — thuần, không I/O."""

try:
    import pytest
except ImportError:
    pytest = None

from voice.corrections import apply_corrections, load_corrections

MAP = {"hip hop": "github", "diu túp": "youtube", "phây búc": "facebook"}


def test_fixes_github_in_sentence():
    assert apply_corrections("mở hip hop", MAP) == "mở github"


def test_fixes_ignoring_accents_and_case():
    # STT có thể trả 'Hip Hop' hoặc không dấu
    assert apply_corrections("mở Hip Hop giúp mình", MAP) == "mở github giúp mình"


def test_fixes_multiword_target():
    assert apply_corrections("vào diu túp", MAP) == "vào youtube"


def test_leaves_unrelated_text_untouched():
    assert apply_corrections("mở trình duyệt chrome", MAP) == "mở trình duyệt chrome"


def test_multiple_corrections_in_one_sentence():
    got = apply_corrections("mở hip hop rồi phây búc", MAP)
    assert got == "mở github rồi facebook"


def test_empty_and_none_safe():
    assert apply_corrections("", MAP) == ""
    assert apply_corrections(None, MAP) is None
    assert apply_corrections("mở hip hop", {}) == "mở hip hop"


def test_longer_phrase_preferred_over_shorter():
    # cụm 2 từ được ưu tiên trước cụm 1 từ trùng token đầu
    m = {"hip hop": "github", "hip": "hông"}
    assert apply_corrections("nghe hip hop", m) == "nghe github"


def test_load_corrections_includes_defaults():
    corr = load_corrections("khong_ton_tai.json")   # file thiếu -> chỉ mặc định
    assert corr.get("hip hop") == "github"


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
