"""Bounded, in-process handoff for webcam frames and IoT presence."""

from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time


@dataclass(frozen=True)
class FramePacket:
    sequence: int
    generation: int
    captured_at: str
    captured_monotonic: float
    pixels: object


class LatestFrame:
    """One slot; a slow consumer skips old frames instead of growing a queue."""

    def __init__(self):
        self._condition = threading.Condition()
        self._packet = None

    def publish(self, packet):
        with self._condition:
            self._packet = packet
            self._condition.notify_all()

    def clear(self):
        with self._condition:
            self._packet = None
            self._condition.notify_all()

    def wait_next(self, sequence, timeout=0.5):
        with self._condition:
            self._condition.wait_for(
                lambda: self._packet is not None and self._packet.sequence != sequence,
                timeout=timeout)
            return self._packet if self._packet and self._packet.sequence != sequence else None


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class PresenceOutbox:
    """Only the latest state is pending; HTTP never runs on the capture thread."""

    def __init__(self, client, room_id, debug=None):
        self.client = client
        self.room_id = room_id
        self.debug = debug
        self._condition = threading.Condition()
        self._pending = None
        self._stopping = False
        self._thread = None

    def start(self):
        if self.client is None or self._thread and self._thread.is_alive():
            return
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="alice-presence-outbox", daemon=True)
        self._thread.start()

    def submit(self, present):
        if self.client is None:
            return
        with self._condition:
            self._pending = bool(present)
            self._condition.notify()

    def stop(self):
        self.submit(False)
        with self._condition:
            self._stopping = True
            self._condition.notify()
        if self._thread is not None:
            self._thread.join(timeout=7)

    def _run(self):
        last_sent = 0.0
        last_value = None
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending is not None or self._stopping,
                                         timeout=0.5)
                if self._pending is None and self._stopping:
                    return
                if self._pending is None:
                    continue
                value = self._pending
                self._pending = None
            # Only fresh inference submissions refresh a positive gateway state.
            # If capture freezes, no more submissions arrive and gateway TTL expires.
            if value == last_value and time.monotonic() - last_sent < 3 and not self._stopping:
                continue
            try:
                self.client.presence(self.room_id, value,
                                     confidence=1.0 if value else 0.0)
            except Exception as exc:
                if self.debug:
                    self.debug("Presence report failed", {"error": type(exc).__name__}, "WARNING")
            finally:
                last_sent = time.monotonic()
                last_value = value
            with self._condition:
                if self._stopping and self._pending is None:
                    return
