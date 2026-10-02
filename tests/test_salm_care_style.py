import json

from features.salm.care_style import (DEFAULT_CARE_STYLE, CareStyleStore,
                                      match_care_style_command)
from features.salm.policy import PolicyDecision
from features.salm.runtime import SalmRuntime
from ui.panels import care_style_blocks
from utils.events import AssistantBus


def test_matcher_requires_explicit_care_scope_and_supports_multiple_changes():
    assert match_care_style_command("hãy nói ngắn gọn hơn") is None
    command = match_care_style_command(
        "Nhắc nghỉ ngắn gọn hơn, nhẹ nhàng hơn và đa dạng hơn")
    assert command == {"action": "update", "changes": {
        "length": "concise", "directness": "gentle", "variation": "high"}}


def test_matcher_fails_closed_on_conflict_and_supports_show_reset():
    assert match_care_style_command(
        "nhắc nghỉ nhẹ nhàng hơn nhưng nói thẳng hơn") is None
    assert match_care_style_command("xem cài đặt nhắc nghỉ")["action"] == "show"
    assert match_care_style_command("đặt lại phong cách nhắc nghỉ")["action"] == "reset"


def test_store_persists_only_strict_enum_schema_and_reset_removes_file(tmp_path):
    path = tmp_path / "care-style.json"
    store = CareStyleStore(path)
    assert store.update({"length": "concise", "variation": "high"})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {**DEFAULT_CARE_STYLE, "length": "concise", "variation": "high"}
    assert not any(key in saved for key in ("utterance", "threshold", "activity", "app"))
    assert CareStyleStore(path).snapshot() == saved

    store.reset()
    assert store.snapshot() == DEFAULT_CARE_STYLE
    assert not path.exists()


def test_store_rejects_unknown_or_invalid_persisted_fields(tmp_path):
    path = tmp_path / "care-style.json"
    path.write_text(json.dumps({**DEFAULT_CARE_STYLE, "raw": "bí mật"}),
                    encoding="utf-8")
    assert CareStyleStore(path).snapshot() == DEFAULT_CARE_STYLE
    path.write_text("{broken", encoding="utf-8")
    assert CareStyleStore(path).snapshot() == DEFAULT_CARE_STYLE


def test_runtime_updates_emits_and_never_copies_address_into_store(tmp_path):
    emitted = []
    runtime = SalmRuntime(
        tmp_path, care_style_enabled=True, on_care_style=emitted.append,
        address_form_provider=lambda: "cậu chủ")

    reply = runtime.try_style_command("nhắc nghỉ ngắn gọn hơn và ít gọi tôi")

    assert "ngắn gọn hơn" in reply
    assert emitted[-1]["address_form"] == "cậu chủ"
    assert emitted[-1]["length"] == "concise"
    saved = json.loads((tmp_path / "care-style.json").read_text(encoding="utf-8"))
    assert "address_form" not in saved
    assert runtime.try_style_command("hãy nói trực tiếp hơn") is None


def test_style_command_inside_active_checkin_does_not_close_or_snooze(tmp_path):
    runtime = SalmRuntime(tmp_path, gentle_checkin=True, care_style_enabled=True)
    decision = PolicyDecision(
        "dispatch", "work_engagement:soft:4", "work_engagement", "soft", None,
        ("natural_pause",))
    runtime.checkins.arm(decision, cycle_id=4, now=100)

    reply = runtime.try_care_response("nhắc nghỉ trực tiếp hơn", now=101)

    assert "trực tiếp hơn" in reply
    assert runtime.checkins.active(101) is not None


def test_disabled_runtime_does_not_intercept_style_commands(tmp_path):
    runtime = SalmRuntime(tmp_path, care_style_enabled=False)
    assert runtime.try_style_command("nhắc nghỉ ngắn hơn") is None


def test_hud_blocks_and_bus_snapshot_are_safe():
    payload = {**DEFAULT_CARE_STYLE, "address_form": "cậu chủ"}
    blocks = care_style_blocks(payload)
    assert "cậu chủ" in str(blocks)
    assert ("buttons", [("ĐẶT LẠI", "reset", "off")]) in blocks
    assert "ngưỡng sức khỏe" in str(blocks)

    bus = AssistantBus()
    bus.emit_care_style(payload)
    payload["length"] = "concise"
    assert bus.drain()[0].care_style["length"] == "balanced"


def test_avatar_routes_style_snapshot_to_shared_hud_without_real_tk():
    from unittest.mock import MagicMock
    from ui.avatar import AvatarWindow

    win = object.__new__(AvatarWindow)
    win.on_care_style_action = MagicMock()
    panel = MagicMock()
    win._panel = MagicMock(return_value=panel)
    payload = {**DEFAULT_CARE_STYLE, "address_form": "cậu chủ"}

    win._show_care_style(payload)

    win._panel.assert_called_once_with(
        "care_style", "PHONG CÁCH NHẮC NGHỈ", win.on_care_style_action)
    assert "cậu chủ" in str(panel.show.call_args.args[0])
