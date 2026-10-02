"""Explicit room/device mapping; unknown MQTT publishers never become controllable."""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    device_id: str
    home_id: str
    room_id: str
    name: str
    kind: str
    topic_prefix: str
    capabilities: tuple

    @classmethod
    def from_mapping(cls, item):
        return cls(
            device_id=str(item["device_id"]),
            home_id=str(item["home_id"]),
            room_id=str(item["room_id"]),
            name=str(item.get("name") or item["device_id"]),
            kind=str(item.get("kind") or "mqtt_node"),
            topic_prefix=str(item["topic_prefix"]).strip("/"),
            capabilities=tuple(str(x) for x in item.get("capabilities", [])),
        )

    def public(self):
        return {
            "device_id": self.device_id, "home_id": self.home_id,
            "room_id": self.room_id, "name": self.name, "kind": self.kind,
            "capabilities": list(self.capabilities),
        }


DEFAULT_DEVICES = [
    {
        "device_id": "esp32s3-ir-gateway",
        "home_id": "home-main",
        "room_id": "bedroom",
        "name": "Gateway phòng ngủ",
        "kind": "mqtt_node",
        "topic_prefix": "home/esp32s3-ir-gateway",
        "capabilities": ["temperature.read", "humidity.read", "climate.power"],
    }
]


def load_devices(path):
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else DEFAULT_DEVICES
    if not isinstance(data, list) or not data:
        raise ValueError("IOT_DEVICES_PATH must contain a non-empty device array")
    devices = [Device.from_mapping(item) for item in data]
    ids = [item.device_id for item in devices]
    prefixes = [item.topic_prefix for item in devices]
    if len(ids) != len(set(ids)) or len(prefixes) != len(set(prefixes)):
        raise ValueError("IoT device IDs and topic prefixes must be unique")
    for device in devices:
        if (not device.device_id or not device.home_id or not device.room_id or
                not device.topic_prefix or any(char in device.topic_prefix for char in "+#")):
            raise ValueError("IoT device IDs, rooms, and MQTT topic prefixes must be valid")
    for index, prefix in enumerate(prefixes):
        if any(prefix.startswith(other + "/") or other.startswith(prefix + "/")
               for other in prefixes[index + 1:]):
            raise ValueError("IoT MQTT topic prefixes must not overlap")
    rooms = {}
    for device in devices:
        previous_home = rooms.setdefault(device.room_id, device.home_id)
        if previous_home != device.home_id:
            raise ValueError("IoT room IDs must be unique across homes")
    return devices
