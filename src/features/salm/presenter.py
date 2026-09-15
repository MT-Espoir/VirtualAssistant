"""Primitive thuần cho care pulse; Tkinter chỉ tiêu thụ các giá trị này."""

import math

CARE_PULSE_SECONDS = 1.8
CARE_PULSE_TICK_MS = 100
CARE_MIN_FACTOR = 0.82


def care_opacity(base_opacity, progress, min_factor=CARE_MIN_FACTOR):
    """Một nhịp thở cosine: base -> base*factor -> base, không sáng hơn base."""
    base = max(0.0, min(1.0, float(base_opacity)))
    progress = max(0.0, min(1.0, float(progress)))
    depth = 1.0 - max(0.0, min(1.0, float(min_factor)))
    factor = 1.0 - depth * math.sin(math.pi * progress)
    return base * factor


def care_progress_steps(duration=CARE_PULSE_SECONDS, tick_ms=CARE_PULSE_TICK_MS):
    count = max(1, round(float(duration) * 1000.0 / max(1, int(tick_ms))))
    return tuple(index / count for index in range(count + 1))
