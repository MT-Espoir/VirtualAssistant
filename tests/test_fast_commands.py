"""Test fast-path lệnh trực tiếp (voice.fast_commands) — thuần, không I/O."""

try:
    import pytest
except ImportError:
    pytest = None

from voice.fast_commands import (match_fast_command, match_avatar_command,
                                 match_mode_command, match_confirmation,
                                 match_persona_command)


def test_scroll_down_variants():
    for t in ("cuộn xuống", "lướt xuống", "kéo xuống tiếp", "cuon xuong"):
        assert match_fast_command(t) == ("scroll_screen", {"direction": "down"})


def test_scroll_up_variants():
    for t in ("cuộn lên", "lướt lên", "keo len"):
        assert match_fast_command(t) == ("scroll_screen", {"direction": "up"})


def test_screenshot_variants():
    for t in ("chụp màn hình", "chụp lại màn hình", "screenshot"):
        assert match_fast_command(t) == ("take_screenshot", {})


def test_matches_within_longer_sentence():
    # câu có thêm chữ vẫn khớp (vd sau khi bỏ wake word)
    assert match_fast_command("giúp tôi cuộn xuống với") == ("scroll_screen", {"direction": "down"})


def test_ignores_accents_and_case():
    assert match_fast_command("CUỘN XUỐNG") == ("scroll_screen", {"direction": "down"})


def test_non_command_returns_none():
    for t in ("mở chrome", "bật bài lấp lánh", "hôm nay thế nào", "", None):
        assert match_fast_command(t) is None


# --------------------------- fast-path âm lượng --------------------------- #

def test_volume_absolute_level():
    assert match_fast_command("tăng âm lượng lên 35%") == ("set_volume", {"level": 35})
    assert match_fast_command("đặt âm lượng 80") == ("set_volume", {"level": 80})


def test_volume_relative_up_down():
    assert match_fast_command("tăng âm lượng") == ("set_volume", {"change": 10})
    assert match_fast_command("giảm âm lượng") == ("set_volume", {"change": -10})


def test_volume_video_routes_to_browser():
    assert match_fast_command("âm lượng video 50%") == \
        ("browser_media_control", {"action": "set_volume", "value": 50})


def test_volume_video_without_number_defers_to_llm():
    # media không kèm số -> None (để LLM xử tăng/giảm tương đối phức tạp)
    assert match_fast_command("tăng âm lượng video") is None


def test_non_volume_sentence_not_matched():
    assert match_fast_command("mở chrome giúp tôi") is None


def test_youtube_not_fast_pathed():
    # YouTube CỐ Ý không còn trong fast-path -> để router + LLM lo (không hijack bằng luật)
    assert match_fast_command("tìm clip trên YouTube về Luyện thi Toeic speaking") is None


def test_returns_fresh_args_each_call():
    a = match_fast_command("cuộn xuống")
    a[1]["direction"] = "up"                      # sửa bản trả về
    b = match_fast_command("cuộn xuống")
    assert b == ("scroll_screen", {"direction": "down"})   # không bị dính sửa


# --------------------------- fast-path điều khiển media --------------------------- #

def test_media_pause_variants():
    for t in ("tạm dừng video", "ngừng phát video trên YouTube", "dừng nhạc lại",
              "tạm ngưng clip"):
        assert match_fast_command(t) == ("browser_media_control", {"action": "pause"})


def test_media_play_variants():
    for t in ("tiếp tục phát video trên YouTube", "phát tiếp video", "chơi tiếp nhạc"):
        assert match_fast_command(t) == ("browser_media_control", {"action": "play"})


def test_media_next_prev():
    assert match_fast_command("bài tiếp theo trên youtube") == \
        ("browser_media_control", {"action": "next"})
    assert match_fast_command("video tiếp theo") == \
        ("browser_media_control", {"action": "next"})
    assert match_fast_command("quay lại bài trước") == \
        ("browser_media_control", {"action": "prev"})


def test_media_next_beats_play_when_both_present():
    # 'tiếp theo' (next) phải thắng 'tiếp tục/phát tiếp' (play) — không lẫn
    assert match_fast_command("chuyển bài tiếp theo trong video") == \
        ("browser_media_control", {"action": "next"})


def test_media_requires_context_word():
    # 'dừng lại' KHÔNG có ngữ cảnh media -> None (không cướp lệnh khác)
    assert match_fast_command("dừng lại đi") is None
    assert match_fast_command("tạm dừng") is None
    # 'phát video mới' (mở nội dung mới, không có cụm điều khiển) -> None, để LLM lo
    assert match_fast_command("mở video mèo trên youtube") is None


# --------------------------- match_avatar_command --------------------------- #

def test_avatar_smaller():
    for t in ("nhỏ hơn", "thu nhỏ", "làm nhỏ lại", "nho hon"):
        assert match_avatar_command(t) == {"scale_delta": -0.15}


def test_avatar_bigger():
    for t in ("to hơn", "phóng to", "lớn hơn"):
        assert match_avatar_command(t) == {"scale_delta": 0.15}


def test_avatar_dimmer():
    for t in ("mờ hơn", "làm mờ", "trong suốt hơn"):
        assert match_avatar_command(t) == {"opacity_delta": -0.15}


def test_avatar_clearer():
    for t in ("rõ hơn", "bớt mờ", "đậm hơn"):
        assert match_avatar_command(t) == {"opacity_delta": 0.15}


def test_avatar_none_for_other():
    for t in ("mở chrome", "cuộn xuống", ""):
        assert match_avatar_command(t) is None


# --------------------------- match_mode_command --------------------------- #

def test_mode_work_variants():
    for t in ("chuyển sang chế độ làm việc", "bật chế độ làm việc",
              "vào làm việc thôi", "bắt đầu làm việc", "chế độ công việc"):
        assert match_mode_command(t) == "work"


def test_mode_normal_variants():
    for t in ("về chế độ bình thường", "thoát chế độ làm việc",
              "tắt chế độ làm việc", "quay lại bình thường", "thôi làm việc"):
        assert match_mode_command(t) == "normal"


def test_mode_normal_beats_work_when_both_present():
    # "thoát chế độ làm việc" chứa cả "che do lam viec" -> phải ra 'normal', không 'work'
    assert match_mode_command("thoát chế độ làm việc") == "normal"


def test_mode_none_for_other():
    for t in ("mở chrome", "thời tiết hôm nay", "", None):
        assert match_mode_command(t) is None


# --------------------------- xác nhận có/không --------------------------- #

def test_confirmation_yes_variants():
    for t in ("có", "ừ", "được", "đồng ý", "ok", "vâng", "đúng rồi", "làm đi", "cứ làm"):
        assert match_confirmation(t) == "yes", t


def test_confirmation_no_variants():
    for t in ("không", "thôi", "hủy", "khỏi", "không cần", "thôi khỏi", "để sau", "bỏ đi"):
        assert match_confirmation(t) == "no", t


def test_confirmation_no_beats_yes_when_mixed():
    # Vừa có phủ định vừa có khẳng định -> ưu tiên huỷ cho an toàn
    assert match_confirmation("có nhưng thôi không cần đâu") == "no"


def test_confirmation_none_for_new_request():
    # Câu không phải xác nhận -> None (để coi là yêu cầu mới)
    for t in ("mở notepad", "phát nhạc trên youtube", "", None):
        assert match_confirmation(t) is None


def test_confirmation_long_co_sentence_not_yes():
    # "có" mở đầu câu DÀI không được nhận nhầm là đồng ý (an toàn)
    assert match_confirmation("có xem giúp tôi mấy giờ rồi") is None


# --------------------------- chỉnh tính cách bằng lời --------------------------- #

def test_persona_command_adjust_traits():
    assert match_persona_command("vui tính hơn đi")["trait"] == "humor"
    assert match_persona_command("vui tính hơn đi")["delta"] > 0
    assert match_persona_command("nghiêm túc hơn chút")["delta"] < 0
    assert match_persona_command("thân thiện hơn nhé")["trait"] == "warmth"
    assert match_persona_command("sôi nổi hơn")["trait"] == "energy"


def test_persona_command_reset():
    r = match_persona_command("reset tính cách")
    assert r["reset"] is True
    assert match_persona_command("về tính cách mặc định")["reset"] is True


def test_persona_command_none_for_other():
    for t in ("mở youtube", "thời tiết hôm nay", "", None):
        assert match_persona_command(t) is None


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
