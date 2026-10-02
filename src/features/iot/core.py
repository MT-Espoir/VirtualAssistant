"""Room state, MQTT contract adapter, alerts, and climate timing policy."""

import json
import logging
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from features.iot.storage import iso, utc_now


logger = logging.getLogger(__name__)


def _parsed_time(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


class IoTCore:
    def __init__(self, settings, devices, store, publish):
        self.settings = settings
        self.devices = tuple(devices)
        self._by_id = {d.device_id: d for d in devices}
        self._by_prefix = {d.topic_prefix: d for d in devices}
        self.store = store
        self._publish = publish  # (topic, bytes, qos, retain) -> bool
        self._lock = threading.RLock()
        self._last_live = {}
        self._last_sample = {}
        self._presence = {}
        self._hot_since = {}
        self._last_temperature_sample_at = {}
        self._alert_active = set()
        self._timer_failure_reported = set()
        self._legacy_pending = {}
        self._automation = store.automations()
        self.mqtt_connected = False
        self.enabled = True

    def apply_controls(self, values):
        """Called by the gateway, so service settings change without a restart."""
        from services.control_panel import validate_threshold
        with self._lock:
            changes = {}
            for key, attr in (("IOT_COMMANDS_ENABLED", "commands_enabled"),
                              ("IOT_AUTOMATION_ENABLED", "automation_enabled")):
                if key in values:
                    if type(values[key]) is not bool:
                        raise ValueError("invalid IoT control")
                    changes[attr] = values[key]
            if "IOT_AUTO_ON_TEMPERATURE_C" in values:
                changes["auto_on_temperature_c"] = validate_threshold(values["IOT_AUTO_ON_TEMPERATURE_C"])
            enabled = values.get("IOT_ENABLED", self.enabled)
            if type(enabled) is not bool:
                raise ValueError("invalid IoT enabled state")
            updated = replace(self.settings, **changes)
            if (updated.auto_on_temperature_c != self.settings.auto_on_temperature_c or
                    updated.automation_enabled != self.settings.automation_enabled or enabled != self.enabled):
                self._hot_since.clear()
            self.settings, self.enabled = updated, enabled

    def topics(self):
        suffixes = (
            "availability", "dht20/state", "ac/state", "ac/result",
            "ac/ack", "light/state",
        )
        return [f"{device.topic_prefix}/{suffix}"
                for device in self.devices for suffix in suffixes]

    def _device_for_topic(self, topic):
        for prefix, device in self._by_prefix.items():
            if topic.startswith(prefix + "/"):
                return device, topic[len(prefix) + 1:]
        return None, None

    def ingest(self, topic, payload, *, retained=False):
        device, suffix = self._device_for_topic(topic)
        if device is None or len(payload) > 4096:
            return False
        try:
            value = payload.decode("utf-8", "strict").strip()
            with self._lock:
                return self._ingest(device, suffix, value, retained)
        except (UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False

    def _ingest(self, device, suffix, value, retained):
        if suffix == "availability":
            if value not in ("online", "offline"):
                return False
            availability = "unknown" if retained and value == "online" else value
            seen = iso(utc_now()) if not retained and value == "online" else None
            if seen:
                self._last_live[device.device_id] = utc_now()
            self.store.set_device(device.device_id, availability, seen)
            return True

        if suffix == "dht20/state":
            data = json.loads(value)
            if not isinstance(data, dict) or set(data) != {
                    "temperature_c", "humidity_percent", "sample"}:
                return False
            if (type(data["temperature_c"]) not in (int, float) or
                    type(data["humidity_percent"]) not in (int, float)):
                return False
            temperature = float(data["temperature_c"])
            humidity = float(data["humidity_percent"])
            sample = data["sample"]
            if (not -40 <= temperature <= 85 or not 0 <= humidity <= 100
                    or type(sample) is not int or not 1 <= sample <= 4294967295):
                return False
            key = device.device_id
            signature = (sample, temperature, humidity, retained)
            if self._last_sample.get(key) == signature:
                return True
            self._last_sample[key] = signature
            quality = "retained_unverified" if retained else "fresh"
            received = utc_now()
            self.store.record_measurement(device, "temperature_c", temperature, "°C",
                                          received_at=received, quality=quality, sample=sample)
            self.store.record_measurement(device, "humidity_percent", humidity, "%RH",
                                          received_at=received, quality=quality, sample=sample)
            if not retained:
                self._mark_live(device, received)
                self._temperature_event(device.room_id, temperature, received)
            return True

        if suffix == "light/state":
            if "illuminance.read" not in device.capabilities:
                return False
            data = json.loads(value)
            raw_lux = data["illuminance_lux"] if isinstance(data, dict) else data
            if type(raw_lux) not in (int, float):
                return False
            lux = float(raw_lux)
            if not 0 <= lux <= 200000:
                return False
            received = utc_now()
            self.store.record_measurement(device, "illuminance_lux", lux, "lx",
                                          received_at=received,
                                          quality="retained_unverified" if retained else "fresh")
            if not retained:
                self._mark_live(device, received)
            return True

        if suffix == "ac/state":
            data = json.loads(value)
            if (not isinstance(data, dict) or set(data) != {
                    "power", "temperature", "mode", "fan"} or
                    type(data["power"]) is not bool or
                    type(data["temperature"]) is not int or
                    not 16 <= data["temperature"] <= 30 or
                    data["mode"] not in ("cool", "economic", "dry", "fan", "auto") or
                    data["fan"] != "auto"):
                return False
            self.store.set_device(device.device_id, "online" if not retained else "unknown",
                                  iso(utc_now()) if not retained else None, ac_state=data)
            if not retained:
                self._mark_live(device, utc_now())
            return True

        if suffix == "ac/ack":
            if retained:
                return False
            data = json.loads(value)
            if not isinstance(data, dict) or not isinstance(data.get("request_id"), str):
                return False
            try:
                uuid.UUID(data["request_id"])
            except ValueError:
                return False
            status = data.get("command_status")
            if status not in ("received", "ir_sent", "failed"):
                return False
            command = self.store.command(data["request_id"])
            if command is None or command["device_id"] != device.device_id:
                return False
            return self.store.acknowledge_command(data["request_id"], status, data)

        if suffix == "ac/result":
            if retained or value not in (
                    "ok", "error: command is empty or too long",
                    "error: unsupported command"):
                return False
            self._mark_live(device, utc_now())
            pending = self._legacy_pending.pop(device.device_id, None)
            if pending and utc_now() <= pending["deadline"]:
                status = ("node_result_ok_uncorrelated" if value == "ok" else "failed")
                self.store.update_command(pending["request_id"], status, {
                    "raw_result": value,
                    "correlation": "single_gateway_command_only_no_request_id",
                    "physical_ac_state_verified": False,
                })
            return True
        return False

    def _mark_live(self, device, when):
        self._last_live[device.device_id] = when
        self.store.set_device(device.device_id, "online", iso(when))

    def _temperature_event(self, room_id, temperature, when):
        threshold = self.settings.alert_temperature_c
        if temperature > threshold and room_id not in self._alert_active:
            self._alert_active.add(room_id)
            self.store.add_alert(
                room_id, "high_temperature",
                f"Nhiệt độ phòng {room_id} đang là {temperature:.1f} độ C, "
                f"cao hơn ngưỡng {threshold:g} độ C.")
        elif temperature <= threshold - 1:
            self._alert_active.discard(room_id)
        previous = self._last_temperature_sample_at.get(room_id)
        if (previous is not None and
                (when - previous).total_seconds() > self.settings.sensor_ttl_seconds):
            self._hot_since.pop(room_id, None)
        self._last_temperature_sample_at[room_id] = when
        if temperature > self.settings.auto_on_temperature_c:
            self._hot_since.setdefault(room_id, when)
        else:
            self._hot_since.pop(room_id, None)

    def update_presence(self, room_id, present, confidence=1.0):
        if not self._room_exists(room_id):
            raise ValueError("unknown room")
        if type(present) is not bool or not 0 <= float(confidence) <= 1:
            raise ValueError("invalid presence")
        with self._lock:
            self._presence[room_id] = {
                "present": present, "confidence": float(confidence),
                "received_at": iso(utc_now()),
            }

    def _room_exists(self, room_id):
        return any(d.room_id == room_id for d in self.devices)

    def _climate_device(self, room_id):
        return next((d for d in self.devices if d.room_id == room_id and
                     "climate.power" in d.capabilities), None)

    def _room_state(self, room_id):
        return self._automation.setdefault(room_id, {
            "room_id": room_id, "run_until": None, "cooldown_until": None,
            "manual_lockout_until": None, "timer_source": None,
        })

    def _save_room_state(self, room_id):
        state = self._room_state(room_id)
        self.store.save_automation(room_id, state["run_until"], state["cooldown_until"],
                                   state["manual_lockout_until"], state["timer_source"])

    def _send_power(self, room_id, power, source, *, temperature_c=None, mode=None):
        if not self.enabled or not self.settings.commands_enabled:
            raise RuntimeError("IoT commands are disabled")
        if not self.mqtt_connected:
            raise RuntimeError("MQTT broker is disconnected")
        device = self._climate_device(room_id)
        if device is None:
            raise ValueError("no climate device in room")
        availability = self._availability(device, utc_now())
        if source not in ("voice", "ui") and availability != "online":
            raise RuntimeError("Climate node is offline or has no fresh heartbeat")
        protocol = self.settings.command_protocol
        if protocol not in ("composite", "v2"):
            raise RuntimeError("Unsupported IoT command protocol")
        if protocol == "composite":
            pending = self._legacy_pending.get(device.device_id)
            if pending:
                if utc_now() <= pending["deadline"]:
                    raise RuntimeError("Previous A/C command is awaiting the node result")
                self.store.update_command(pending["request_id"], "ack_timeout_unknown")
                del self._legacy_pending[device.device_id]
        request_id = str(uuid.uuid4())
        if protocol == "composite":
            if power == "on":
                temperature_c = (self.settings.default_ac_temperature_c
                                 if temperature_c is None else temperature_c)
                mode = "cool" if mode is None else mode
                if not 16 <= temperature_c <= 30:
                    raise ValueError("IOT_DEFAULT_AC_TEMPERATURE_C must be 16..30")
                payload = f"on {temperature_c} {mode}".encode("ascii")
            else:
                payload = b"off"
            topic, qos = f"{device.topic_prefix}/ac/command", 0
        else:
            command = {
                "request_id": request_id, "power": power,
                "expires_at": iso(utc_now() + timedelta(seconds=30)),
            }
            if power == "on":
                command["temperature_c"] = (self.settings.default_ac_temperature_c
                                            if temperature_c is None else temperature_c)
                command["mode"] = "cool" if mode is None else mode
            payload = json.dumps(command, separators=(",", ":")).encode("utf-8")
            topic, qos = f"{device.topic_prefix}/ac/command_v2", 1
        self.store.add_command(request_id, room_id, device.device_id, source,
                               power, "pending")
        published = self._publish(topic, payload, qos, False)
        self.store.update_command(request_id,
                                  "queued_for_mqtt" if published else "publish_failed",
                                  expected_status="pending")
        if not published:
            raise RuntimeError("MQTT publish failed")
        if protocol == "composite":
            self._legacy_pending[device.device_id] = {
                "request_id": request_id,
                "deadline": utc_now() + timedelta(seconds=10),
            }
        result = self.store.command(request_id)
        result["mqtt_topic"] = topic
        result["mqtt_payload"] = payload.decode("ascii" if protocol == "composite" else "utf-8")
        result["command_protocol"] = protocol
        result["device_availability_at_publish"] = availability
        if availability != "online":
            result["delivery_warning"] = (
                "Device has no fresh heartbeat. MQTT publish is not proof that the "
                "node received or executed this command; wait for ac/result."
            )
        return result

    def command(self, room_id, power, *, source="voice", timer_minutes=None,
                temperature_c=None, mode=None):
        if not self.enabled:
            raise RuntimeError("IoT is disabled in the control panel")
        if not self._room_exists(room_id):
            raise ValueError("unknown room")
        if power not in ("on", "off", "schedule_off"):
            raise ValueError("power must be on, off, or schedule_off")
        if self._climate_device(room_id) is None:
            raise ValueError("no climate device in room")
        if source not in ("voice", "ui"):
            raise ValueError("invalid command source")
        if timer_minutes is not None and (type(timer_minutes) is not int or
                                          not 1 <= timer_minutes <= 1440):
            raise ValueError("timer_minutes must be 1..1440")
        if power == "off" and timer_minutes is not None:
            raise ValueError("off does not accept timer_minutes")
        if temperature_c is not None and (type(temperature_c) is not int or
                                          not 16 <= temperature_c <= 30):
            raise ValueError("temperature_c must be 16..30")
        if mode is not None and mode not in ("cool", "economic"):
            raise ValueError("mode must be cool or economic")
        if power != "on" and (temperature_c is not None or mode is not None):
            raise ValueError("temperature_c and mode apply only to on")
        with self._lock:
            state = self._room_state(room_id)
            now = utc_now()
            if power == "schedule_off":
                if timer_minutes is None:
                    raise ValueError("schedule_off requires timer_minutes")
                if not self.settings.commands_enabled or not self.mqtt_connected:
                    raise RuntimeError("Climate commands are unavailable")
                state["run_until"] = iso(now + timedelta(minutes=int(timer_minutes)))
                state["timer_source"] = "user_timer"
                self._timer_failure_reported.discard(room_id)
                self._save_room_state(room_id)
                logger.info("A/C off scheduled for room %s at %s", room_id,
                            state["run_until"])
                return {"status": "scheduled", "run_until": state["run_until"]}
            if power == "off":
                state["manual_lockout_until"] = iso(now + timedelta(hours=6))
                self._hot_since.pop(room_id, None)
                self._save_room_state(room_id)
            result = self._send_power(room_id, power, source,
                                      temperature_c=temperature_c, mode=mode)
            if power == "off":
                state["run_until"] = None
                state["timer_source"] = None
                self._timer_failure_reported.discard(room_id)
                self._save_room_state(room_id)
            elif timer_minutes is not None:
                state["run_until"] = iso(now + timedelta(minutes=timer_minutes))
                state["timer_source"] = "user_timer"
                self._timer_failure_reported.discard(room_id)
                self._save_room_state(room_id)
            elif state["run_until"]:
                logger.info("A/C on command kept existing off timer for room %s at %s",
                            room_id, state["run_until"])
            if power == "on" and state["run_until"]:
                result["run_until"] = state["run_until"]
            return result

    def tick(self):
        now = utc_now()
        with self._lock:
            for device_id, pending in list(self._legacy_pending.items()):
                if now > pending["deadline"]:
                    self.store.update_command(pending["request_id"], "ack_timeout_unknown")
                    del self._legacy_pending[device_id]
            for room_id in {d.room_id for d in self.devices}:
                state = self._room_state(room_id)
                run_until = _parsed_time(state["run_until"])
                if run_until is not None and now >= run_until:
                    try:
                        result = self._send_power(
                            room_id, "off", state["timer_source"] or "auto_timer")
                    except (RuntimeError, ValueError) as exc:
                        if room_id not in self._timer_failure_reported:
                            logger.warning("A/C off timer due for room %s but command not sent: %s",
                                           room_id, exc)
                            self._timer_failure_reported.add(room_id)
                        continue  # retry when the broker/node is available
                    logger.info("A/C off timer published for room %s: request %s, status %s",
                                room_id, result["request_id"], result["status"])
                    self._timer_failure_reported.discard(room_id)
                    state["run_until"] = None
                    state["timer_source"] = None
                    state["cooldown_until"] = iso(now + timedelta(hours=2))
                    self._hot_since.pop(room_id, None)
                    self._save_room_state(room_id)
                    continue
                if not self.enabled or not self.settings.automation_enabled or run_until is not None:
                    continue
                if _parsed_time(state["manual_lockout_until"]) and now < _parsed_time(
                        state["manual_lockout_until"]):
                    self._hot_since.pop(room_id, None)
                    continue
                if _parsed_time(state["cooldown_until"]) and now < _parsed_time(
                        state["cooldown_until"]):
                    self._hot_since.pop(room_id, None)
                    continue
                temperature = self._fresh_temperature(room_id, now)
                if temperature is None or temperature <= self.settings.auto_on_temperature_c:
                    self._hot_since.pop(room_id, None)
                    continue
                self._hot_since.setdefault(room_id, now)
                # Only fresh samples prove the complete window: elapsed wall time
                # alone cannot extrapolate the last reading beyond its sample time.
                last_sample = self._last_temperature_sample_at.get(room_id)
                if last_sample is None or last_sample - self._hot_since[room_id] < timedelta(minutes=20):
                    continue
                if not self._fresh_presence(room_id, now):
                    continue
                device = self._climate_device(room_id)
                if device is None or self._availability(device, now) != "online":
                    continue
                ac_state = self.store.devices().get(device.device_id, {}).get("ac_state")
                if ac_state is None or ac_state.get("power") is not False:
                    continue  # pending state is not physical truth; avoid duplicate on
                try:
                    self._send_power(room_id, "on", "auto")
                except (RuntimeError, ValueError) as exc:
                    logger.warning("A/C auto-on not sent for room %s: %s", room_id, exc)
                    continue
                state["run_until"] = iso(now + timedelta(hours=1))
                state["timer_source"] = "auto_timer"
                self._save_room_state(room_id)

    def _fresh_temperature(self, room_id, now):
        row = self.store.latest(room_id).get("temperature_c")
        if not row or row["quality"] != "fresh":
            return None
        if row["device_id"] not in self._last_live:
            return None
        received = _parsed_time(row["received_at"])
        if not received or (now - received).total_seconds() > self.settings.sensor_ttl_seconds:
            return None
        return row["value"]

    def _fresh_presence(self, room_id, now):
        data = self._presence.get(room_id)
        if not data or not data["present"]:
            return False
        received = _parsed_time(data["received_at"])
        return bool(received and (now - received).total_seconds()
                    <= self.settings.presence_ttl_seconds)

    def _availability(self, device, now):
        state = self.store.devices().get(device.device_id, {})
        if state.get("availability") == "offline":
            return "offline"
        if not self.mqtt_connected:
            return "unknown"
        last = self._last_live.get(device.device_id)
        if last and (now - last).total_seconds() <= 3 * self.settings.sensor_ttl_seconds:
            return "online"
        return "unknown"

    def snapshot(self):
        now = utc_now()
        with self._lock:
            states = self.store.devices()
            devices = []
            for device in self.devices:
                item = device.public()
                item.update(states.get(device.device_id, {}))
                item["availability"] = self._availability(device, now)
                if item.get("ac_state") is not None:
                    item["ac_state_meaning"] = "node_pending_ir_state"
                devices.append(item)
            rooms = {}
            for device in self.devices:
                room = rooms.setdefault(device.room_id, {
                    "home_id": device.home_id, "room_id": device.room_id,
                    "measurements": {}, "presence": None,
                })
                for metric, row in self.store.latest(device.room_id).items():
                    received = _parsed_time(row["received_at"])
                    fresh = (row["quality"] == "fresh" and received is not None and
                             (now - received).total_seconds() <= self.settings.sensor_ttl_seconds
                             and row["device_id"] in self._last_live)
                    room["measurements"][metric] = {
                        "value": row["value"], "unit": row["unit"],
                        "received_at": row["received_at"],
                        "quality": "fresh" if fresh else "stale",
                        "device_id": row["device_id"],
                    }
                if self._fresh_presence(device.room_id, now):
                    room["presence"] = {"present": True, **self._presence[device.room_id]}
                room["automation"] = dict(self._room_state(device.room_id))
            return {"broker_connected": self.mqtt_connected,
                    "policy_version": 2,
                    "devices": devices, "rooms": list(rooms.values()),
                    "policy": {"enabled": self.enabled,
                               "commands_enabled": self.settings.commands_enabled,
                               "automation_enabled": self.settings.automation_enabled,
                               "threshold_c": self.settings.auto_on_temperature_c,
                               "hot_window_minutes": 20,
                               "sensor_ttl_seconds": self.settings.sensor_ttl_seconds}}

    def disconnected(self):
        with self._lock:
            self.mqtt_connected = False
            for pending in self._legacy_pending.values():
                self.store.update_command(pending["request_id"], "ack_timeout_unknown")
            self._legacy_pending.clear()
            self._last_live.clear()
            self._hot_since.clear()
            self._last_temperature_sample_at.clear()
