import json

from features.salm.windows import normalize_app_id
from services.browser_bridge import BrowserBridge


def test_app_id_normalization_never_keeps_path():
    assert normalize_app_id(r"C:\\Program Files\\VideoLAN\\VLC\\vlc.exe") == "vlc"
    assert normalize_app_id("ms-teams.exe") == "ms-teams"
    assert normalize_app_id("Code - Insiders.exe") == "code"


def test_browser_bridge_ignores_unsolicited_meeting_state_without_data_permission():
    bridge = BrowserBridge()
    trusted_socket = object()
    bridge._client = trusted_socket
    bridge._on_message(json.dumps({"type": "MEETING_STATE", "meeting_tab_open": True}), trusted_socket)
    assert bridge.meeting_open is None
    bridge._on_message(json.dumps({"type": "MEETING_STATE", "meeting_tab_open": "yes",
                                   "url": "https://meet.google.com/private"}), trusted_socket)
    assert bridge.meeting_open is None
