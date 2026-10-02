"""Scale HUD là contract liên tục, độc lập nguồn input và avatar."""

import math
from unittest.mock import MagicMock

from ui.hud import HudPanel
from ui.avatar import AvatarWindow
from ui.scale import ContinuousScale
from utils.events import AssistantBus


def test_continuous_scale_keeps_fractional_values_and_clamps_boundaries():
    scale = ContinuousScale(value=1.0, minimum=0.65, maximum=1.80)
    assert scale.adjust(0.037) == 1.037
    assert scale.set(1.413) == 1.413
    assert scale.adjust(10) == 1.80
    assert scale.adjust(-10) == 0.65


def test_continuous_scale_ignores_invalid_sensor_values():
    scale = ContinuousScale(1.2)
    assert scale.set(float("nan")) == 1.2
    assert scale.adjust(math.inf) == 1.2
    assert scale.adjust("không phải số") == 1.2


def test_hud_panel_scales_geometry_without_creating_tk_window():
    panel = HudPanel(None, size=(430, 560), scale=1.137)
    assert panel.scale == 1.137
    assert panel.size == (489, 637)
    panel.nudge_scale(0.023)
    assert panel.scale == 1.16
    assert panel.size == (499, 650)


def test_bus_exposes_source_independent_hud_scale_contract():
    bus = AssistantBus()
    bus.emit_hud_scale(scale_delta=0.023, source="gesture")
    event = bus.drain()[0]
    assert event.ui == {"target": "hud", "scale_delta": 0.023, "source": "gesture"}


def test_panel_payload_sets_hud_as_conversation_surface():
    bus = AssistantBus()
    assert bus.current_ui_target() == "avatar"
    bus.emit_activity({"days": 7})
    assert bus.current_ui_target() == "hud"


def test_avatar_host_routes_hud_scale_to_all_panels_only():
    class Panel:
        def __init__(self):
            self.values = []

        def set_scale(self, value):
            self.values.append(value)

    host = object.__new__(AvatarWindow)
    host._hud_scale = ContinuousScale()
    host._panels = {"activity": Panel(), "mail": Panel()}
    AvatarWindow._apply_ui(host, {"target": "hud", "scale_delta": 0.037})
    assert host._hud_scale.value == 1.037
    assert all(panel.values == [1.037] for panel in host._panels.values())


def test_panel_created_later_inherits_current_hud_scale():
    host = object.__new__(AvatarWindow)
    host.root = None
    host._panels = {}
    host._hud_scale = ContinuousScale(1.273)
    panel = AvatarWindow._panel(host, "activity", "ACTIVITY", None)
    assert panel.scale == 1.273


def test_real_panel_visibility_updates_and_clears_hud_context():
    host = object.__new__(AvatarWindow)
    host.bus = AssistantBus()
    host._visible_panels = set()
    AvatarWindow._panel_visibility(host, "activity", True)
    assert host.bus.current_ui_target() == "hud"
    AvatarWindow._panel_visibility(host, "mail", True)
    AvatarWindow._panel_visibility(host, "activity", False)
    assert host.bus.current_ui_target() == "hud"
    AvatarWindow._panel_visibility(host, "mail", False)
    assert host.bus.current_ui_target() == "avatar"


def test_dispatch_routes_explicit_hud_command_before_generic_avatar_rule():
    import app

    bus = AssistantBus()
    agent = MagicMock()
    agent.registry.has.return_value = False
    response, _emotion = app._dispatch(
        agent, "phóng to HUD", bus, fast_match=lambda _text: None)
    ui_events = [event.ui for event in bus.drain() if event.ui is not None]
    assert ui_events == [{"target": "hud", "scale_delta": 0.10}]
    assert response == "Đã phóng to bảng thông tin."
    agent.run.assert_not_called()


def test_dispatch_uses_recent_panel_context_for_ambiguous_follow_up():
    import app

    bus = AssistantBus()
    bus.emit_activity({"days": 7})
    agent = MagicMock()
    agent.registry.has.return_value = False
    response, _emotion = app._dispatch(
        agent, "phóng to nói lên", bus, fast_match=lambda _text: None)
    ui_events = [event.ui for event in bus.drain() if event.ui is not None]
    assert ui_events == [{"target": "hud", "scale_delta": 0.10}]
    assert response == "Đã phóng to bảng thông tin."
    agent.run.assert_not_called()


def test_explicit_avatar_target_overrides_recent_panel_context():
    import app

    bus = AssistantBus()
    bus.emit_activity({"days": 7})
    agent = MagicMock()
    agent.registry.has.return_value = False
    response, _emotion = app._dispatch(
        agent, "phóng to nhân vật", bus, fast_match=lambda _text: None)
    ui_events = [event.ui for event in bus.drain() if event.ui is not None]
    assert ui_events == [{"scale_delta": 0.15}]
    assert response == "Đã phóng to avatar."
