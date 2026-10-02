"""Ephemeral hand features shared by confirmation and future interaction poses.

WonderSnap inspired the scale-normalized 2-D finger features. Alice retains its
existing 3-D confirmation rules; neither frames nor landmarks are stored here.
"""

import math
from dataclasses import dataclass


FINGERS = (
    ("index", 5, 6, 7, 8),
    ("middle", 9, 10, 11, 12),
    ("ring", 13, 14, 15, 16),
    ("pinky", 17, 18, 19, 20),
)


def _distance(a, b):
    return math.sqrt(sum((getattr(a, axis) - getattr(b, axis)) ** 2
                         for axis in ("x", "y", "z")))


def _image_distance(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def _screen_distance(a, b, aspect):
    # MediaPipe normalizes x by width and y by height. Restore pixel aspect
    # before comparing directions or finger lengths on a widescreen webcam.
    return math.hypot((a.x - b.x) * aspect, a.y - b.y)


def _angle(a, b, c):
    first = [getattr(a, axis) - getattr(b, axis) for axis in ("x", "y", "z")]
    second = [getattr(c, axis) - getattr(b, axis) for axis in ("x", "y", "z")]
    length = math.sqrt(sum(x * x for x in first) * sum(x * x for x in second))
    if length < 1e-8:
        return 0.0
    cosine = sum(x * y for x, y in zip(first, second)) / length
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _clamp01(value):
    return min(1.0, max(0.0, value))


@dataclass(frozen=True)
class HandFeatures:
    """Only derived scalars and one transient tip position; no landmark array."""

    angles: tuple
    legacy_extended: tuple
    legacy_folded: tuple
    thumb_straight: bool
    thumb_vertical: bool
    loop_gap_ratio: float | None
    ok_extended: tuple
    basic_pose: str
    openness: float
    pinch_ratio: float
    pinched: bool
    roll_degrees: float
    pointer: tuple
    hand_scale: float
    aspect_ratio: float

    def confirmation(self):
        if self.thumb_straight and self.thumb_vertical and all(self.legacy_folded):
            return "thumbs_up"
        if self.loop_gap_ratio is not None and self.loop_gap_ratio <= 0.55 and len(self.ok_extended) == 3:
            return "ok"
        return "unknown"

    def diagnostics(self):
        # Never put pointer coordinates or landmark arrays in a debug log.
        return {
            "loop_gap_ratio": (round(self.loop_gap_ratio, 2)
                               if self.loop_gap_ratio is not None else None),
            "ok_extended": list(self.ok_extended),
            "index_pip_angle": round(self.angles[0]),
            "thumb_vertical": self.thumb_vertical,
            "basic_pose": self.basic_pose,
            "openness": round(self.openness, 2),
            "pinched": self.pinched,
            "roll_degrees": round(self.roll_degrees),
        }


def extract_hand_features(landmarks, world_landmarks=None, aspect_ratio=1.0):
    """Build one geometry snapshot from MediaPipe's 21 landmarks.

    Confirmation uses Alice's prior thresholds and unmodified image geometry.
    General poses use WonderSnap-like ratios with image aspect correction.
    """
    if landmarks is None or len(landmarks) != 21:
        return None
    if not math.isfinite(aspect_ratio) or aspect_ratio <= 0:
        return None
    points = (world_landmarks if world_landmarks is not None and
              len(world_landmarks) == 21 else landmarks)
    if any(not all(math.isfinite(getattr(p, axis)) for axis in ("x", "y", "z"))
           for p in landmarks) or any(
               not all(math.isfinite(getattr(p, axis)) for axis in ("x", "y", "z"))
               for p in points):
        return None
    if _distance(points[5], points[17]) < 1e-5:
        return None

    angles = tuple(_angle(points[mcp], points[pip], points[dip])
                   for _, mcp, pip, dip, _ in FINGERS)
    legacy_extended = tuple(
        angles[i] >= 155 and _distance(points[tip], points[mcp]) >
        1.5 * _distance(points[pip], points[mcp])
        for i, (_, mcp, pip, _, tip) in enumerate(FINGERS))
    legacy_folded = tuple(angles[i] <= 145 and not legacy_extended[i]
                          for i in range(4))
    thumb_straight = _angle(points[2], points[3], points[4]) >= 150
    image_palm = _image_distance(landmarks[5], landmarks[17])
    thumb_rise = landmarks[2].y - landmarks[4].y
    thumb_vertical = (thumb_rise > 0.6 * image_palm and
                      abs(landmarks[4].x - landmarks[2].x) < 0.65 * thumb_rise)
    loop_gap_ratio = None
    ok_extended = []
    if image_palm >= 1e-5:
        loop_gap_ratio = _image_distance(landmarks[4], landmarks[8]) / image_palm
        for i in (1, 2, 3):
            name, mcp, pip, _, tip = FINGERS[i]
            base = max(_distance(points[mcp], points[pip]), 1e-5)
            image_base = max(_image_distance(landmarks[mcp], landmarks[pip]), 1e-5)
            reach = _distance(points[mcp], points[tip]) / base
            image_reach = _image_distance(landmarks[mcp], landmarks[tip]) / image_base
            if ((angles[i] >= 140 and reach >= 1.25) or
                    (image_reach >= 1.75 and reach >= 1.15)):
                ok_extended.append(name)

    # These ratios are adapted from WonderSnap's open/fist/point/peace rules.
    # They do not grant any action or modify the confirmation classifier.
    scale = _screen_distance(landmarks[0], landmarks[9], aspect_ratio)
    if scale < 1e-5:
        return None
    wrist_tip = tuple(_screen_distance(landmarks[tip], landmarks[0], aspect_ratio)
                      for _, _, _, _, tip in FINGERS)
    wrist_pip = tuple(_screen_distance(landmarks[pip], landmarks[0], aspect_ratio)
                      for _, _, pip, _, _ in FINGERS)
    wrist_mcp = tuple(_screen_distance(landmarks[mcp], landmarks[0], aspect_ratio)
                      for _, mcp, _, _, _ in FINGERS)
    extended = tuple(wrist_tip[i] > 1.15 * wrist_pip[i] for i in range(4))
    curled = tuple(wrist_tip[i] < 1.25 * wrist_mcp[i] for i in range(4))
    thumb_ratio = _screen_distance(landmarks[4], landmarks[17], aspect_ratio) / scale
    if all(extended) and thumb_ratio > 1.1:
        basic_pose = "open"
    elif all(curled):
        basic_pose = "fist"
    elif extended[0] and extended[1] and curled[2] and curled[3]:
        basic_pose = "peace"
    elif extended[0] and all(curled[1:]):
        basic_pose = "point"
    else:
        basic_pose = "other"
    openness = sum(_clamp01((wrist_tip[i] / max(wrist_mcp[i], 1e-6)
                             - 1.05) / 0.70) for i in range(4)) / 5
    openness += 0.2 * _clamp01((thumb_ratio - 0.9) / 0.65)
    pinch_ratio = _screen_distance(landmarks[4], landmarks[8], aspect_ratio) / scale
    roll = math.degrees(math.atan2((landmarks[9].x - landmarks[0].x) * aspect_ratio,
                                   -(landmarks[9].y - landmarks[0].y)))
    return HandFeatures(
        angles, legacy_extended, legacy_folded, thumb_straight, thumb_vertical,
        loop_gap_ratio, tuple(ok_extended), basic_pose, openness, pinch_ratio,
        pinch_ratio < 0.32 and basic_pose != "fist", roll,
        (landmarks[8].x, landmarks[8].y), scale, aspect_ratio)
