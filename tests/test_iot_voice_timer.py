"""A/C timer commands must reach the gateway before acknowledging success."""

from unittest.mock import MagicMock
from types import SimpleNamespace

from agent.agent import Agent
from features.iot.fast import describe_ac_off_timer_result, match_ac_off_timer
from features import fast as feature_fast
from llm.client import AssistantTurn, ToolCall

from conftest import full_report, registry_with


def test_direct_timer_variants():
    for text in ("30 phút sau tắt máy lạnh", "tắt điều hòa sau 30 phút",
                 "sau 30 phút hãy tắt máy lạnh", "hẹn giờ tắt máy lạnh 30 phút"):
        expected = ("control_room_ac", {"action": "schedule_off", "timer_minutes": 30})
        assert match_ac_off_timer(text) == expected
        assert feature_fast.match(text, full_report()) == expected


def test_direct_timer_avoids_ambiguous_or_invalid_requests():
    for text in ("30 phút sau tắt máy lạnh rồi mở đèn", "nhắc tôi tắt máy lạnh sau 30 phút",
                 "30 phút sau tắt máy lạnh ở phòng khách", "0 phút sau tắt máy lạnh",
                 "1441 phút sau tắt máy lạnh", "tắt máy lạnh ngay"):
        assert match_ac_off_timer(text) is None


def test_timer_result_requires_gateway_confirmation():
    assert "Đã đặt lịch" in describe_ac_off_timer_result(
        '{"status":"scheduled","run_until_local":"2026-09-26T18:30:00+07:00"}')
    for raw in ('{"status":"error","message":"gateway unavailable"}',
                '{"status":"scheduled"}', "bad json"):
        assert "Đã đặt lịch" not in describe_ac_off_timer_result(raw)


def test_fast_timer_calls_iot_gateway_before_responding():
    from app import _run_fast

    client = MagicMock()
    client.status.return_value = {"devices": [
        {"room_id": "bedroom", "capabilities": ["climate.power"]}]}
    client.command.return_value = {
        "status": "scheduled", "run_until": "2026-09-26T11:30:00+00:00"}
    agent = SimpleNamespace(registry=registry_with(iot=client))
    reply = _run_fast(agent, match_ac_off_timer("30 phút sau tắt máy lạnh"))
    client.command.assert_called_once_with("bedroom", "schedule_off", 30, None, None)
    assert "Đã đặt lịch tắt máy lạnh" in reply


def test_agent_rejects_llm_timer_claim_without_tool_call():
    llm = MagicMock()
    llm.generate.return_value = AssistantTurn(text="Em đã đặt hẹn 30 phút nữa tắt máy lạnh.")
    agent = Agent(llm, registry_with(actions=MagicMock()))
    reply = agent.run("30 phút sau tắt máy lạnh")
    assert "chưa đặt được" in reply.text
    assert "đã đặt" not in reply.text.lower()


def test_temperature_rule_is_saved_before_acknowledging():
    from app import _run_fast
    from features.iot.fast import match_ac_automation
    client = MagicMock()
    client.configure_automation.return_value = {"status": "saved", "policy": {
        "automation_enabled": True, "threshold_c": 32.5}}
    request = "Alice khi nhiệt độ tăng lên trên 32,5 độ C thì em hãy bật máy lạnh"
    hit = match_ac_automation(request)
    assert hit == ("configure_climate_automation", {"enabled": True, "threshold_c": 32.5})
    agent = SimpleNamespace(registry=registry_with(iot=client))
    reply = _run_fast(agent, hit)
    client.configure_automation.assert_called_once_with(True, 32.5)
    assert "Đã lưu" in reply and "20 phút" in reply
    client.configure_automation.side_effect = RuntimeError("offline")
    assert "chưa lưu" in _run_fast(agent, hit)


def test_agent_rejects_temperature_rule_promise_without_tool():
    llm = MagicMock()
    llm.generate.return_value = AssistantTurn(text="Em sẽ bật ngay khi vượt 32,5 độ C.")
    agent = Agent(llm, registry_with(actions=MagicMock()))
    reply = agent.run("khi nhiệt độ tăng lên trên 32,5 độ C thì em hãy bật máy lạnh")
    assert "chưa lưu" in reply.text


def test_automation_matcher_does_not_capture_questions_negation_or_compound_actions():
    from features.iot.fast import match_ac_automation
    for text in ("đừng bật máy lạnh khi nhiệt độ trên 32.5 độ", "nhiệt độ trên 32.5 độ có nên bật máy lạnh",
                 "khi nhiệt độ trên 32.5 độ thì bật máy lạnh rồi mở đèn"):
        assert match_ac_automation(text) is None


def test_on_duration_variants():
    for text, minutes in (("Alice mở máy lạnh trong một tiếng", 60),
                          ("bật điều hòa trong vòng 2 giờ", 120),
                          ("mở máy lạnh nửa tiếng", 30),
                          ("bật máy lạnh trong 45 phút", 45)):
        expected = ("control_room_ac", {"action": "on", "timer_minutes": minutes})
        assert match_ac_off_timer(text) == expected
        assert feature_fast.match(text, full_report()) == expected
    for text in ("mở máy lạnh trong một tiếng rồi mở đèn", "mở máy lạnh trong 25 giờ",
                 "mở máy lạnh trong một tiếng ở phòng khách"):
        assert match_ac_off_timer(text) is None


def test_confirmed_on_keeps_duration_and_speaks_summary(monkeypatch):
    monkeypatch.setattr("features.iot.tools.time.sleep", lambda _: None)
    client = MagicMock()
    client.status.return_value = {"devices": [
        {"room_id": "bedroom", "capabilities": ["climate.power"]}]}
    client.command.return_value = {"request_id": "request", "status": "queued_for_mqtt",
                                   "run_until": "2026-09-28T08:26:53+00:00"}
    client.command_status.return_value = {"status": "node_result_ok_uncorrelated"}
    llm = MagicMock()
    llm.generate.return_value = AssistantTurn(tool_calls=[
        ToolCall("call", "control_room_ac", {"action": "on"})])
    agent = Agent(llm, registry_with(iot=client))
    agent._nhiem = 2  # previous external content survives the decay at turn start
    question = agent.run("Alice mở máy lạnh trong một tiếng")
    assert agent.pending["arguments"]["timer_minutes"] == 60
    assert "60 phút" in question.text
    assert "control_room_ac" not in question.text
    client.command.assert_not_called()
    reply = agent.run("có")
    client.command.assert_called_once_with("bedroom", "on", 60, None, None)
    assert "Đã đặt lịch tắt máy lạnh" in reply.text
    assert "request_id" not in reply.text
    assert "node_result" not in reply.text


def test_current_metric_does_not_query_history():
    import json
    from features.iot.tools import _environment

    client = MagicMock()
    reading = {"value": 32.55, "quality": "stale", "received_at": "2026-09-28T07:25:20+00:00"}
    client.status.return_value = {"rooms": [{"room_id": "bedroom",
        "measurements": {"temperature_c": reading}, "automation": {}}],
        "devices": [], "broker_connected": True}
    result = json.loads(_environment(client, metric="temperature_c"))
    assert result["requested_measurement"] == reading
    client.history.assert_not_called()
    client.history.return_value = {"samples": []}
    _environment(client, metric="temperature_c", hours=24)
    client.history.assert_called_once_with("bedroom", "temperature_c", 24)
