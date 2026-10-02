"""Kiểu dữ liệu trung lập của SALM — không phụ thuộc Win32, UI hay storage."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple


class _TextEnum(str, Enum):
    def __str__(self):
        return self.value


class Presence(_TextEnum):
    PRESENT = "present"
    IDLE_CANDIDATE = "idle_candidate"
    AWAY = "away"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class DisplayState(_TextEnum):
    ON = "on"
    DIM = "dim"
    OFF = "off"
    UNKNOWN = "unknown"


class ActivityKind(_TextEnum):
    ACTIVE_INTERACTIVE = "active_interactive"
    PASSIVE_VIEWING = "passive_viewing"
    AMBIGUOUS_IDLE = "ambiguous_idle"
    NONE = "none"


class MediaKind(_TextEnum):
    NONE = "none"
    FOREGROUND_MEDIA = "foreground_media"
    BACKGROUND_AUDIO = "background_audio"
    UNKNOWN_PLAYBACK = "unknown_playback"


class Confidence(_TextEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ActivitySnapshot:
    """Một snapshot trung tính từ collector.

    `wall_time` chỉ để hiển thị/lưu; mọi duration dùng `monotonic`.
    App ID đã được normalize, không chứa title/URL/command line.
    """

    monotonic: float
    wall_time: datetime
    idle_seconds: Optional[float] = None
    foreground_app: Optional[str] = None
    foreground_pid: Optional[int] = None
    foreground_fullscreen: bool = False
    display: DisplayState = DisplayState.UNKNOWN
    session_locked: Optional[bool] = None
    suspended: bool = False
    running_apps: FrozenSet[str] = frozenset()
    gsmtc_apps: FrozenSet[str] = frozenset()
    audible_apps: FrozenSet[str] = frozenset()
    meeting_open: Optional[bool] = None
    # Khoảng sleep vừa hoàn tất do power watcher đo bằng monotonic; chỉ dùng để
    # hoàn trả clock, không phải activity/app duration.
    no_screen_break_seconds: float = 0.0


@dataclass(frozen=True)
class DerivedState:
    presence: Presence
    display: DisplayState
    activity: ActivityKind
    media: MediaKind
    primary_app: Optional[str]
    confidence: Confidence
    evidence: Tuple[str, ...]
    since_monotonic: float
    since_wall: datetime
    meeting_open: Optional[bool] = None

    def signature(self):
        """Những trường làm đóng/mở interval; bỏ confidence/evidence dao động nhẹ."""
        return (self.presence, self.display, self.activity, self.media,
                self.primary_app, self.meeting_open)


@dataclass(frozen=True)
class ActivityInterval:
    start: datetime
    end: datetime
    duration_seconds: float
    presence: Presence
    display: DisplayState
    activity: ActivityKind
    media: MediaKind
    primary_app: Optional[str]
    confidence: Confidence
    evidence: Tuple[str, ...]
    meeting_open: Optional[bool] = None

    def to_record(self) -> dict:
        return {
            "kind": "interval",
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "duration_seconds": round(max(0.0, self.duration_seconds), 3),
            "presence": self.presence.value,
            "display": self.display.value,
            "activity": self.activity.value,
            "media": self.media.value,
            "primary_app": self.primary_app,
            "confidence": self.confidence.value,
            "evidence": list(self.evidence),
            "meeting_open": self.meeting_open,
        }


@dataclass(frozen=True)
class BreakOpportunity:
    clock: str
    level: str
    at: datetime
    value_seconds: float
    threshold_seconds: float
    reason_codes: Tuple[str, ...]
    cycle_id: int = 0

    def to_record(self) -> dict:
        return {
            "kind": "opportunity",
            "at": self.at.isoformat(),
            "clock": self.clock,
            "level": self.level,
            "value_seconds": round(self.value_seconds, 3),
            "threshold_seconds": round(self.threshold_seconds, 3),
            "reason_codes": list(self.reason_codes),
            "cycle_id": self.cycle_id,
        }


@dataclass
class AppDurations:
    running: float = 0.0
    foreground: float = 0.0
    interactive: float = 0.0
    passive_viewing: float = 0.0
    background_audio: float = 0.0

    def add(self, field_name: str, seconds: float):
        setattr(self, field_name, getattr(self, field_name) + max(0.0, seconds))

    def to_dict(self) -> dict:
        return {name: round(max(0.0, getattr(self, name)), 3)
                for name in ("running", "foreground", "interactive",
                             "passive_viewing", "background_audio")}


@dataclass
class DailyMetrics:
    work_engagement: float = 0.0
    screen_exposure: float = 0.0
    unknown_duration: float = 0.0
    idle_gap: float = 0.0
    confirmed_break: float = 0.0
    apps: Dict[str, AppDurations] = field(default_factory=dict)
    circadian_coverage: float = 0.0
    circadian_interactive: List[float] = field(
        default_factory=lambda: [0.0] * 48)
    timezone_offset_minutes: Optional[int] = None
    timezone_changed: bool = False

    def app(self, app_id: str) -> AppDurations:
        if app_id not in self.apps:
            self.apps[app_id] = AppDurations()
        return self.apps[app_id]

    def add_circadian(self, when: datetime, seconds: float, *, interactive=False):
        """Accumulate privacy-reduced half-hour buckets in the snapshot's local time."""
        seconds = max(0.0, float(seconds or 0))
        if not seconds:
            return
        local = when if when.tzinfo else when.astimezone()
        offset = local.utcoffset()
        offset_minutes = int(offset.total_seconds() // 60) if offset is not None else None
        if self.timezone_offset_minutes is None:
            self.timezone_offset_minutes = offset_minutes
        elif offset_minutes != self.timezone_offset_minutes:
            self.timezone_changed = True
        self.circadian_coverage += seconds
        if interactive:
            bucket = max(0, min(47, local.hour * 2 + local.minute // 30))
            self.circadian_interactive[bucket] += seconds

    def to_dict(self) -> dict:
        return {
            "work_engagement": round(self.work_engagement, 3),
            "screen_exposure": round(self.screen_exposure, 3),
            "unknown_duration": round(self.unknown_duration, 3),
            "idle_gap": round(self.idle_gap, 3),
            "confirmed_break": round(self.confirmed_break, 3),
            "apps": {name: value.to_dict() for name, value in sorted(self.apps.items())},
            "circadian": {
                "schema_version": 1,
                "coverage_seconds": round(self.circadian_coverage, 3),
                "interactive_seconds_by_half_hour": [
                    round(max(0.0, value), 3)
                    for value in self.circadian_interactive[:48]
                ],
                "timezone_offset_minutes": self.timezone_offset_minutes,
                "timezone_changed": bool(self.timezone_changed),
            },
        }
