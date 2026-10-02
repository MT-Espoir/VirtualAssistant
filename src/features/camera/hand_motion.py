"""Transient hand pose and motion analysis; no OS or Agent side effects."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class HandTemporalResult:
    stable_pose: str = "unknown"
    pose_changed: bool = False
    swipe: str | None = None  # Image direction; UI mirroring is deliberately unresolved.
    pinch_started: bool = False
    pinch_ended: bool = False


class HandTemporalTracker:
    """Time-based pose and swipe primitives for the existing single-hand worker.

    Outputs are diagnostic only. A future interaction mode must own the mapping
    from these observations to cursor actions and run at an adequate frame rate.
    """

    def __init__(self, pose_hold_seconds=0.18, max_gap_seconds=0.6,
                 swipe_window_seconds=1.0):
        self.pose_hold_seconds = pose_hold_seconds
        self.max_gap_seconds = max_gap_seconds
        self.swipe_window_seconds = swipe_window_seconds
        self.reset()

    def reset(self):
        self._last_at = None
        self._candidate = "unknown"
        self._candidate_at = 0.0
        self._candidate_count = 0
        self._stable = "unknown"
        self._pinch_count = 0
        self._release_count = 0
        self._pinched = False
        self._swipe_anchor = None
        self._point_samples = 0
        self._swipe_fired = False

    def observe(self, features, captured_at):
        if features is None or not math.isfinite(captured_at):
            self.reset()
            return HandTemporalResult()
        if self._last_at is not None and (
                captured_at <= self._last_at or
                captured_at - self._last_at > self.max_gap_seconds):
            self.reset()
        self._last_at = captured_at

        pose = features.basic_pose
        if pose != self._candidate:
            self._candidate = pose
            self._candidate_at = captured_at
            self._candidate_count = 1
        else:
            self._candidate_count += 1
        changed = False
        if (pose != self._stable and self._candidate_count >= 2 and
                captured_at - self._candidate_at >= self.pose_hold_seconds):
            self._stable = pose
            changed = True

        pinch_started = pinch_ended = False
        if features.pinched:
            self._pinch_count += 1
            self._release_count = 0
            if not self._pinched and self._pinch_count >= 2:
                self._pinched = True
                pinch_started = True
        else:
            self._pinch_count = 0
            self._release_count += 1
            if self._pinched and self._release_count >= 2:
                self._pinched = False
                pinch_ended = True

        swipe = None
        if self._stable != "point" or pose != "point":
            self._swipe_anchor = None
            self._point_samples = 0
            self._swipe_fired = False
        elif self._swipe_anchor is None:
            self._swipe_anchor = (features.pointer, features.hand_scale, captured_at)
            self._point_samples = 1
        else:
            self._point_samples += 1
            (start_x, start_y), scale, started_at = self._swipe_anchor
            elapsed = captured_at - started_at
            if elapsed > self.swipe_window_seconds:
                self._swipe_anchor = (features.pointer, features.hand_scale, captured_at)
                self._point_samples = 1
            elif not self._swipe_fired and self._point_samples >= 3:
                # x and y are normalized by different dimensions. Correct x
                # before comparing trajectory with the scale-normalized hand.
                dx = (features.pointer[0] - start_x) * features.aspect_ratio
                dy = features.pointer[1] - start_y
                if (abs(dx) >= 1.3 * scale and
                        abs(dx) >= 1.8 * abs(dy) and
                        elapsed >= 0.15):
                    swipe = "image_swipe_right" if dx > 0 else "image_swipe_left"
                    self._swipe_fired = True

        return HandTemporalResult(self._stable, changed, swipe,
                                  pinch_started, pinch_ended)
