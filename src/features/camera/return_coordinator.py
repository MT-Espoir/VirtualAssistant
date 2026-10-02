"""Join camera and desktop return evidence without changing SALM presence.

Camera observations and episode state live only in memory. Greeting admission is
separate from wording: shadow/local/llm all use the same absence episode reducer.
"""

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class WelcomeRequest:
    source: str
    absence_episode_id: str
    absence_seconds: float
    observed_monotonic: float = 0.0
    generation: object = None


class WorkstationReturnCoordinator:
    def __init__(self, mode="shadow", on_camera_welcome=None,
                 on_desktop_welcome=None, debug=None,
                 min_absence_seconds=120, cooldown_seconds=300):
        self.mode = mode if mode in {"off", "shadow", "local", "llm"} else "shadow"
        self.on_camera_welcome = on_camera_welcome
        self.on_desktop_welcome = on_desktop_welcome
        self.debug = debug
        self.min_absence = max(30.0, float(min_absence_seconds))
        self.cooldown = max(0.0, float(cooldown_seconds))
        self._lock = threading.Lock()
        self._camera_generation = None
        self._camera_observation_state = "unknown"
        self._camera_seen_near = False
        self._last_near_at = 0.0
        self._camera_absence_since = None
        self._camera_absence_valid = 0.0
        self._camera_last_absence_sample = None
        self._camera_unknown_since = None
        self._camera_last_sample = 0.0
        self._episode_counter = 0
        self._last_camera_episode = None  # (absence_start, return_time, id, attempted)
        self._last_desktop_return = None  # (absence_start, return_time)
        self._desktop_absence_since = None
        self._desktop_return_transition_seen = False
        self._session_blocked = True
        self._recent_input = False
        self._activity_at = 0.0
        self._last_attempt_at = float("-inf")

    def _log(self, message, data=None, level="INFO"):
        if self.debug is not None:
            self.debug("camera", message, data or {}, level=level)

    def observe_activity(self, state, snapshot):
        now = float(snapshot.monotonic)
        raw_presence = getattr(state, "presence", None)
        raw_display = getattr(snapshot, "display", None)
        presence = getattr(raw_presence, "value", raw_presence)
        display = getattr(raw_display, "value", raw_display)
        with self._lock:
            self._activity_at = now
            self._session_blocked = (snapshot.session_locked is True or
                                     presence == "suspended" or display == "off")
            idle = snapshot.idle_seconds
            self._recent_input = idle is not None and idle < 30
            if presence in {"away", "suspended"}:
                if self._desktop_absence_since is None:
                    self._desktop_absence_since = now
                self._desktop_return_transition_seen = False
            elif presence == "present" and self._desktop_absence_since is not None:
                # Keep the interval for the same tick's ReturnEvent callback.
                if self._desktop_return_transition_seen:
                    self._desktop_absence_since = None
                self._desktop_return_transition_seen = True
            elif presence not in {"unknown", "idle_candidate"}:
                self._desktop_absence_since = None
                self._desktop_return_transition_seen = False

    def observe_camera(self, observation):
        if self.mode == "off":
            return
        now = float(observation.get("observed_monotonic") or time.monotonic())
        state = observation.get("observation_state", "unknown")
        generation = observation.get("generation")
        message = None
        payload = None
        welcome = False
        request = None
        with self._lock:
            if generation != self._camera_generation:
                self._camera_generation = generation
                self._camera_seen_near = False
                self._camera_absence_since = None
                self._camera_absence_valid = 0.0
                self._camera_last_absence_sample = None
                self._camera_unknown_since = None
                self._last_near_at = 0.0
            if (self._camera_last_sample and now - self._camera_last_sample > 2.5):
                self._camera_seen_near = False
                self._camera_absence_since = None
                self._camera_absence_valid = 0.0
                self._camera_last_absence_sample = None
                self._camera_unknown_since = None
                self._last_near_at = 0.0
            self._camera_last_sample = now
            if (observation.get("calibration") != "ready" or
                    observation.get("quality") != "good"):
                state = "unknown"
            self._camera_observation_state = state
            if state == "unknown":
                if self._camera_unknown_since is None:
                    self._camera_unknown_since = now
                self._camera_last_absence_sample = None
                if now - self._camera_unknown_since > 10:
                    self._camera_absence_since = None
                    self._camera_absence_valid = 0.0
                    self._camera_seen_near = False
            elif state == "near":
                absence = self._camera_absence_since
                if absence is not None and self._camera_absence_valid >= self.min_absence:
                    self._episode_counter += 1
                    episode_id = f"return-episode-{self._episode_counter}"
                    blocked = (self._session_blocked or
                               now - self._activity_at > 3 or
                               now - self._last_attempt_at < self.cooldown)
                    desktop = self._last_desktop_return
                    duplicate = bool(desktop and desktop[0] <= now and
                                     desktop[1] >= absence and
                                     now - desktop[1] <= 60)
                    welcome = (self.mode in {"local", "llm"} and not blocked and not duplicate and
                               self.on_camera_welcome is not None)
                    if welcome:
                        self._last_attempt_at = now
                        request = WelcomeRequest(
                            "camera", episode_id, self._camera_absence_valid,
                            observed_monotonic=now, generation=generation)
                    self._last_camera_episode = (absence, now, episode_id, welcome)
                    message = "Workstation return candidate"
                    payload = {"camera_id": observation.get("camera_id"),
                               "episode_id": episode_id, "mode": self.mode,
                               "absence_seconds": round(self._camera_absence_valid),
                               "accepted": welcome, "blocked": blocked,
                               "duplicate_desktop": duplicate}
                self._camera_seen_near = True
                self._last_near_at = now
                self._camera_absence_since = None
                self._camera_absence_valid = 0.0
                self._camera_last_absence_sample = None
                self._camera_unknown_since = None
            elif state in {"far", "no_face"} and self._camera_seen_near:
                if state == "no_face" and self._recent_input:
                    self._camera_absence_since = None
                    self._camera_absence_valid = 0.0
                    self._camera_last_absence_sample = None
                elif self._camera_absence_since is None:
                    self._camera_absence_since = now
                    self._camera_last_absence_sample = now
                    self._camera_unknown_since = None
                else:
                    if self._camera_last_absence_sample is not None:
                        self._camera_absence_valid += max(
                            0.0, now - self._camera_last_absence_sample)
                    self._camera_last_absence_sample = now
                    self._camera_unknown_since = None
        if message:
            self._log(message, payload, "SUCCESS" if welcome else "INFO")
        if welcome:
            self.on_camera_welcome(request)

    def camera_request_current(self, request, max_age_seconds=10):
        """Recheck after dispatch waits/LLM latency; stale returns cannot speak."""
        now = time.monotonic()
        with self._lock:
            episode = self._last_camera_episode
            return bool(
                request.source == "camera" and episode and episode[3] and
                episode[2] == request.absence_episode_id and
                request.generation == self._camera_generation and
                0 <= now - request.observed_monotonic <= max_age_seconds and
                0 <= now - self._camera_last_sample <= 2.5 and
                0 <= now - self._activity_at <= 3 and
                self._camera_observation_state == "near" and
                self._camera_absence_since is None and not self._session_blocked)

    def on_desktop_return(self, event):
        now = time.monotonic()
        with self._lock:
            absence = self._desktop_absence_since
            self._desktop_absence_since = None
            self._desktop_return_transition_seen = False
            camera = self._last_camera_episode
            same_interval = bool(camera and absence is not None and
                                 absence <= camera[1] and now >= camera[0])
            still_seated = (self._camera_seen_near and
                            self._camera_absence_since is None and
                            now - self._camera_last_sample <= 3)
            duplicate = bool(self.mode in {"local", "llm"} and camera and camera[3] and
                             (same_interval or still_seated) and
                             # A new observed departure opens a new episode.
                             self._camera_absence_since is None)
            if absence is not None:
                self._last_desktop_return = (absence, now)
            if not duplicate:
                self._last_attempt_at = now
        if duplicate:
            self._log("Desktop return greeting merged with camera episode", {
                "episode_id": camera[2]})
            return
        if self.on_desktop_welcome is not None:
            self.on_desktop_welcome(event)
