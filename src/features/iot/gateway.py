"""Always-on IoT gateway process: MQTT ingestion and authenticated loopback API."""

import json
import logging
import os
import secrets
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from features.iot.core import IoTCore
from features.iot.mqtt import MQTTTransport
from features.iot.registry import load_devices
from features.iot.settings import settings
from features.iot.storage import IoTStore
from utils.control_settings import controls


logger = logging.getLogger(__name__)


def _token(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(48))
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except FileExistsError:
            pass
    token = path.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("IoT API token must be at least 32 characters")
    return token


class IoTGateway:
    def __init__(self, cfg=settings):
        self.settings = cfg
        self.token = _token(cfg.token_path)
        self.store = IoTStore(cfg.database_path)
        self.devices = load_devices(cfg.devices_path)
        self.transport = None
        self.core = IoTCore(cfg, self.devices, self.store,
                            lambda *args: self.transport.publish(*args))
        self.transport = MQTTTransport(cfg, self.core)
        self.server = ThreadingHTTPServer((cfg.api_host, cfg.api_port),
                                          self._handler_class())
        self.server.daemon_threads = True
        self._stop = threading.Event()
        self._ticker = threading.Thread(target=self._tick_loop, name="iot-policy",
                                        daemon=True)

    def _handler_class(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                logger.debug("IoT API: " + format, *args)

            def _send(self, status, data):
                raw = json.dumps(data, ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def _authorized(self):
                supplied = self.headers.get("X-Alice-IoT-Token", "")
                if not secrets.compare_digest(supplied, gateway.token):
                    self._send(401, {"error": "IoT API token is invalid"})
                    return False
                return True

            def do_GET(self):
                if not self._authorized():
                    return
                route = urlparse(self.path)
                query = parse_qs(route.query)
                try:
                    if route.path == "/v1/status":
                        data = gateway.core.snapshot()
                    elif route.path == "/v1/history":
                        room_id = query.get("room_id", [""])[0]
                        metric = query.get("metric", ["temperature_c"])[0]
                        if metric not in ("temperature_c", "humidity_percent",
                                          "illuminance_lux") or not gateway.core._room_exists(room_id):
                            raise ValueError("invalid room or metric")
                        hours = int(query.get("hours", ["24"])[0])
                        data = {"room_id": room_id, "metric": metric,
                                "unit": {"temperature_c": "°C",
                                         "humidity_percent": "%RH",
                                         "illuminance_lux": "lx"}[metric],
                                "resolution": "hourly",
                                "rows": gateway.store.history(room_id, metric, hours)}
                    elif route.path == "/v1/alerts":
                        after_id = int(query.get("after_id", ["0"])[0])
                        data = {"alerts": gateway.store.alerts_since(after_id)}
                    elif route.path.startswith("/v1/commands/"):
                        command_id = route.path.removeprefix("/v1/commands/")
                        data = gateway.store.command(command_id)
                        if data is None:
                            self._send(404, {"error": "unknown command"})
                            return
                    else:
                        self._send(404, {"error": "unknown route"})
                        return
                    self._send(200, data)
                except (ValueError, TypeError) as exc:
                    self._send(400, {"error": str(exc)})

            def do_POST(self):
                if not self._authorized():
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 2048:
                        raise ValueError("invalid request size")
                    data = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(data, dict):
                        raise ValueError("expected a JSON object")
                    if self.path == "/v1/presence":
                        gateway.core.update_presence(data["room_id"], data["present"],
                                                     data.get("confidence", 1.0))
                        result = {"status": "ok"}
                    elif self.path == "/v1/climate":
                        result = gateway.core.command(
                            data["room_id"], data["power"], source="voice",
                            timer_minutes=data.get("timer_minutes"),
                            temperature_c=data.get("temperature_c"),
                            mode=data.get("mode"))
                    elif self.path == "/v1/automation":
                        from services.control_panel import validate_threshold
                        if set(data) - {"enabled", "threshold_c"} or type(data.get("enabled")) is not bool:
                            raise ValueError("invalid automation settings")
                        changes = {"IOT_AUTOMATION_ENABLED": data["enabled"]}
                        if "threshold_c" in data:
                            changes["IOT_AUTO_ON_TEMPERATURE_C"] = validate_threshold(data["threshold_c"])
                        gateway.core.apply_controls(controls.update(changes))
                        result = {"status": "saved", "policy": gateway.core.snapshot()["policy"]}
                    else:
                        self._send(404, {"error": "unknown route"})
                        return
                    self._send(200, result)
                except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    self._send(400, {"error": str(exc)})
                except RuntimeError as exc:
                    self._send(409, {"error": str(exc)})

        return Handler

    def _tick_loop(self):
        ticks = 0
        while not self._stop.wait(1):
            try:
                self.core.apply_controls(controls.values())
                self.core.tick()
                ticks += 1
                if ticks >= 3600:
                    self.store.prune()
                    ticks = 0
            except Exception:
                logger.exception("IoT policy tick failed")

    def run(self):
        self.store.prune()
        self.transport.start()
        self._ticker.start()
        logger.info("IoT gateway API on 127.0.0.1:%s; broker %s:%s",
                    self.settings.api_port, self.settings.mqtt_host,
                    self.settings.mqtt_port)
        try:
            self.server.serve_forever(poll_interval=0.5)
        finally:
            self.stop()

    def stop(self):
        if self._stop.is_set():
            return
        self._stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.transport.stop()
        self.store.close()


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    gateway = IoTGateway()
    def request_stop(*_args):
        threading.Thread(target=gateway.server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    gateway.run()


if __name__ == "__main__":
    main()
