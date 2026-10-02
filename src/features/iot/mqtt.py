"""MQTT transport for the gateway. Domain policy remains in IoTCore."""

import logging
import sys
from pathlib import Path


logger = logging.getLogger(__name__)


class MQTTTransport:
    def __init__(self, settings, core):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            local_deps = Path(__file__).resolve().parents[3] / "packaging/iot/python-deps"
            if local_deps.is_dir():
                sys.path.insert(0, str(local_deps))
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                raise RuntimeError("Install paho-mqtt to run the IoT gateway") from exc
        self.core = core
        self.settings = settings
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="alice-iot-gateway",
            clean_session=False,
        )
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self.client.reconnect_delay_set(min_delay=2, max_delay=60)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self):
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, 30)
        self.client.loop_start()

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()
        self.core.mqtt_connected = False

    def publish(self, topic, payload, qos=1, retain=False):
        if not self.core.mqtt_connected:
            return False
        result = self.client.publish(topic, payload, qos=qos, retain=retain)
        return result.rc == 0

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties):
        connected = getattr(reason_code, "value", reason_code) == 0
        self.core.mqtt_connected = connected
        if not connected:
            logger.warning("MQTT broker rejected connection: %s", reason_code)
            return
        for topic in self.core.topics():
            client.subscribe(topic, qos=1)
        logger.info("MQTT connected to %s:%s", self.settings.mqtt_host,
                    self.settings.mqtt_port)

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties):
        self.core.disconnected()
        logger.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, _client, _userdata, message):
        accepted = self.core.ingest(message.topic, message.payload,
                                    retained=bool(message.retain))
        if not accepted:
            logger.warning("Ignored malformed/unknown MQTT payload on %s", message.topic)
