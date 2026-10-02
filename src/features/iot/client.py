"""Loopback JSON client used by Alice desktop and the camera feature."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from features.iot.settings import settings


class IoTClient:
    def __init__(self, cfg=settings):
        self.cfg = cfg
        self.base_url = f"http://127.0.0.1:{cfg.api_port}/v1"

    def _call(self, method, path, body=None):
        try:
            token = self.cfg.token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("IoT gateway token is missing; start the gateway service") from exc
        payload = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        request = Request(
            self.base_url + path, data=payload, method=method,
            headers={"X-Alice-IoT-Token": token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                error = json.loads(exc.read().decode("utf-8")).get("error", "HTTP error")
            except (ValueError, UnicodeError):
                error = "HTTP error"
            raise RuntimeError(error) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("IoT gateway service is unavailable") from exc

    def status(self):
        return self._call("GET", "/status")

    def history(self, room_id, metric="temperature_c", hours=24):
        from urllib.parse import urlencode
        query = urlencode({"room_id": room_id, "metric": metric, "hours": hours})
        return self._call("GET", "/history?" + query)

    def command(self, room_id, power, timer_minutes=None, temperature_c=None, mode=None):
        body = {"room_id": room_id, "power": power}
        if timer_minutes is not None:
            body["timer_minutes"] = timer_minutes
        if temperature_c is not None:
            body["temperature_c"] = temperature_c
        if mode is not None:
            body["mode"] = mode
        return self._call("POST", "/climate", body)

    def command_status(self, request_id):
        return self._call("GET", "/commands/" + request_id)

    def presence(self, room_id, present, confidence=1.0):
        return self._call("POST", "/presence", {
            "room_id": room_id, "present": bool(present),
            "confidence": float(confidence),
        })

    def configure_automation(self, enabled, threshold_c=None):
        body = {"enabled": enabled}
        if threshold_c is not None:
            body["threshold_c"] = threshold_c
        return self._call("POST", "/automation", body)

    def alerts(self, after_id=0):
        return self._call("GET", f"/alerts?after_id={int(after_id)}")
