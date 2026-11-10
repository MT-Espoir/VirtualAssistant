"""Voice/agent adapters for the local IoT gateway."""

import json
import time
from datetime import datetime
from urllib.error import HTTPError

from agent.results import ActionResult
from agent.tools import Tool

# Trạng thái lệnh của gateway -> (status, reason, tầng). Không trạng thái nào tới tầng
# `device`: chưa có phép đọc trạng thái vật lý của máy lạnh (I1). Lịch hẹn tắt đã lưu
# cũng chỉ là gateway đã nhận: mục tiêu "máy lạnh tắt sau N phút" chưa đọc lại được.
_COMMAND_STATUSES = {
    "scheduled": ("dispatched", "accepted_unverified", "gateway"),
    "pending": ("unknown", "deadline_exceeded", "gateway"),
    "queued_for_mqtt": ("dispatched", "accepted_unverified", "mqtt"),
    "published_to_broker": ("dispatched", "accepted_unverified", "mqtt"),
    "received": ("dispatched", "accepted_unverified", "node"),
    "ir_sent": ("dispatched", "accepted_unverified", "node"),
    "node_result_ok_uncorrelated": ("dispatched", "accepted_unverified", "node"),
    "ack_timeout_unknown": ("unknown", "ack_timeout_unknown", "mqtt"),
    "publish_failed": ("failed", "publish_failed", "mqtt"),
    "failed": ("failed", "remote_error", "node"),
    "room_required": ("not_attempted", "target_ambiguous", "local"),
}


def _result(name, data, status="verified", reason="ok", layer="gateway"):
    """JSON cho LLM/`describe_ac_result` kèm trạng thái theo hợp đồng kết quả (K9)."""
    return ActionResult(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                        name=name, status=status, reason=reason, layer=layer,
                        side_effect_possible=status in ("dispatched", "unknown"))


def _call_error(name, exc, data):
    """RuntimeError của IoTClient -> kết quả. Hết giờ chờ sau khi gửi là CHƯA RÕ, không
    phải thất bại: gateway có thể đã nhận và phát lệnh."""
    cause = exc.__cause__
    if isinstance(cause, HTTPError):
        status, reason = "failed", "remote_error"
    elif isinstance(cause, TimeoutError) or isinstance(getattr(cause, "reason", None), TimeoutError):
        status, reason = "unknown", "deadline_exceeded"
    else:
        status, reason = "failed", "dependency_unavailable"
    return _result(name, data, status, reason)


def _environment(client, room_id="bedroom", metric=None, hours=None):
    try:
        if hours is not None:
            return _result("get_room_environment",
                           client.history(room_id, metric or "temperature_c", hours))
        status = client.status()
        if room_id == "all":
            return _result("get_room_environment", status)
        room = next((item for item in status["rooms"] if item["room_id"] == room_id), None)
        if room is None:
            return _result("get_room_environment",
                           {"status": "error", "message": "Không tìm thấy phòng", "room_id": room_id},
                           "failed", "target_not_found")
        run_until = room.get("automation", {}).get("run_until")
        if run_until:
            deadline = datetime.fromisoformat(run_until)
            room["automation"]["run_until_local"] = (
                deadline.astimezone().isoformat(timespec="seconds")
            )
            room["automation"]["off_timer_status"] = (
                "overdue_retrying" if deadline <= datetime.now(deadline.tzinfo)
                else "scheduled"
            )
        else:
            room["automation"]["off_timer_status"] = "none"
        devices = [item for item in status["devices"] if item["room_id"] == room_id]
        return _result("get_room_environment",
                       {"room": room, "devices": devices,
                        "requested_measurement": room.get("measurements", {}).get(metric) if metric else None,
                        "broker_connected": status["broker_connected"]})
    except RuntimeError as exc:
        # Chỉ đọc: không có gì đã gửi, nên mọi lỗi gọi gateway đều là thất bại.
        return _result("get_room_environment", {"status": "unavailable", "message": str(exc)},
                       "failed", "dependency_unavailable")


def _climate(client, action, room_id=None, timer_minutes=None,
             temperature_c=None, mode=None):
    name = "control_room_ac"
    try:
        if room_id is None:
            status = client.status()
            climate_rooms = sorted({item["room_id"] for item in status["devices"]
                                    if "climate.power" in item["capabilities"]})
            if len(climate_rooms) != 1:
                return _result(name, {"status": "room_required", "rooms": climate_rooms},
                               *_COMMAND_STATUSES["room_required"])
            room_id = climate_rooms[0]
    except RuntimeError as exc:
        return _result(name, {"status": "unavailable", "message": str(exc)},
                       "failed", "dependency_unavailable")
    try:
        result = client.command(room_id, action, timer_minutes, temperature_c, mode)
    except RuntimeError as exc:
        return _call_error(name, exc, {"status": "error", "message": str(exc)})
    try:
        sent_details = {key: result[key] for key in
                        ("mqtt_topic", "mqtt_payload", "command_protocol",
                         "device_availability_at_publish", "run_until")
                        if key in result}
        delivery_warning = result.get("delivery_warning")
        request_id = result.get("request_id")
        if request_id:
            for _ in range(10):
                time.sleep(0.2)
                try:
                    latest = client.command_status(request_id)
                except RuntimeError:
                    break       # lệnh đã gửi: giữ trạng thái biết sau cùng, không báo lỗi
                result = latest
                if latest.get("status") in ("ir_sent", "failed",
                                             "node_result_ok_uncorrelated"):
                    break
        result.update(sent_details)
        if result.get("run_until"):
            result["run_until_local"] = (
                datetime.fromisoformat(result["run_until"])
                .astimezone().isoformat(timespec="seconds")
            )
        if delivery_warning and result.get("status") not in (
                "ir_sent", "failed", "node_result_ok_uncorrelated"):
            result["delivery_warning"] = delivery_warning
    except (TypeError, ValueError, AttributeError):
        # Gateway trả phản hồi khác giao thức sau khi đã nhận lệnh: chưa rõ.
        return _result(name, {"status": "unknown"}, "unknown", "unexpected_response")
    status, reason, layer = _COMMAND_STATUSES.get(
        result.get("status"), ("unknown", "unexpected_response", "gateway"))
    return _result(name, result, status, reason, layer)


def register(reg, ctx):
    client = ctx.iot
    reg.register(Tool(
        name="get_room_environment",
        description="Số đo mới nhất theo metric; hours chỉ dùng cho lịch sử 1-336 giờ. "
                    "stale: đọc giá trị gần nhất và nói đã cũ. "
                    "Hẹn tắt: room.automation.run_until_local (không metric).",
        input_schema={
            "type": "object",
            "properties": {
                "room_id": {"type": "string", "description": "Mặc định bedroom; all liệt kê phòng"},
                "metric": {"type": "string", "enum": ["temperature_c", "humidity_percent",
                                                     "illuminance_lux"]},
                "hours": {"type": "integer", "minimum": 1, "maximum": 336},
            },
        },
        handler=lambda room_id="bedroom", metric=None, hours=None: _environment(
            client, room_id, metric, hours),
        evidence_policy="read",
    ))
    reg.register(Tool(
        name="control_room_ac",
        description="Bật/tắt, hẹn tắt máy lạnh. Bật một tiếng: on, timer_minutes=60. "
                    "Mặc định 28 °C cool. ac/result chưa xác minh trạng thái vật lý.",
        input_schema={
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["on", "off", "schedule_off"]},
                "room_id": {"type": "string", "description": "ID phòng; bắt buộc nếu có nhiều phòng"},
                "timer_minutes": {"type": "integer", "minimum": 1, "maximum": 1440},
                "temperature_c": {"type": "integer", "minimum": 16, "maximum": 30},
                "mode": {"type": "string", "enum": ["cool", "economic"]},
            },
        },
        handler=lambda action, room_id=None, timer_minutes=None,
                       temperature_c=None, mode=None: _climate(
            client, action, room_id, timer_minutes, temperature_c, mode),
        persistent=True,
        evidence_policy="dispatch_only",
        confirm_message=lambda action, room_id=None, timer_minutes=None, **kwargs: (
            ("bật máy lạnh" if action == "on" else "tắt máy lạnh" if action == "off" else "hẹn tắt máy lạnh")
            + (f" ở phòng {room_id}" if room_id else "")
            + (f" và tắt sau {timer_minutes} phút" if action == "on" and timer_minutes else
               f" sau {timer_minutes} phút" if timer_minutes else "")),
    ))
    reg.register(Tool(
        name="configure_climate_automation",
        description="Lưu quy tắc tự bật: trên threshold_c trong 20 phút, có người; giữ thời gian chờ. Áp dụng mọi phòng.",
        input_schema={"type": "object", "required": ["enabled"], "properties": {
            "enabled": {"type": "boolean"},
            "threshold_c": {"type": "number", "minimum": 16, "maximum": 50}}},
        handler=lambda enabled, threshold_c=None: _automation(client, enabled, threshold_c),
        persistent=True,
        # Gateway lưu bền rồi trả lại cấu hình đã lưu.
        evidence_policy="local_commit",
    ))


def _automation(client, enabled, threshold_c=None):
    try:
        return _result("configure_climate_automation",
                       client.configure_automation(enabled, threshold_c))
    except RuntimeError as exc:
        return _call_error("configure_climate_automation", exc,
                           {"status": "error", "message": str(exc)})
