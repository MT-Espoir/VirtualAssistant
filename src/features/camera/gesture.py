"""Local hand-landmark gesture recognition; no images or landmarks are retained."""

import hashlib
from pathlib import Path

from features.camera.face_auth import MODEL_DIR
from features.camera.hand_geometry import extract_hand_features


MODEL_FILE = "hand_landmarker_float16_v1.task"
MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"
MODEL_SOURCE = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
                "hand_landmarker/float16/1/hand_landmarker.task")
PROVIDER = "mediapipe-hand-landmarker-float16-v1"


def gesture_model_path(directory=MODEL_DIR):
    path = Path(directory) / MODEL_FILE
    if not path.is_file():
        raise FileNotFoundError(
            f"Missing {MODEL_FILE}; run packaging/install_camera_models.py --gesture")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != MODEL_SHA256:
        raise ValueError(f"Checksum mismatch for {MODEL_FILE}")
    return path


def classify_hand(landmarks, world_landmarks=None, return_details=False,
                  aspect_ratio=1.0):
    """Return thumbs_up, ok, or unknown from the user's exact pose definitions.

    Joint angles use 3-D world points when available; vertical orientation uses
    image points, where a smaller y means higher in the webcam image.
    """
    features = extract_hand_features(landmarks, world_landmarks, aspect_ratio)
    if features is None:
        return ("unknown", {}) if return_details else "unknown"
    label = features.confirmation()
    details = features.diagnostics()
    return (label, details) if return_details else label


class GestureDebouncer:
    """One event per held pose; rearm only after a visible release."""

    def __init__(self, hold_seconds=0.7, release_seconds=0.4, cooldown_seconds=1.5):
        self.hold_seconds = hold_seconds
        self.release_seconds = release_seconds
        self.cooldown_seconds = cooldown_seconds
        self.reset()

    def reset(self):
        self._candidate = "unknown"
        self._since = 0.0
        self._samples = 0
        self._armed = True
        self._release_since = None
        self._last_fired = float("-inf")

    def observe(self, label, now):
        if label not in ("thumbs_up", "ok"):
            self._candidate = "unknown"
            self._samples = 0
            if self._release_since is None:
                self._release_since = now
            if now - self._release_since >= self.release_seconds:
                self._armed = True
            return None
        self._release_since = None
        if label != self._candidate:
            self._candidate = label
            self._since = now
            self._samples = 1
            return None
        self._samples += 1
        if (self._armed and self._samples >= 4 and
                now - self._since >= self.hold_seconds and
                now - self._last_fired >= self.cooldown_seconds):
            self._armed = False
            self._last_fired = now
            return label
        return None

    @property
    def candidate_started_at(self):
        return self._since


class HandGestureEngine:
    """MediaPipe VIDEO-mode inference, owned by one dedicated camera worker."""

    def __init__(self, directory=MODEL_DIR):
        import mediapipe as mp

        self._mp = mp
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(
                model_asset_path=str(gesture_model_path(directory))),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.65,
            min_hand_presence_confidence=0.6,
            min_tracking_confidence=0.6)
        self._landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1
        self.last_features = None
        self.last_landmarks = ()

    def close(self):
        self.last_features = None
        self.last_landmarks = ()
        self._landmarker.close()

    def recognize(self, bgr_frame, timestamp_ms, include_landmarks=False):
        import cv2

        self.last_features = None
        self.last_landmarks = ()
        stamp = max(int(timestamp_ms), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = stamp
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, stamp)
        if include_landmarks:
            self.last_landmarks = tuple(
                tuple((float(point.x), float(point.y)) for point in hand)
                for hand in result.hand_landmarks)
        count = len(result.hand_landmarks)
        if count == 0:
            return "no_hand", "unknown", 0, None, {}
        if count != 1:
            return "multiple_hands", "unknown", count, None, {}
        world = result.hand_world_landmarks[0] if result.hand_world_landmarks else None
        aspect = bgr_frame.shape[1] / max(bgr_frame.shape[0], 1)
        features = extract_hand_features(result.hand_landmarks[0], world, aspect)
        if features is None:
            return "unclassified_pose", "unknown", count, None, {}
        self.last_features = features
        label, details = features.confirmation(), features.diagnostics()
        score = (float(result.handedness[0][0].score)
                 if result.handedness and result.handedness[0] else None)
        return ("ok" if label != "unknown" else "unclassified_pose",
                label, count, score, details)
