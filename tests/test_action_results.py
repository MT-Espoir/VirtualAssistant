"""Hợp đồng kết quả R1.2: `ActionResult`, phân loại ở `ToolRegistry.run_result`, và
mapping của browser/IoT/MCP. Xem `docs/alice_result_contract_spec.md` §3–§7."""

import json
import socket
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from agent.results import ActionResult, RemoteError
from agent.tools import ActionRefused, Tool, ToolRegistry
from features.browser.tools import _register_browser_tools
from features.iot.fast import describe_ac_result
from features.iot.tools import register as register_iot
from services.mcp_bridge import MCPClient, MCPError


def _registry(handler, **tool_options):
    reg = ToolRegistry()
    reg.register(Tool("fixture", "fixture", {"type": "object", "properties": {}},
                      handler, **tool_options))
    return reg


# --------------------------- ActionResult --------------------------- #

@pytest.mark.parametrize("field", ["status", "reason", "layer"])
def test_action_result_rejects_values_outside_contract(field):
    values = {"status": "verified", "reason": "ok", "layer": "local", field: "made_up"}
    with pytest.raises(ValueError):
        ActionResult("x", name="t", **values)


def test_action_result_is_a_string_for_existing_callers():
    result = ActionResult('{"status":"ir_sent"}', name="t", status="dispatched",
                          reason="accepted_unverified", layer="node")
    assert result == '{"status":"ir_sent"}' and json.loads(result)["status"] == "ir_sent"
    assert result.render == str(result) and not result.is_error
    assert result.for_llm() == '{"status":"ir_sent"}\n[kết quả: dispatched/accepted_unverified]'


def test_legacy_result_keeps_old_behaviour_without_status_line():
    result = ActionResult("Đã bật.", name="t", status="unknown",
                          reason="legacy_unclassified", layer="local", legacy=True)
    assert not result.is_error and result.for_llm() == "Đã bật."


def test_tool_rejects_unknown_evidence_policy():
    with pytest.raises(ValueError):
        Tool("t", "t", {}, lambda: "", evidence_policy="trust_me")


# --------------------------- ToolRegistry.run_result --------------------------- #

def test_undeclared_string_tool_is_legacy_unknown():
    result = _registry(lambda: "Đã làm.").run_result("fixture", {})
    assert (result.status, result.reason, result.legacy) == ("unknown", "legacy_unclassified", True)


def test_declared_read_string_tool_is_verified():
    result = _registry(lambda: "26 độ", evidence_policy="read").run_result("fixture", {})
    assert (result.status, result.reason, result.legacy) == ("verified", "ok", False)


def test_dispatch_only_tool_cannot_claim_verified():
    def claims_verified():
        return ActionResult("Đã tắt.", name="fixture", status="verified", reason="ok",
                            layer="node")
    result = _registry(claims_verified, evidence_policy="dispatch_only").run_result("fixture", {})
    assert (result.status, result.reason, result.layer) == ("dispatched", "accepted_unverified", "node")


def test_exception_and_refusal_become_failed_and_refused():
    def boom():
        raise RuntimeError("fixture")
    failed = _registry(boom).run_result("fixture", {})
    assert (failed.status, failed.reason) == ("failed", "handler_exception") and failed.is_error
    refused = _registry(lambda: "x", cam=lambda **_: "bị cấm").run_result("fixture", {})
    assert (refused.status, refused.reason) == ("refused", "policy_refused") and refused.is_error


def test_remote_error_keeps_unknown_when_side_effect_may_have_happened():
    def timeout_after_send():
        raise RemoteError("timeout", status="unknown", reason="transport_error", layer="mcp")
    result = _registry(timeout_after_send).run_result("fixture", {})
    assert (result.status, result.layer, result.side_effect_possible) == ("unknown", "mcp", True)


def test_unknown_tool_still_raises_key_error():
    with pytest.raises(KeyError):
        ToolRegistry().run_result("missing", {})


def test_handler_key_error_is_not_reported_as_missing_tool():
    """Audit: KeyError bên trong handler từng bị Agent báo là 'không có công cụ'."""
    from agent.agent import Agent
    from llm.client import AssistantTurn, ToolCall

    class LLM:
        def __init__(self):
            self.turns = iter([AssistantTurn(tool_calls=[ToolCall("c", "fixture", {})]),
                               AssistantTurn(text="Xin lỗi.")])
            self.results = []

        def generate(self, **kwargs):
            self.results.extend(r for m in kwargs["messages"] for r in m.tool_results)
            return next(self.turns)

    def broken():
        return {}["missing_key"]
    llm = LLM()
    Agent(llm, _registry(broken)).run("chạy fixture")
    assert llm.results[0].is_error
    assert llm.results[0].content.endswith("[kết quả: failed/handler_exception]")
    assert "Không có công cụ" not in llm.results[0].content


# --------------------------- browser --------------------------- #

class _Bridge:
    connection_id = "fixture-connection"

    def __init__(self, response):
        self.response = response

    def send_command(self, **_):
        return self.response


def _browser(response, name, args):
    reg = ToolRegistry()
    _register_browser_tools(reg, _Bridge(response))
    return reg.run_result(name, args)


@pytest.mark.parametrize("response,status,reason,layer", [
    ({"type": "STATUS", "success": True}, "dispatched", "accepted_unverified", "extension"),
    ({"type": "ERROR", "reason": "no_client", "outcome": "failed"}, "failed", "no_client", "bridge"),
    ({"type": "ERROR", "reason": "transport_error", "outcome": "unknown"}, "unknown", "transport_error", "bridge"),
    ({"type": "ERROR", "reason": "connection_changed"}, "not_attempted", "connection_changed", "bridge"),
    ({"type": "ERROR", "reason": "data_scope_not_authorized"}, "refused", "data_scope_not_authorized", "bridge"),
    ({"type": "ERROR", "message": "No controllable media element found."}, "failed", "target_not_found", "extension"),
    ({"type": "ERROR", "message": "Media injection failed."}, "failed", "remote_error", "extension"),
    (None, "unknown", "unexpected_response", "bridge"),
])
def test_media_control_maps_bridge_response(response, status, reason, layer):
    result = _browser(response, "browser_media_control", {"action": "pause"})
    assert (result.status, result.reason, result.layer) == (status, reason, layer)


def test_media_control_invalid_arguments_are_not_attempted():
    result = _browser({}, "browser_media_control", {"action": "set_volume"})
    assert (result.status, result.reason) == ("not_attempted", "invalid_arguments")


def test_list_tabs_success_is_verified_read():
    result = _browser({"type": "STATUS", "tabs": [{"id": 1, "domain": "example.com"}]},
                      "browser_list_tabs", {})
    assert (result.status, result.reason) == ("verified", "ok")


# --------------------------- IoT --------------------------- #

class _IoT:
    def __init__(self, command=None, polled=None, command_error=None, poll_error=False):
        self._command, self._polled = command, polled
        self._command_error, self._poll_error = command_error, poll_error

    def command(self, *args):
        if self._command_error is not None:
            raise self._command_error
        return dict(self._command)

    def command_status(self, request_id):
        if self._poll_error:
            raise RuntimeError("fixture poll")
        return dict(self._polled)

    def status(self):
        return {"devices": [{"room_id": "a", "capabilities": ["climate.power"]},
                            {"room_id": "b", "capabilities": ["climate.power"]}]}


def _ac(client, **args):
    reg = ToolRegistry()
    register_iot(reg, SimpleNamespace(iot=client))
    return reg.run_result("control_room_ac", dict({"action": "off", "room_id": "a"}, **args),
                          confirmed=True)


def _wrapped(cause):
    try:
        raise RuntimeError("IoT gateway service is unavailable") from cause
    except RuntimeError as exc:
        return exc


@pytest.mark.parametrize("gateway_status,status,reason,layer", [
    ("queued_for_mqtt", "dispatched", "accepted_unverified", "mqtt"),
    ("ir_sent", "dispatched", "accepted_unverified", "node"),
    ("node_result_ok_uncorrelated", "dispatched", "accepted_unverified", "node"),
    ("ack_timeout_unknown", "unknown", "ack_timeout_unknown", "mqtt"),
    ("publish_failed", "failed", "publish_failed", "mqtt"),
    ("failed", "failed", "remote_error", "node"),
    ("something_new", "unknown", "unexpected_response", "gateway"),
])
def test_ac_command_status_mapping_never_claims_device_state(gateway_status, status, reason, layer):
    result = _ac(_IoT(command={"status": gateway_status}))
    assert (result.status, result.reason, result.layer) == (status, reason, layer)
    assert result.layer != "device"


def test_ac_timer_scheduled_is_only_accepted_by_gateway():
    """Lịch đã lưu ở gateway chưa chứng minh máy lạnh sẽ tắt: dispatched, không verified."""
    result = _ac(_IoT(command={"status": "scheduled", "run_until": "2030-01-01T10:00:00+00:00"}),
                 action="schedule_off", timer_minutes=30)
    assert (result.status, result.layer) == ("dispatched", "gateway")


def test_ac_timeout_after_send_is_unknown_not_failed():
    result = _ac(_IoT(command_error=_wrapped(URLError(socket.timeout("timed out")))))
    assert (result.status, result.reason, result.side_effect_possible) == ("unknown", "deadline_exceeded", True)


def test_ac_gateway_rejection_and_unreachable_gateway_are_failed():
    rejected = _ac(_IoT(command_error=_wrapped(HTTPError("u", 400, "bad", {}, None))))
    unreachable = _ac(_IoT(command_error=_wrapped(ConnectionRefusedError())))
    assert (rejected.status, rejected.reason) == ("failed", "remote_error")
    assert (unreachable.status, unreachable.reason) == ("failed", "dependency_unavailable")


def test_ac_poll_error_keeps_last_known_dispatched_state(monkeypatch):
    import features.iot.tools as module
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    result = _ac(_IoT(command={"status": "queued_for_mqtt", "request_id": "r1"}, poll_error=True))
    assert (result.status, result.layer) == ("dispatched", "mqtt")


def test_ac_room_required_is_not_attempted():
    reg = ToolRegistry()
    register_iot(reg, SimpleNamespace(iot=_IoT()))
    result = reg.run_result("control_room_ac", {"action": "off"}, confirmed=True)
    assert (result.status, result.reason) == ("not_attempted", "target_ambiguous")


def test_fast_path_still_reads_ac_result_as_json():
    result = _ac(_IoT(command={"status": "ir_sent"}))
    assert "chưa xác minh" in describe_ac_result(str(result), {"action": "off"})


# --------------------------- MCP --------------------------- #

def test_mcp_not_connected_is_failed_dependency():
    client = MCPClient("fixture")
    with pytest.raises(MCPError) as error:
        client.call_tool("gws_gmail_send", {})
    assert (error.value.status, error.value.reason, error.value.layer) == (
        "failed", "dependency_unavailable", "mcp")


def test_mcp_failure_after_dispatch_is_unknown(monkeypatch):
    import asyncio
    client = MCPClient("fixture")
    client.loop = object()
    monkeypatch.setattr(type(client), "connected", property(lambda self: True))

    def submit(coroutine, loop):
        coroutine.close()
        return SimpleNamespace(result=lambda timeout: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", submit)
    with pytest.raises(MCPError) as error:
        client.call_tool("gws_gmail_send", {})
    assert (error.value.status, error.value.reason) == ("unknown", "transport_error")
