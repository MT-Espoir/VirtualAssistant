"""Configuration shared by Alice and the local IoT gateway process."""

import os
from dataclasses import dataclass
from pathlib import Path

from utils.config import config  # loads src/.env with the application's usual precedence
from utils.control_settings import override


ROOT = Path(__file__).resolve().parents[3]


def _path(name, default):
    raw = os.getenv(name, default).strip()
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _number(name, default, cast):
    try:
        return cast(override(name, os.getenv(name, default)))
    except (TypeError, ValueError):
        return cast(default)


def _enabled(name, default=False):
    value = os.getenv(name)
    return override(name, default if value is None else value.strip().lower() in ("1", "true", "yes", "on"))


@dataclass(frozen=True)
class IoTSettings:
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    api_host: str
    api_port: int
    token_path: Path
    database_path: Path
    devices_path: Path
    commands_enabled: bool
    automation_enabled: bool
    alert_temperature_c: float
    sensor_ttl_seconds: int
    presence_ttl_seconds: int
    command_protocol: str = "composite"
    default_ac_temperature_c: int = 28
    auto_on_temperature_c: float = 32.5

    @classmethod
    def from_env(cls):
        return cls(
            mqtt_host=os.getenv("IOT_MQTT_HOST", "192.168.2.19").strip(),
            mqtt_port=_number("IOT_MQTT_PORT", 1883, int),
            mqtt_username=os.getenv("IOT_MQTT_USERNAME", "").strip(),
            mqtt_password=os.getenv("IOT_MQTT_PASSWORD", ""),
            api_host="127.0.0.1",  # IPC is never exposed to the LAN
            api_port=_number("IOT_API_PORT", 18787, int),
            token_path=_path("IOT_API_TOKEN_PATH", "data/iot_api_token"),
            database_path=_path("IOT_DATABASE_PATH", "data/iot.db"),
            devices_path=_path("IOT_DEVICES_PATH", "data/iot_devices.json"),
            commands_enabled=_enabled("IOT_COMMANDS_ENABLED", True),
            automation_enabled=_enabled("IOT_AUTOMATION_ENABLED"),
            alert_temperature_c=_number("IOT_ALERT_TEMPERATURE_C", 32.0, float),
            sensor_ttl_seconds=_number("IOT_SENSOR_TTL_SECONDS", 330, int),
            presence_ttl_seconds=_number("IOT_PRESENCE_TTL_SECONDS", 10, int),
            command_protocol=os.getenv("IOT_COMMAND_PROTOCOL", "composite").strip().lower(),
            default_ac_temperature_c=_number("IOT_DEFAULT_AC_TEMPERATURE_C", 28, int),
            auto_on_temperature_c=_number("IOT_AUTO_ON_TEMPERATURE_C", 32.5, float),
        )


settings = IoTSettings.from_env()
