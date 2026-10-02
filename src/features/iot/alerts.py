"""Deliver fresh gateway alerts through Alice's existing proactive speech gate."""

import logging
import threading
from datetime import datetime, timezone


logger = logging.getLogger(__name__)


class VoiceAlertPoller:
    def __init__(self, client, speak):
        self.client = client
        self.speak = speak  # message -> bool, using the app's proactive dispatcher
        self._stop = threading.Event()
        self._thread = None
        self._last_id = 0
        self._pending = {}

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="iot-voice-alerts",
                                        daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=4)

    def _run(self):
        while not self._stop.is_set():
            try:
                for alert in self.client.alerts(self._last_id)["alerts"]:
                    self._last_id = max(self._last_id, int(alert["id"]))
                    self._pending[alert["id"]] = alert
                now = datetime.now(timezone.utc)
                for alert_id, alert in list(self._pending.items()):
                    created = datetime.fromisoformat(alert["created_at"])
                    if (now - created).total_seconds() > 60:
                        del self._pending[alert_id]
                    elif self.speak(alert["message"]):
                        del self._pending[alert_id]
            except (RuntimeError, ValueError, KeyError, TypeError) as exc:
                logger.debug("IoT alert poll unavailable: %s", exc)
            self._stop.wait(3)
