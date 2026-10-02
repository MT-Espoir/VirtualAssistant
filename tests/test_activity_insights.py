import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from conftest import registry_with
from features.activity_insights import ActivityInsightsService
from features.activity_insights.prompt import CASE_ACTIVITY
from features.salm.models import AppDurations, DailyMetrics
from persistence import LocalDatabase
from ui.panels import activity_classification_blocks, activity_insights_blocks
from utils.events import AssistantBus


NOW = datetime(2030, 1, 10, 12, 0, tzinfo=timezone.utc)


def _daily(work=0, screen=0, rest=0, unknown=0, apps=None):
    metrics = DailyMetrics(work_engagement=work, screen_exposure=screen,
                           confirmed_break=rest, unknown_duration=unknown)
    for name, seconds in (apps or {}).items():
        metrics.apps[name] = AppDurations(
            running=seconds * 2, foreground=seconds, interactive=seconds)
    return metrics.to_dict()


def _service(tmp_path):
    database = LocalDatabase(tmp_path / "alice.db")
    service = ActivityInsightsService(database, now_provider=lambda: NOW)
    return database, service


def test_service_aggregates_interactive_not_running_and_keeps_full_app_name(tmp_path):
    database, service = _service(tmp_path)
    database.replace_salm_daily("2030-01-04", _daily(
        work=1800, screen=3600, rest=300, apps={"code": 1200}))
    database.replace_salm_daily("2030-01-10", _daily(
        work=2400, screen=4200, rest=600, unknown=60,
        apps={"code": 1800, "chatgpt": 900}))

    result = service.snapshot("7_days", "overview")

    assert result["range"] == {"start": "2030-01-04", "end": "2030-01-10"}
    assert result["totals"]["interactive_seconds"] == 3900
    assert result["totals"]["screen_exposure_seconds"] == 7800
    assert result["top_apps"] == [
        {"app_id": "code", "display_name": "Visual Studio Code",
         "interactive_seconds": 3000.0, "category": "unknown",
         "classifiable": True},
        {"app_id": "chatgpt", "display_name": "ChatGPT",
         "interactive_seconds": 900.0, "category": "unknown",
         "classifiable": True},
    ]
    assert result["data_quality"] == {
        "valid_days": 2, "partial_days": 1, "missing_days": 5,
        "coverage": 0.286, "unknown_seconds": 60.0,
        "classification_coverage": 0.0,
        "classification_eligible_seconds": 3900.0,
    }
    assert "workload_signal" not in result


def test_service_empty_and_invalid_contracts(tmp_path):
    _, service = _service(tmp_path)
    empty = service.snapshot("today", "apps")

    assert empty["data_quality"]["valid_days"] == 0
    assert empty["trend"] == [{
        "day": "2030-01-10", "interactive_seconds": 0.0,
        "has_data": False, "complete": False,
    }]
    assert json.loads(service.llm_result(empty))["status"] == "no_data"

    with pytest.raises(ValueError):
        service.snapshot("forever", "overview")
    with pytest.raises(ValueError):
        service.snapshot("today", "raw_events")


def test_llm_payload_is_capped_and_contains_no_raw_activity_fields(tmp_path):
    database, service = _service(tmp_path)
    database.replace_salm_daily("2030-01-10", _daily(
        apps={f"Full App Name {index}": 600 - index for index in range(6)}))

    payload = json.loads(service.llm_result(service.snapshot("today")))
    encoded = json.dumps(payload)

    assert len(payload["top_apps"]) == 5
    assert "classification_apps" not in payload
    assert "classifiable" not in encoded
    assert not any(key in encoded for key in (
        "window_title", "command_line", "clipboard", "raw_events"))
    assert "stress" not in encoded.lower() and "deadline" not in encoded.lower()


def test_activity_prompt_forbids_personality_overreach_and_category_guessing():
    assert "Không tự đoán category" in CASE_ACTIVITY
    assert "Không khen/chê chăm chỉ" in CASE_ACTIVITY
    assert "không khuyên sức khỏe" in CASE_ACTIVITY
    assert "không suy diễn stress, deadline" in CASE_ACTIVITY


def test_tool_is_read_only_emits_panel_snapshot_and_returns_aggregate(tmp_path):
    database, service = _service(tmp_path)
    database.replace_salm_daily("2030-01-10", _daily(
        screen=1200, apps={"code": 600}))
    bus = AssistantBus()
    registry = registry_with(activity_insights=service, bus=bus)
    before = database.counts().copy()

    output = registry.run("activity_insights", {"period": "today", "view": "apps"})

    assert database.counts() == before
    assert json.loads(output)["status"] == "ok"
    event = next(event for event in bus.drain() if event.activity is not None)
    assert event.activity["view"] == "apps"
    assert event.activity["top_apps"][0]["display_name"] == "Visual Studio Code"


def test_activity_event_deep_copies_nested_snapshot():
    bus = AssistantBus()
    snapshot = {"top_apps": [{"app_id": "Visual Studio Code"}]}
    bus.emit_activity(snapshot)
    snapshot["top_apps"][0]["app_id"] = "changed"
    assert bus.drain()[0].activity["top_apps"][0]["app_id"] == "Visual Studio Code"


def test_panel_builds_native_charts_without_workload_section(tmp_path):
    database, service = _service(tmp_path)
    database.replace_salm_daily("2030-01-10", _daily(
        work=1200, screen=1800, rest=300,
        apps={"code": 900, "chatgpt": 300}))

    blocks = activity_insights_blocks(service.snapshot("7_days"))
    kinds = [block[0] for block in blocks]

    assert "bar_chart" in kinds and "sparkline" in kinds and "badge" in kinds
    assert "Visual Studio Code" in str(blocks)
    assert "workload" not in str(blocks).lower()
    assert "stress" not in str(blocks).lower()


def test_classification_coverage_and_exclusion_are_applied_before_outputs(tmp_path):
    database, service = _service(tmp_path)
    database.replace_salm_daily("2030-01-10", _daily(
        apps={"code": 600, "chatgpt": 300, "python": 100}))
    service.set_app_preference("code", "work")
    service.set_app_preference("chatgpt", "communication", excluded=True)

    result = service.snapshot("today")
    payload = json.loads(service.llm_result(result))

    assert result["totals"]["interactive_seconds"] == 700
    assert [row["app_id"] for row in result["top_apps"]] == ["code", "python"]
    assert result["data_quality"]["classification_coverage"] == 1.0
    assert "chatgpt" not in json.dumps(payload)
    python_row = next(row for row in result["classification_apps"]
                      if row["app_id"] == "python")
    assert python_row["classifiable"] is False


def test_generic_host_cannot_be_classified_but_can_be_excluded(tmp_path):
    database, service = _service(tmp_path)
    database.replace_salm_daily("2030-01-10", _daily(apps={"python": 100}))

    with pytest.raises(ValueError):
        service.set_app_preference("python", "work")
    result = service.apply_setting("exclude", app_id="python")
    assert result["preference"]["excluded"] is True


def test_excluded_preference_remains_manageable_when_period_has_no_data(tmp_path):
    database, service = _service(tmp_path)
    database.replace_salm_daily("2029-12-01", _daily(apps={"code": 100}))
    service.set_app_preference("code", "work", excluded=True)

    snapshot = service.snapshot("today")
    blocks = activity_insights_blocks(snapshot)
    chooser = activity_classification_blocks(snapshot, "code")

    assert snapshot["data_quality"]["valid_days"] == 0
    assert "Visual Studio Code" in str(blocks)
    assert "Đưa lại vào thống kê" in str(chooser)
    assert {"action": "include", "app_id": "code"} in [
        block[2] for block in chooser if block[0] == "card"]


def test_activity_settings_tool_mutates_only_explicit_preference(tmp_path):
    from agent.tools import NeedsConfirmation

    database, service = _service(tmp_path)
    database.replace_salm_daily("2030-01-10", _daily(apps={"code": 600}))
    bus = AssistantBus()
    registry = registry_with(activity_insights=service, bus=bus)

    output = json.loads(registry.run("activity_insights", {
        "action": "classify", "app_id": "code", "category": "work"}))
    assert output["preference"]["category"] == "work"
    assert database.salm_app_preference("code")["source"] == "user"
    # Query vẫn là read-only trong ngữ cảnh đã đọc nội dung ngoài; action ghi thì bị gác.
    assert json.loads(registry.run(
        "activity_insights", {"action": "query"}, nhiem=True))["status"] == "ok"
    with pytest.raises(NeedsConfirmation):
        registry.run("activity_insights", {
            "action": "exclude", "app_id": "code"}, nhiem=True)
    with pytest.raises(NeedsConfirmation):
        registry.run("activity_insights", {"action": "clear_history"})


def test_confirmed_clear_history_keeps_app_preferences(tmp_path):
    database, service = _service(tmp_path)
    database.replace_salm_daily("2030-01-10", _daily(apps={"code": 600}))
    database.record_salm_event({
        "kind": "interval", "at": "2030-01-10T10:00:00+00:00"})
    service.set_app_preference("code", "work")
    registry = registry_with(activity_insights=service, bus=AssistantBus())

    output = json.loads(registry.run(
        "activity_insights", {"action": "clear_history"}, confirmed=True))

    assert output["removed"] == {"events": 1, "daily": 1}
    assert database.salm_app_preference("code")["category"] == "work"
    assert service.snapshot("today")["data_quality"]["valid_days"] == 0


def test_avatar_routes_activity_snapshot_to_shared_read_only_hud():
    from ui.avatar import AvatarWindow

    win = object.__new__(AvatarWindow)
    panel = MagicMock()
    win._panel = MagicMock(return_value=panel)
    payload = {
        "period": "today", "view": "overview",
        "range": {"start": "2030-01-10", "end": "2030-01-10"},
        "totals": {}, "top_apps": [], "trend": [],
        "data_quality": {"valid_days": 0},
    }

    win._show_activity(payload)

    win._panel.assert_called_once_with(
        "activity", "ACTIVITY INSIGHTS", win._activity_panel_pick)
    assert "Chưa có dữ liệu" in str(panel.show.call_args.args[0])


def test_avatar_routes_structured_classification_action_through_service_callback():
    from ui.avatar import AvatarWindow

    win = object.__new__(AvatarWindow)
    panel = MagicMock()
    win._panels = {"activity": panel}
    win._activity_payload = {"period": "7_days", "view": "apps"}
    updated = {"period": "7_days", "view": "apps", "data_quality": {}}
    win.on_activity_action = MagicMock(return_value=updated)
    win._show_activity = MagicMock()

    win._activity_panel_pick({
        "action": "classify", "app_id": "code", "category": "work"})

    win.on_activity_action.assert_called_once_with({
        "action": "classify", "app_id": "code", "category": "work",
        "period": "7_days", "view": "apps",
    })
    win._show_activity.assert_called_once_with(updated)
