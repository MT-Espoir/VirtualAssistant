import json

from features.salm.windows import normalize_app_id
from services.browser_bridge import BrowserBridge


def test_app_id_normalization_never_keeps_path():
    assert normalize_app_id(r"C:\\Program Files\\VideoLAN\\VLC\\vlc.exe") == "vlc"
    assert normalize_app_id("ms-teams.exe") == "ms-teams"
    assert normalize_app_id("Code - Insiders.exe") == "code"


def test_browser_bridge_accepts_only_boolean_meeting_state():
    bridge = BrowserBridge()
    bridge._on_message(json.dumps({"type": "MEETING_STATE", "meeting_tab_open": True}))
    assert bridge.meeting_open is True
    bridge._on_message(json.dumps({"type": "MEETING_STATE", "meeting_tab_open": "yes",
                                   "url": "https://meet.google.com/private"}))
    assert bridge.meeting_open is True
