import ast
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.tools import ActionRefused, Tool, ToolRegistry
from services.control_panel import FLAG_GROUPS, LIVE, SystemControls, validate_threshold
from ui.control_panel import control_blocks
from utils.control_settings import ControlSettings
from utils.events import AssistantBus
from voice.fast_commands import match_control_panel_command


def test_every_boolean_config_and_catalog_feature_has_a_control(tmp_path):
    from features.catalog import FEATURES
    from features.contract import LoadReport
    tree = ast.parse(Path("src/utils/config.py").read_text(encoding="utf-8"))
    flags = {n.args[0].value for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_get_bool"}
    panel_flags = {key for group in FLAG_GROUPS.values() for key in group}
    assert flags <= panel_flags
    service = SystemControls(LoadReport(), store=ControlSettings(tmp_path / "settings.json"))
    keys = {row["key"] for row in service.snapshot()["rows"]}
    assert {"feature." + f.name for f in FEATURES} <= keys


def test_settings_merge_across_independent_process_stores_and_reload(tmp_path):
    a = ControlSettings(tmp_path / "settings.json")
    b = ControlSettings(tmp_path / "settings.json")
    a.update({"CAMERA_ENABLED": False})
    b.update({"IOT_AUTOMATION_ENABLED": True})
    assert a.values() == b.values() == {"CAMERA_ENABLED": False, "IOT_AUTOMATION_ENABLED": True}
    assert json.loads(a.path.read_text())["version"] == 1


def test_saved_controls_override_env_in_desktop_and_gateway(tmp_path, monkeypatch):
    from utils import control_settings
    from utils.config import _get_bool
    from features.iot.settings import IoTSettings
    store = ControlSettings(tmp_path / "settings.json")
    monkeypatch.setattr(control_settings, "controls", store)
    monkeypatch.setenv("IOT_AUTOMATION_ENABLED", "false")
    monkeypatch.setenv("CAMERA_ENABLED", "true")
    store.update({"IOT_AUTOMATION_ENABLED": True, "CAMERA_ENABLED": False,
                  "IOT_AUTO_ON_TEMPERATURE_C": 33.5})
    assert _get_bool("CAMERA_ENABLED", True) is False
    cfg = IoTSettings.from_env()
    assert cfg.automation_enabled is True
    assert cfg.auto_on_temperature_c == 33.5


@pytest.mark.parametrize("text,action", [
    ("Alice mở bảng điều khiển", "show"), ("bảng chức năng", "show"),
    ("hiển thị bảng cài đặt", "show"), ("đóng bảng điều khiển", "hide"),
    ("tắt bảng chức năng", "hide"), ("control panel", "show"),
    ("bảng điều khiển là gì", None), ("đừng mở bảng điều khiển", None),
    ("mở bảng điều khiển rồi tắt máy", None),
])
def test_voice_panel_commands_are_narrow(text, action):
    assert match_control_panel_command(text) == action


def test_registry_blocks_disabled_feature_on_all_paths():
    reg = ToolRegistry()
    handler = MagicMock(return_value="ok")
    reg.register(Tool("example", "example", {}, handler, group="iot"))
    enabled = [True]
    reg.set_feature_gate(lambda group: enabled[0])
    assert reg.specs()
    enabled[0] = False
    assert reg.specs() == []
    with pytest.raises(ActionRefused):
        reg.run("example", {}, confirmed=True, tu_dong=True)
    handler.assert_not_called()
    enabled[0] = True
    assert reg.run("example", {}) == "ok"


def test_restart_pending_and_live_controls_are_not_confused(tmp_path, monkeypatch):
    from features.contract import LoadReport
    from utils.config import config
    monkeypatch.setattr(config, "FAST_COMMANDS", True)
    service = SystemControls(LoadReport(), store=ControlSettings(tmp_path / "settings.json"))
    current = service.boot["SALM_ENABLED"]
    snap = service.set("SALM_ENABLED", not current)
    assert snap["restart_required"]
    assert next(row for row in snap["rows"] if row["key"] == "SALM_ENABLED")["pending"]
    service.set("SALM_ENABLED", current)
    snap = service.set("FAST_COMMANDS", False)
    assert not snap["restart_required"]
    assert config.FAST_COMMANDS is False
    with pytest.raises(ValueError):
        service.set("not-a-feature", True)
    with pytest.raises(ValueError):
        service.set("FAST_COMMANDS", "false")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "32.5", 15, 51])
def test_threshold_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        validate_threshold(value)


def test_panel_is_in_main_bus_and_uses_shared_hud_blocks(tmp_path):
    from features.contract import LoadReport
    bus = AssistantBus()
    bus.emit_control("show")
    assert bus.drain()[0].control == {"action": "show"}
    service = SystemControls(LoadReport(), store=ControlSettings(tmp_path / "settings.json"))
    snapshot = service.set_threshold(32.5)
    blocks = control_blocks(snapshot)
    assert any(block[0] == "toggle" for block in blocks)
    assert any(block[0] == "field" and block[2] == "32.5 °C" for block in blocks)


def test_dispatch_panel_does_not_need_llm_or_fast_commands(monkeypatch):
    from app import _dispatch
    from utils.config import config
    monkeypatch.setattr(config, "FAST_COMMANDS", False)
    agent = MagicMock()
    bus = AssistantBus()
    reply, _ = _dispatch(agent, "mở bảng điều khiển", bus)
    assert "Đã mở" in reply
    agent.run.assert_not_called()
    assert bus.drain()[0].control["action"] == "show"


def test_disabled_gesture_does_not_load_model_or_spin(monkeypatch):
    import sys
    from types import SimpleNamespace
    from features.camera.service import CameraService
    factory = MagicMock()
    monkeypatch.setitem(sys.modules, "features.camera.gesture", SimpleNamespace(
        PROVIDER="fixture", GestureDebouncer=MagicMock(), HandGestureEngine=factory))
    camera = CameraService(None, template_store=MagicMock())
    camera.set_gesture_enabled(False)
    stopped = [False]
    waits = []
    def wait(seconds):
        waits.append(seconds)
        stopped[0] = True
    camera._stop = SimpleNamespace(is_set=lambda: stopped[0], wait=wait)
    camera._gesture_loop()
    factory.assert_not_called()
    assert waits == [0.25]
