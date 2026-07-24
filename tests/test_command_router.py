"""
Unit test cho CommandRouter.

Router được thiết kế tách khỏi I/O nên ở đây ta tiêm toàn bộ phụ thuộc bằng
mock: không mở app thật, không đổi âm lượng, không cần micro. Chỉ kiểm tra
"text vào -> định tuyến đúng action / trả về đúng response".
"""

from unittest.mock import MagicMock

try:
    import pytest
except ImportError:  # cho phép chạy thủ công khi chưa cài pytest
    pytest = None

from core.command_router import CommandRouter

CONVERSATION_INTENTS = {"greeting", "goodbye", "small_talk", "conversation",
                        "question_answering", "help"}


def make_router(intent_map, entities=None, entity_value="chrome"):
    """Tạo router với NLP/hội thoại/actions giả.

    intent_map: dict text(lowercase) -> intent trả về từ classify_intent.
    """
    nlp = MagicMock()
    nlp.classify_intent.side_effect = lambda t: intent_map.get(t, "unknown")
    nlp.extract_entities.return_value = entities or {}

    conversation = MagicMock()
    conversation.is_conversation_intent.side_effect = lambda i: i in CONVERSATION_INTENTS
    conversation.generate_response.return_value = "PHẢN_HỒI_HỘI_THOẠI"

    actions = MagicMock()
    # Cho action trả về chuỗi để dễ khẳng định
    actions.control_volume.return_value = "VOL"
    actions.control_brightness.return_value = "BRI"
    actions.system_shutdown.return_value = "SHUTDOWN"
    actions.system_restart.return_value = "RESTART"
    actions.search_web.return_value = "WEB"
    actions.search_and_play_youtube_direct.return_value = "YT_DIRECT"
    actions.search_and_play_youtube.return_value = "YT_FALLBACK"
    actions.search_on_specific_site.return_value = "SITE"
    actions.open_website.return_value = "SITE_OPEN"

    extract_entity = MagicMock(return_value=entity_value)

    router = CommandRouter(
        nlp_processor=nlp,
        conversation_engine=conversation,
        actions=actions,
        user_profile=None,
        extract_entity=extract_entity,
    )
    return router, actions, conversation


# --------------------------- Lệnh hệ thống --------------------------- #

def test_open_app():
    router, actions, _ = make_router({"mở chrome": "open_app"})
    resp = router.route("mở chrome")
    actions.open_application.assert_called_once_with("chrome")
    assert resp == "Opening chrome"


def test_volume_up_with_percent():
    router, actions, _ = make_router({"tăng âm lượng 20%": "system_volume"})
    router.route("tăng âm lượng 20%")
    actions.control_volume.assert_called_once_with(change=20)


def test_volume_down_default():
    router, actions, _ = make_router({"giảm âm lượng": "system_volume"})
    router.route("giảm âm lượng")
    actions.control_volume.assert_called_once_with(change=-10)


def test_volume_set_level_only_percent():
    router, actions, _ = make_router({"âm lượng 50%": "system_volume"})
    router.route("âm lượng 50%")
    actions.control_volume.assert_called_once_with(level=50)


def test_brightness_up():
    router, actions, _ = make_router({"tăng độ sáng": "system_brightness"})
    router.route("tăng độ sáng")
    actions.control_brightness.assert_called_once_with(change=10)


def test_shutdown_immediate():
    router, actions, _ = make_router({"tắt máy ngay lập tức": "system_shutdown"})
    router.route("tắt máy ngay lập tức")
    actions.system_shutdown.assert_called_once_with(close_apps=False)


def test_shutdown_default_closes_apps():
    router, actions, _ = make_router({"tắt máy": "system_shutdown"})
    router.route("tắt máy")
    actions.system_shutdown.assert_called_once_with(close_apps=True)


# --------------------------- Web / YouTube --------------------------- #

def test_web_search_engine_google():
    router, actions, _ = make_router({"tìm mèo con": "web_search"})
    router.route("tìm mèo con")
    args, kwargs = actions.search_web.call_args
    assert args[1] == "google"  # engine mặc định


def test_youtube_uses_direct_first():
    router, actions, _ = make_router({"phát nhạc sơn tùng youtube": "youtube_search"})
    resp = router.route("phát nhạc sơn tùng youtube")
    actions.search_and_play_youtube_direct.assert_called_once()
    assert resp == "YT_DIRECT"


def test_youtube_falls_back_on_error():
    router, actions, _ = make_router({"phát nhạc sơn tùng youtube": "youtube_search"})
    actions.search_and_play_youtube_direct.side_effect = RuntimeError("pytube lỗi")
    resp = router.route("phát nhạc sơn tùng youtube")
    actions.search_and_play_youtube.assert_called_once()
    assert resp == "YT_FALLBACK"


def test_search_on_site_alias_expanded():
    router, actions, _ = make_router(
        {"tìm mèo trên fb": "search_on_site"},
        entities={"site": "fb", "query": "mèo"},
    )
    router.route("tìm mèo trên fb")
    actions.search_on_specific_site.assert_called_once_with("mèo", "facebook")


# --------------------------- Hội thoại --------------------------- #

def test_greeting_goes_to_conversation_and_enables_mode():
    router, _, conversation = make_router({"xin chào": "greeting"})
    resp = router.route("xin chào")
    assert resp == "PHẢN_HỒI_HỘI_THOẠI"
    conversation.set_conversation_mode.assert_called_once_with(True)


def test_goodbye_disables_mode():
    router, _, conversation = make_router({"tạm biệt": "goodbye"})
    router.route("tạm biệt")
    conversation.set_conversation_mode.assert_called_once_with(False)


def test_unknown_falls_back_to_conversation():
    router, _, conversation = make_router({"blah blah": "unknown"})
    resp = router.route("blah blah")
    conversation.generate_response.assert_called_with("blah blah", "unknown")
    assert resp == "PHẢN_HỒI_HỘI_THOẠI"


# --------------------------- Đa lệnh --------------------------- #

def test_route_multi_two_commands():
    router, actions, _ = make_router({
        "mở chrome": "open_app",
        "tăng âm lượng": "system_volume",
    })
    resp = router.route_multi("mở chrome và tăng âm lượng")
    actions.open_application.assert_called_once_with("chrome")
    actions.control_volume.assert_called_once_with(change=10)
    assert "Lệnh 1" in resp and "Lệnh 2" in resp


def test_route_multi_single_command_no_prefix():
    router, actions, _ = make_router({"mở chrome": "open_app"})
    resp = router.route_multi("mở chrome")
    assert resp == "Opening chrome"  # không thêm tiền tố "Lệnh 1"


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))

    # Fallback: chạy thủ công khi chưa cài pytest
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
