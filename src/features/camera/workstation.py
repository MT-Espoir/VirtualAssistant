"""Relative workstation proximity from the existing presence detector boxes.

No frame, face box, landmark or identity is retained by this module.
"""

import json
import os
import statistics
import time
from pathlib import Path


class ProximityEstimator:
    def __init__(self, camera_id, camera_index, calibration_path,
                 dwell_seconds=1.5, min_samples=4):
        self.camera_id = str(camera_id)
        self.camera_index = int(camera_index)
        self.path = Path(calibration_path) if calibration_path else None
        self.dwell_seconds = max(0.5, float(dwell_seconds))
        self.min_samples = max(3, int(min_samples))
        self._calibration = self._load()
        self._collecting = False
        self._samples = []
        self._candidate = "unknown"
        self._candidate_since = 0.0
        self._candidate_count = 0
        self._stable = "unknown"
        self._last_at = 0.0
        self._generation = None
        self._status = {"camera_id": self.camera_id,
                        "band": "unknown", "visibility": "degraded",
                        "quality": "insufficient", "calibration": "missing",
                        "valid_samples": 0, "sample_age_ms": None}

    def _load(self):
        if self.path is None:
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (value.get("version") == 1 and value.get("camera_id") == self.camera_id
                    and value.get("camera_index") == self.camera_index
                    and 0.02 <= float(value.get("face_ratio", 0)) <= 0.9):
                value["face_ratio"] = float(value["face_ratio"])
                return value
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        return None

    def begin_calibration(self):
        self._collecting = True
        self._samples.clear()
        self.reset()

    def reset(self):
        self._candidate = "unknown"
        self._candidate_since = 0.0
        self._candidate_count = 0
        self._stable = "unknown"
        self._last_at = 0.0
        self._generation = None
        self._status.update(band="unknown", visibility="degraded",
                            quality="insufficient", valid_samples=0,
                            sample_age_ms=None)

    def status(self):
        value = dict(self._status)
        if self._last_at:
            value["sample_age_ms"] = round((time.monotonic() - self._last_at) * 1000)
            if value["sample_age_ms"] > 2000:
                value.update(band="unknown", visibility="degraded",
                             quality="insufficient")
        value["calibration"] = ("collecting" if self._collecting else
                                value["calibration"] if self._calibration else "missing")
        value["calibration_samples"] = len(self._samples)
        return value

    def observe(self, faces, frame, provider, generation, now=None):
        now = time.monotonic() if now is None else float(now)
        height, width = frame.shape[:2]
        if generation != self._generation:
            self.reset()
            self._generation = generation
        # Sparse luminance/texture checks prevent a covered or dark webcam from
        # manufacturing a healthy no-face absence episode.
        sparse = frame[::8, ::8]
        light = float(sparse.mean())
        texture = float(sparse.std())
        healthy = 35 <= light <= 220 and texture >= 14
        visibility = ("degraded" if not healthy else
                      "no_face" if len(faces) == 0 else
                      "single_face" if len(faces) == 1 else "multiple_faces")
        source = {"provider": provider, "width": width, "height": height,
                  "camera_id": self.camera_id, "camera_index": self.camera_index}
        calibration = self._calibration
        valid_calibration = bool(calibration and all(
            calibration.get(key) == value for key, value in source.items()))
        ratio = None
        centered = False
        if healthy and len(faces) == 1:
            x, y, w, h = faces[0]
            ratio = max(0.0, h / max(1, height))
            center_x = (x + w / 2) / max(1, width)
            center_y = (y + h / 2) / max(1, height)
            centered = 0.17 <= center_x <= 0.83 and 0.13 <= center_y <= 0.87
        if self._collecting and ratio is not None and centered and ratio >= 0.07:
            self._samples.append(ratio)
            if len(self._samples) >= 12:
                baseline = statistics.median(self._samples)
                spread = statistics.median(abs(sample - baseline)
                                           for sample in self._samples)
                if spread > 0.12 * baseline:
                    self._samples = self._samples[-4:]
                else:
                    self._calibration = dict(source, version=1,
                                             face_ratio=round(baseline, 5))
                    self._collecting = False
                    self._samples.clear()
                    self._save()
                    calibration = self._calibration
                    valid_calibration = True
        if self._collecting:
            valid_calibration = False
        if not healthy or len(faces) > 1 or (len(faces) > 0 and not centered):
            raw = "unknown"
        elif not valid_calibration:
            raw = "unknown"
        elif len(faces) == 0:
            raw = "no_face"
        elif ratio >= 0.65 * calibration["face_ratio"]:
            raw = "near"
        elif ratio <= 0.45 * calibration["face_ratio"]:
            raw = "far"
        else:
            raw = "unknown"
        if raw == "unknown":
            self._candidate = raw
            self._candidate_count = 0
            self._stable = raw
        else:
            if raw != self._candidate:
                self._candidate = raw
                self._candidate_since = now
                self._candidate_count = 1
            else:
                self._candidate_count += 1
            if (self._candidate_count >= self.min_samples and
                    now - self._candidate_since >= self.dwell_seconds):
                self._stable = raw
        self._last_at = now
        band = self._stable if self._stable in ("near", "far") else "unknown"
        self._status = {
            "camera_id": self.camera_id,
            "band": band, "visibility": visibility,
            "quality": "good" if healthy else "degraded",
            "calibration": ("collecting" if self._collecting else
                            "ready" if valid_calibration else
                            "invalid" if calibration else "missing"),
            "valid_samples": self._candidate_count,
            "sample_age_ms": 0,
            "observation_state": self._stable,
            "observed_monotonic": now,
            "generation": generation,
        }
        return dict(self._status)

    def _save(self):
        if self.path is None or self._calibration is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(self._calibration, separators=(",", ":")),
                                 encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            # In-memory calibration remains usable for this session.
            pass
