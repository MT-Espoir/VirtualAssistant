"""Reducer thuần: ActivitySnapshot -> DerivedState."""

from datetime import timedelta

from features.salm.models import (
    ActivityKind,
    ActivitySnapshot,
    Confidence,
    DerivedState,
    DisplayState,
    MediaKind,
    Presence,
)


INTERACTIVE_IDLE_SECONDS = 30.0
AWAY_CONFIRM_SECONDS = 10 * 60.0


def _same_start(previous, signature, snapshot, infer_idle_start=False):
    if previous is not None and previous.signature() == signature:
        return previous.since_monotonic, previous.since_wall
    # IDLE_CANDIDATE -> AWAY chỉ là confidence tăng lên cho CÙNG một idle gap.
    # Không được làm `away_since` nhảy tới đúng tick phút thứ 10.
    if (previous is not None and infer_idle_start
            and previous.activity == ActivityKind.AMBIGUOUS_IDLE):
        return previous.since_monotonic, previous.since_wall
    if infer_idle_start and snapshot.idle_seconds is not None:
        idle = max(0.0, snapshot.idle_seconds)
        return snapshot.monotonic - idle, snapshot.wall_time - timedelta(seconds=idle)
    return snapshot.monotonic, snapshot.wall_time


def derive_state(snapshot: ActivitySnapshot, previous=None,
                 interactive_idle=INTERACTIVE_IDLE_SECONDS,
                 away_confirm=AWAY_CONFIRM_SECONDS) -> DerivedState:
    """Suy trạng thái theo thứ tự ưu tiên của spec; không I/O, replay được."""
    evidence = []
    foreground = snapshot.foreground_app
    media_apps = set(snapshot.gsmtc_apps) | set(snapshot.audible_apps)
    foreground_media = bool(foreground and foreground in media_apps)
    any_media = bool(media_apps)

    if snapshot.suspended:
        presence = Presence.SUSPENDED
        activity = ActivityKind.NONE
        media = MediaKind.BACKGROUND_AUDIO if any_media else MediaKind.NONE
        confidence = Confidence.HIGH
        evidence.append("suspended")
    elif snapshot.session_locked is True or snapshot.display == DisplayState.OFF:
        presence = Presence.AWAY
        activity = ActivityKind.NONE
        media = MediaKind.BACKGROUND_AUDIO if any_media else MediaKind.NONE
        confidence = Confidence.HIGH
        evidence.append("session_locked" if snapshot.session_locked else "display_off")
    elif snapshot.idle_seconds is not None and snapshot.idle_seconds < interactive_idle:
        presence = Presence.PRESENT
        activity = ActivityKind.ACTIVE_INTERACTIVE
        media = (MediaKind.FOREGROUND_MEDIA if foreground_media else
                 MediaKind.BACKGROUND_AUDIO if any_media else MediaKind.NONE)
        confidence = Confidence.HIGH
        evidence.append("recent_input")
    elif foreground_media and snapshot.display != DisplayState.OFF:
        presence = Presence.PRESENT
        activity = ActivityKind.PASSIVE_VIEWING
        media = MediaKind.FOREGROUND_MEDIA
        if foreground in snapshot.gsmtc_apps:
            confidence = Confidence.HIGH
            evidence.append("gsmtc_playing")
        else:
            confidence = Confidence.MEDIUM
            evidence.append("wasapi_audible")
        evidence.append("media_foreground")
        if snapshot.foreground_fullscreen:
            evidence.append("fullscreen")
    elif snapshot.idle_seconds is not None and snapshot.idle_seconds >= away_confirm:
        # Presence có thể coi là away, nhưng screen exposure vẫn mơ hồ khi display bật:
        # người dùng có thể đang đọc một trang tĩnh.
        presence = Presence.AWAY
        activity = ActivityKind.AMBIGUOUS_IDLE
        media = MediaKind.BACKGROUND_AUDIO if any_media else MediaKind.NONE
        confidence = Confidence.MEDIUM
        evidence.extend(("idle_10m", "screen_presence_ambiguous"))
    elif snapshot.idle_seconds is not None:
        presence = Presence.IDLE_CANDIDATE
        activity = ActivityKind.AMBIGUOUS_IDLE
        media = MediaKind.BACKGROUND_AUDIO if any_media else MediaKind.NONE
        confidence = Confidence.LOW
        evidence.append("idle_candidate")
    else:
        presence = Presence.UNKNOWN
        activity = ActivityKind.NONE
        media = MediaKind.UNKNOWN_PLAYBACK if any_media else MediaKind.NONE
        confidence = Confidence.LOW
        evidence.append("input_unavailable")

    if snapshot.display == DisplayState.DIM:
        evidence.append("display_dim")
    elif snapshot.display == DisplayState.ON:
        evidence.append("display_on")
    if snapshot.meeting_open is True:
        evidence.append("meeting_open")

    signature = (presence, snapshot.display, activity, media, foreground,
                 snapshot.meeting_open)
    since_mono, since_wall = _same_start(
        previous, signature, snapshot,
        infer_idle_start=activity == ActivityKind.AMBIGUOUS_IDLE,
    )
    return DerivedState(
        presence=presence,
        display=snapshot.display,
        activity=activity,
        media=media,
        primary_app=foreground,
        confidence=confidence,
        evidence=tuple(evidence),
        since_monotonic=since_mono,
        since_wall=since_wall,
        meeting_open=snapshot.meeting_open,
    )
