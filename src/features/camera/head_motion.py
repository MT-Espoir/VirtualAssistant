"""Experimental, debug-only head motion from YuNet's five face landmarks.

This is a proof of concept, not a head-pose or identity model. It never confirms
an Agent action; the user must review shadow observations on the target webcam.
"""

import statistics
import time
from collections import deque


class HeadMotionTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self._generation = None
        self._neutral_yaw = deque(maxlen=12)
        self._neutral_pitch = deque(maxlen=12)
        self._phase = None
        self._first_sign = 0
        self._phase_at = 0.0
        self._last_event_at = float("-inf")
        self._last_motion_started_at = 0.0
        self._last_sample_at = 0.0
        self._label = "unknown"
        self._status = {"state": "waiting_camera", "quality": "unknown",
                        "label": "unknown", "sample_age_ms": None}

    def status(self):
        result = dict(self._status)
        if self._last_sample_at:
            result["sample_age_ms"] = round(
                (time.monotonic() - self._last_sample_at) * 1000)
            if result["sample_age_ms"] > 2000:
                result.update(state="stale", quality="unknown", label="unknown")
            elif time.monotonic() - self._last_event_at > 2.0:
                result["label"] = "unknown"
        return result

    def unavailable(self):
        self.reset()
        self._status["state"] = "unavailable"

    @property
    def last_motion_started_at(self):
        return self._last_motion_started_at

    def observe(self, row, generation, now=None):
        now = time.monotonic() if now is None else float(now)
        if generation != self._generation:
            self.reset()
            self._generation = generation
        self._last_sample_at = now
        if row is None or len(row) < 14:
            self.reset()
            self._generation = generation
            self._last_sample_at = now
            self._status = {"state": "ready", "quality": "unknown",
                            "label": "unknown", "sample_age_ms": 0}
            return None
        # YuNet: two eyes, nose tip and mouth corners. Normalize by local face
        # geometry so the raw coordinates never leave this function.
        eyes_x = (float(row[4]) + float(row[6])) / 2
        eyes_y = (float(row[5]) + float(row[7])) / 2
        eye_width = abs(float(row[4]) - float(row[6]))
        mouth_y = (float(row[11]) + float(row[13])) / 2
        height = mouth_y - eyes_y
        if eye_width < 8 or height < 10:
            self._phase = None
            self._status = {"state": "ready", "quality": "low",
                            "label": "unknown", "sample_age_ms": 0}
            return None
        yaw = (float(row[8]) - eyes_x) / eye_width
        pitch = (float(row[9]) - eyes_y) / height
        if len(self._neutral_yaw) < 12:
            self._neutral_yaw.append(yaw)
            self._neutral_pitch.append(pitch)
            self._status = {"state": "calibrating", "quality": "good",
                            "label": "unknown", "sample_age_ms": 0}
            return None
        yaw_delta = yaw - statistics.median(self._neutral_yaw)
        pitch_delta = pitch - statistics.median(self._neutral_pitch)
        if abs(yaw_delta) > 0.9 or abs(pitch_delta) > 0.8:
            self._phase = None
            self._status = {"state": "ready", "quality": "low",
                            "label": "unknown", "sample_age_ms": 0}
            return None
        if abs(yaw_delta) >= 0.18 and abs(pitch_delta) >= 0.15:
            self._phase = None
            self._status = {"state": "ready", "quality": "ambiguous",
                            "label": "unknown", "sample_age_ms": 0}
            return None
        if self._phase is not None and now - self._phase_at > 2.6:
            self._phase = None
        event = None
        # Require first excursion, opposite excursion, then a neutral return.
        neutral = abs(yaw_delta) < 0.08 and abs(pitch_delta) < 0.07
        if self._phase is not None and self._phase[1] == "opposite" and neutral:
            if now - self._last_event_at >= 2.0:
                event = self._phase[0]
                self._last_event_at = now
                self._last_motion_started_at = self._phase_at
            self._phase = None
        else:
            for axis, delta, threshold in (("no", yaw_delta, 0.18),
                                           ("yes", pitch_delta, 0.15)):
                if abs(delta) < threshold:
                    continue
                sign = 1 if delta > 0 else -1
                if self._phase is None:
                    self._phase, self._first_sign, self._phase_at = (
                        (axis, "first"), sign, now)
                elif self._phase[0] != axis:
                    self._phase = None
                elif self._phase[1] == "first" and sign != self._first_sign:
                    self._phase = (axis, "opposite")
                break
        if (self._phase is None and abs(yaw_delta) < 0.08 and
                abs(pitch_delta) < 0.07):
            self._neutral_yaw.append(yaw)
            self._neutral_pitch.append(pitch)
        self._label = event or self._label
        self._status = {"state": "ready", "quality": "good",
                        "label": event or "unknown", "sample_age_ms": 0}
        return event
