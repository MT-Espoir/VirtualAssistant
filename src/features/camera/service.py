"""Local webcam pipeline: one capture owner and bounded consumers."""

import logging
import os
import threading
import time
from collections import deque

from features.camera.face_auth import (MATCH_THRESHOLD, FaceEngine,
                                       OwnerTemplateStore, detect_yunet,
                                       match_score, model_path)
from features.camera.pipeline import FramePacket, LatestFrame, PresenceOutbox, utc_now
from features.camera.head_motion import HeadMotionTracker
from features.camera.hand_motion import HandTemporalTracker
from features.camera.hand_preview import draw_hand_skeleton
from features.camera.workstation import ProximityEstimator

logger = logging.getLogger(__name__)


class CameraService:
    def __init__(self, iot_client, room_id="bedroom", camera_index=0,
                 debug_sink=None, preview_enabled=False, template_store=None,
                 gesture_handler=None, camera_id="workstation-webcam",
                 camera_label="Webcam máy tính", camera_role="workstation_facing",
                 proximity_calibration_path=None, proximity_handler=None,
                 head_handler=None):
        self.room_id = room_id
        self.camera_index = camera_index
        self.camera_id = camera_id
        self.camera_label = camera_label
        self.camera_role = (camera_role if camera_role in
                            ("workstation_facing", "room_observation", "unknown")
                            else "unknown")
        self._proximity = ProximityEstimator(
            camera_id, camera_index, proximity_calibration_path)
        self._head_motion = HeadMotionTracker()
        self._proximity_handler = proximity_handler
        self._head_handler = head_handler
        self._visual_cancel_handler = None
        self._last_proximity_log = 0.0
        self._last_proximity_state = None
        self._sample_log_at = {}
        self._sample_log_dropped = {}
        self._debug_sink = debug_sink
        self._preview_enabled = bool(preview_enabled)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._pause_epoch = 0
        self._lock = threading.RLock()
        self._frames = LatestFrame()
        self._outbox = PresenceOutbox(iot_client, room_id, self._debug)
        self._threads = []
        self._state = "stopped"
        self._present = None
        self._face_in_frame = None
        self._face_count = None
        self._presence_reason = "unknown"
        self._presence_sequence = None
        self._last_seen_at = None
        self._last_frame_at = None
        self._last_frame_monotonic = 0.0
        self._last_error = None
        self._frame_sequence = 0
        self._generation = 0
        self._preview_jpeg = None
        self._preview_at = None
        self._preview_sequence = -1
        self._preview_mode = None
        self._last_overlay_monotonic = 0.0
        self._preview_faces = ()
        self._preview_faces_at = 0.0
        self._capture_fps = 0.0
        self._requested_fps = 40
        self._last_presence_inference_monotonic = 0.0
        self._presence_latency_ms = None
        self._presence_state = "starting"
        self._face_latency_ms = None
        self._store = template_store or OwnerTemplateStore()
        self._face_enabled = False
        self._face_state = "disabled"
        self._face_error = None
        self._face_score = None
        self._face_suggestion = "unknown"
        self._face_suggestion_at = 0.0
        self._face_match_quality = "unknown"
        self._enroll_samples = []
        self._enroll_last_at = 0.0
        self._enroll_quality = "unknown"
        self._emotion_debug_visible = False
        self._emotion_control_visible = False
        self._emotion_enabled = False
        self._emotion_epoch = 0
        self._emotion_state = "disabled"
        self._emotion_quality = "unknown"
        self._emotion_label = "unknown"
        self._emotion_confidence = None
        self._emotion_latency_ms = None
        self._emotion_sequence = None
        self._emotion_error = None
        self._emotion_at = 0.0
        self._gesture_handler = gesture_handler
        self._gesture_enabled = True
        self._gesture_state = "starting"
        self._gesture_quality = "unknown"
        self._gesture_label = "unknown"
        self._gesture_basic_pose = "unknown"
        self._gesture_hand_count = 0
        self._gesture_latency_ms = None
        self._gesture_sequence = None
        self._gesture_error = None
        self._gesture_at = 0.0
        self._gesture_fps = 0.0

    def start(self):
        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop.clear()
        self._paused.clear()
        with self._lock:
            self._state = "starting"
        self._outbox.start()
        self._threads = [
            threading.Thread(target=self._capture_loop, name="alice-webcam", daemon=True),
            threading.Thread(target=self._preview_loop, name="alice-camera-preview", daemon=True),
            threading.Thread(target=self._presence_loop, name="alice-camera-presence", daemon=True),
            threading.Thread(target=self._face_loop, name="alice-camera-face", daemon=True),
            threading.Thread(target=self._emotion_loop, name="alice-camera-emotion", daemon=True),
            threading.Thread(target=self._gesture_loop, name="alice-camera-gesture", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self):
        with self._lock:
            self._state = "stopping"
        self._cancel_visual_confirmation()
        self._stop.set()
        self._paused.clear()
        self._frames.clear()
        for thread in self._threads:
            thread.join(timeout=5)
        self._outbox.stop()
        with self._lock:
            self._state = "stopped"
            self._present = None
            self._face_in_frame = None
            self._face_count = None
            self._presence_reason = "unknown"
            self._presence_sequence = None
            self._preview_jpeg = None
            self._preview_at = None
            self._preview_sequence = -1
            self._preview_mode = None
            self._preview_faces = ()
            self._capture_fps = 0.0
            self._face_suggestion = "unknown"
            self._face_score = None
            self._face_match_quality = "unknown"
            self._emotion_enabled = False
            self._clear_emotion_locked("disabled")
            self._clear_gesture_locked("stopped")
            self._proximity.reset()
            self._head_motion.reset()

    def pause(self):
        self._pause_epoch += 1
        self._paused.set()
        self._cancel_visual_confirmation()
        self._frames.clear()
        with self._lock:
            self._generation += 1
            self._state = "paused"
            self._present = None
            self._face_in_frame = None
            self._face_count = None
            self._presence_reason = "unknown"
            self._presence_sequence = None
            self._preview_jpeg = None
            self._preview_at = None
            self._preview_sequence = -1
            self._preview_mode = None
            self._preview_faces = ()
            self._capture_fps = 0.0
            self._face_suggestion = "unknown"
            self._face_score = None
            self._face_match_quality = "unknown"
            self._clear_emotion_locked("paused")
            self._clear_gesture_locked("paused")
            self._enroll_samples.clear()
            self._proximity.reset()
            self._head_motion.reset()
            self._enroll_quality = "unknown"
            if self._face_state == "enrolling":
                self._face_state = "ready" if self._store.exists() else "not_enrolled"
            self._outbox.submit(False)
        self._debug("Camera paused by user")

    def resume(self):
        if self._stop.is_set():
            return
        with self._lock:
            self._state = "starting"
        self._paused.clear()
        self._debug("Camera resumed by user")

    def set_preview_enabled(self, enabled):
        with self._lock:
            self._preview_enabled = bool(enabled)
            if not enabled:
                self._preview_jpeg = None
                self._preview_at = None
                self._preview_sequence = -1
                self._preview_mode = None
                self._last_overlay_monotonic = 0.0
                self._preview_faces = ()

    def set_gesture_handler(self, handler):
        """Receive a debounced, typed gesture; handler runs on gesture worker."""
        with self._lock:
            self._gesture_handler = handler

    def set_proximity_handler(self, handler):
        with self._lock:
            self._proximity_handler = handler

    def set_head_handler(self, handler):
        with self._lock:
            self._head_handler = handler

    def set_visual_cancel_handler(self, handler):
        with self._lock:
            self._visual_cancel_handler = handler

    def visual_input_active(self):
        with self._lock:
            return (self._state == "available" and not self._paused.is_set() and
                    not self._stop.is_set())

    def _cancel_visual_confirmation(self):
        with self._lock:
            handler = self._visual_cancel_handler
        if handler is not None:
            try:
                handler()
            except Exception:
                logger.warning("Could not cancel visual confirmation", exc_info=True)

    def calibrate_proximity(self):
        with self._lock:
            if self.camera_role != "workstation_facing" or self._state != "available":
                raise RuntimeError("Workstation webcam must be available")
            self._proximity.begin_calibration()
        self._debug("Proximity calibration started", {"camera_id": self.camera_id})

    def proximity_status(self):
        with self._lock:
            return self._proximity.status()

    def head_motion_status(self):
        with self._lock:
            return self._head_motion.status()

    def _clear_gesture_locked(self, state):
        self._gesture_state = state
        self._gesture_quality = "unknown"
        self._gesture_label = "unknown"
        self._gesture_basic_pose = "unknown"
        self._gesture_hand_count = 0
        self._gesture_latency_ms = None
        self._gesture_sequence = None
        self._gesture_at = 0.0
        self._gesture_fps = 0.0
        self._gesture_error = None

    def gesture_status(self):
        with self._lock:
            fresh = self._gesture_at and time.monotonic() - self._gesture_at <= 2
            state = ("stale" if self._gesture_state == "ready" and not fresh
                     else self._gesture_state)
            return {
                "enabled": self.camera_role == "workstation_facing" and self._gesture_enabled, "state": state,
                "quality": self._gesture_quality if fresh else "unknown",
                "label": self._gesture_label if fresh else "unknown",
                "basic_pose": self._gesture_basic_pose if fresh else "unknown",
                "hand_count": self._gesture_hand_count if fresh else 0,
                "latency_ms": self._gesture_latency_ms,
                "inference_fps": round(self._gesture_fps, 1),
                "sequence": self._gesture_sequence if fresh else None,
                "error": self._gesture_error,
            }

    def set_emotion_debug_visible(self, visible):
        """Emotion has no consumer when the debug panel is hidden."""
        with self._lock:
            self._emotion_debug_visible = bool(visible)
            if not visible and not self._emotion_control_visible:
                self._emotion_epoch += 1
                self._emotion_enabled = False
                self._clear_emotion_locked("disabled")

    def set_emotion_control_visible(self, visible):
        with self._lock:
            self._emotion_control_visible = bool(visible)

    def set_gesture_enabled(self, enabled):
        with self._lock:
            self._gesture_enabled = bool(enabled)
            if not enabled:
                self._clear_gesture_locked("disabled")

    def set_emotion_enabled(self, enabled):
        with self._lock:
            if enabled and self.camera_role != "workstation_facing":
                raise RuntimeError("Emotion requires a workstation-facing webcam")
            if enabled and not (self._emotion_control_visible or
                                self._debug_sink is not None and self._emotion_debug_visible):
                raise RuntimeError("Emotion requires the visible debug panel")
            self._emotion_epoch += 1
            self._emotion_enabled = bool(enabled)
            self._clear_emotion_locked("loading" if enabled else "disabled")
        self._debug("Emotion enabled" if enabled else "Emotion disabled")

    def _clear_emotion_locked(self, state):
        self._emotion_state = state
        self._emotion_quality = "unknown"
        self._emotion_label = "unknown"
        self._emotion_confidence = None
        self._emotion_latency_ms = None
        self._emotion_sequence = None
        self._emotion_error = None
        self._emotion_at = 0.0

    def emotion_status(self):
        """Diagnostics used only by the debug panel; excluded from ordinary status()."""
        with self._lock:
            fresh = self._emotion_at and time.monotonic() - self._emotion_at <= 3
            state = ("stale" if self._emotion_enabled and
                     self._emotion_state == "ready" and not fresh else self._emotion_state)
            return {
                "enabled": self._emotion_enabled,
                "state": state,
                "quality": self._emotion_quality if fresh else "unknown",
                "label": self._emotion_label if fresh else "unknown",
                "confidence": self._emotion_confidence if fresh else None,
                "latency_ms": self._emotion_latency_ms,
                "sequence": self._emotion_sequence if fresh else None,
                "error": self._emotion_error,
            }

    def set_face_enabled(self, enabled):
        with self._lock:
            if enabled and self.camera_role != "workstation_facing":
                raise RuntimeError("Face suggestion requires a workstation-facing webcam")
            self._face_enabled = bool(enabled)
            self._face_state = "loading" if enabled else "disabled"
            self._face_error = None
            self._face_suggestion = "unknown"
            self._face_score = None
            self._face_match_quality = "unknown"
            if not enabled:
                self._enroll_samples.clear()

    def begin_enrollment(self):
        if self.camera_role != "workstation_facing":
            raise RuntimeError("Enrollment requires a workstation-facing webcam")
        if self._paused.is_set() or self._stop.is_set() or self._state != "available":
            raise RuntimeError("Camera must be running to enroll")
        with self._lock:
            self._face_enabled = True
            self._face_state = "enrolling"
            self._face_error = None
            self._enroll_samples.clear()
            self._enroll_last_at = 0.0
            self._enroll_quality = "unknown"
            self._face_suggestion = "unknown"
            self._face_score = None
            self._face_match_quality = "unknown"

    def cancel_enrollment(self):
        with self._lock:
            self._enroll_samples.clear()
            self._enroll_quality = "unknown"
            self._face_state = "ready" if self._store.exists() else "not_enrolled"

    def delete_template(self):
        with self._lock:
            self._face_enabled = False
            self._face_state = "disabled"
            self._face_suggestion = "unknown"
            self._face_score = None
            self._face_match_quality = "unknown"
            self._enroll_samples.clear()
            self._store.delete()
        self._debug("Face template deleted")

    def status(self):
        return self.diagnostics()["status"]

    def diagnostics(self):
        with self._lock:
            face = {
                "enabled": self._face_enabled, "enrolled": self._store.exists(),
                "state": self._face_state, "suggestion": self._face_suggestion,
                "score": self._face_score, "match_quality": self._face_match_quality,
                "samples": len(self._enroll_samples),
                "quality": self._enroll_quality,
                "model": "YuNet 2023mar + SFace 2021dec", "backend": "OpenCV CPU",
                "error": self._face_error, "latency_ms": self._face_latency_ms,
            }
            if time.monotonic() - self._face_suggestion_at > 3:
                face["suggestion"] = "unknown"
                face["match_quality"] = "unknown"
            state = self._state
            return {
                "status": {
                    "state": state, "running": state not in ("stopped", "stopping"),
                    "available": state == "available", "paused": state == "paused",
                    "present": self._present, "room_id": self.room_id,
                    "face_in_frame": self._face_in_frame,
                    "face_count": self._face_count,
                    "presence_reason": self._presence_reason,
                    "presence_sequence": self._presence_sequence,
                    "camera_index": self.camera_index, "frame_sequence": self._frame_sequence,
                    "capture_fps": round(self._capture_fps, 1),
                    "requested_fps": self._requested_fps,
                    "camera_id": self.camera_id, "camera_label": self.camera_label,
                    "camera_role": self.camera_role,
                    "proximity": self._proximity.status(),
                    "head_motion": self._head_motion.status(),
                    "head_confirmation_enabled": self._head_handler is not None,
                    "generation": self._generation, "last_frame_at": self._last_frame_at,
                    "frame_age_ms": (round((time.monotonic() - self._last_frame_monotonic) * 1000)
                                     if self._last_frame_monotonic else None),
                    "last_seen_at": self._last_seen_at, "last_error": self._last_error,
                    "presence_latency_ms": self._presence_latency_ms,
                    "presence_state": self._presence_state,
                    "identity_recognition": self._face_enabled, "face_auth": face,
                },
                "preview_jpeg": self._preview_jpeg, "preview_at": self._preview_at,
                "preview_mode": self._preview_mode,
                "preview_sequence": self._preview_sequence,
            }

    def _debug(self, message, data=None, level="INFO"):
        if self._debug_sink is None:
            return
        if message in {"Face detection sample", "Owner profile suggestion",
                       "Ước lượng biểu cảm", "Hand gesture sample",
                       "Workstation proximity sample", "Head motion shadow candidate"}:
            now = time.monotonic()
            with self._lock:
                previous = self._sample_log_at.get(message, 0.0)
                if now - previous < 1.0 and not (data or {}).get("accepted"):
                    self._sample_log_dropped[message] = (
                        self._sample_log_dropped.get(message, 0) + 1)
                    return
                suppressed = self._sample_log_dropped.pop(message, 0)
                self._sample_log_at[message] = now
            if suppressed:
                data = dict(data or {}, suppressed_samples=suppressed)
        try:
            self._debug_sink("camera", message, data or {}, level=level)
        except Exception:
            logger.debug("Could not publish camera diagnostic", exc_info=True)

    def _offline(self, state, error=None):
        self._frames.clear()
        self._cancel_visual_confirmation()
        with self._lock:
            self._generation += 1
            self._state = state
            self._present = None
            self._face_in_frame = None
            self._face_count = None
            self._presence_reason = "unknown"
            self._presence_sequence = None
            self._last_error = error
            self._preview_jpeg = None
            self._preview_at = None
            self._preview_sequence = -1
            self._preview_mode = None
            self._preview_faces = ()
            self._capture_fps = 0.0
            self._last_overlay_monotonic = 0.0
            self._face_suggestion = "unknown"
            self._face_score = None
            self._face_match_quality = "unknown"
            emotion_state = ("paused" if state == "paused" and self._emotion_enabled else
                             "unavailable" if self._emotion_enabled else "disabled")
            self._clear_emotion_locked(emotion_state)
            if self._gesture_state != "unavailable":
                self._clear_gesture_locked("paused" if state == "paused"
                                           else "waiting_camera")
            self._proximity.reset()
            self._head_motion.reset()
            self._outbox.submit(False)

    def _capture_loop(self):
        try:
            import cv2
        except ImportError:
            self._offline("error", "opencv-python unavailable")
            self._debug("OpenCV unavailable", level="ERROR")
            return
        while not self._stop.is_set():
            if self._paused.is_set():
                self._stop.wait(0.15)
                continue
            with self._lock:
                self._state = "starting"
            try:
                capture = cv2.VideoCapture(self.camera_index,
                                           cv2.CAP_DSHOW if os.name == "nt" else 0)
            except Exception as exc:
                self._offline("unavailable", type(exc).__name__)
                self._debug("Webcam open failed", {"error": type(exc).__name__}, "ERROR")
                self._stop.wait(5)
                continue
            try:
                opened = capture.isOpened()
            except Exception:
                opened = False
            if not opened:
                try:
                    capture.release()
                except Exception:
                    pass
                self._offline("unavailable", "Webcam unavailable")
                self._debug("Webcam could not be opened",
                            {"camera_index": self.camera_index}, "ERROR")
                self._stop.wait(5)
                continue
            # Ask the driver for compressed 640x480 capture. Unsupported settings
            # are advisory; the measured FPS below reports what it actually gives.
            for prop, value in (
                    (cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")),
                    (cv2.CAP_PROP_FRAME_WIDTH, 640),
                    (cv2.CAP_PROP_FRAME_HEIGHT, 480),
                    (cv2.CAP_PROP_FPS, self._requested_fps)):
                try:
                    capture.set(prop, value)
                except (AttributeError, ValueError, OSError):
                    pass
            with self._lock:
                self._generation += 1
                generation = self._generation
                pause_epoch = self._pause_epoch
                self._state = "available"
                self._last_error = None
            self._debug("Webcam connected", {"camera_index": self.camera_index,
                                              "generation": generation,
                                              "opencv_version": cv2.__version__}, "SUCCESS")
            try:
                capture_times = deque(maxlen=60)
                while (not self._stop.is_set() and not self._paused.is_set() and
                       pause_epoch == self._pause_epoch):
                    try:
                        read_started = time.monotonic()
                        ok, frame = capture.read()
                    except Exception as exc:
                        self._offline("unavailable", type(exc).__name__)
                        self._debug("Webcam read failed", {"error": type(exc).__name__}, "ERROR")
                        break
                    if not ok or frame is None:
                        self._offline("unavailable", "Webcam read failed")
                        self._debug("Webcam frame read failed", level="ERROR")
                        break
                    if (self._stop.is_set() or self._paused.is_set() or
                            pause_epoch != self._pause_epoch):
                        break
                    height, width = frame.shape[:2]
                    if width > 640:
                        frame = cv2.resize(frame, (640, max(1, round(height * 640 / width))))
                    else:
                        frame = frame.copy()
                    frame.setflags(write=False)
                    stamp = utc_now()
                    captured = time.monotonic()
                    capture_times.append(captured)
                    measured_fps = ((len(capture_times) - 1) /
                                    (capture_times[-1] - capture_times[0])
                                    if len(capture_times) > 1 and
                                    capture_times[-1] > capture_times[0] else 0.0)
                    with self._lock:
                        self._frame_sequence += 1
                        sequence = self._frame_sequence
                        generation = self._generation
                        self._last_frame_at = stamp
                        self._last_frame_monotonic = captured
                        self._capture_fps = measured_fps
                    self._frames.publish(FramePacket(sequence, generation, stamp,
                                                     captured, frame))
                    # Bound a fast driver without forcing every webcam down to 10 FPS.
                    self._stop.wait(max(0.0, 1 / self._requested_fps -
                                        (time.monotonic() - read_started)))
            finally:
                try:
                    capture.release()
                except Exception:
                    logger.warning("Could not release webcam", exc_info=True)
                if self._paused.is_set():
                    self._offline("paused")
            if self._state == "unavailable" and not self._stop.is_set():
                self._stop.wait(2)
        self._offline("stopped")
        self._debug("Camera service stopped")

    def _preview_loop(self):
        """Show raw webcam frames if presence detection is unavailable or late."""
        try:
            import cv2
        except ImportError:
            return
        sequence = -1
        last_encoded = 0.0
        while not self._stop.is_set():
            with self._lock:
                preview_enabled = self._preview_enabled
            if not preview_enabled:
                with self._lock:
                    stale = (self._state == "available" and self._last_frame_monotonic and
                             time.monotonic() - self._last_frame_monotonic > 3)
                if stale:
                    self._offline("unavailable", "Webcam frame stale")
                    self._debug("Webcam frame stale", level="WARNING")
                self._stop.wait(0.5)
                continue
            packet = self._frames.wait_next(sequence)
            if packet is None:
                with self._lock:
                    stale = (self._state == "available" and self._last_frame_monotonic and
                             time.monotonic() - self._last_frame_monotonic > 3)
                if stale:
                    self._offline("unavailable", "Webcam frame stale")
                    self._debug("Webcam frame stale", level="WARNING")
                continue
            sequence = packet.sequence
            now = time.monotonic()
            with self._lock:
                allowed = (self._preview_enabled and not self._paused.is_set() and
                           self._state == "available" and
                           packet.generation == self._generation and
                           now - self._last_overlay_monotonic >= 0.25)
            if not allowed or now - last_encoded < 0.05 or now - packet.captured_monotonic > 1:
                continue
            last_encoded = now
            try:
                ok, encoded = cv2.imencode(".jpg", packet.pixels,
                                           [int(cv2.IMWRITE_JPEG_QUALITY), 72])
                if ok:
                    with self._lock:
                        if (self._preview_enabled and not self._paused.is_set() and
                                self._state == "available" and
                                packet.generation == self._generation and
                                packet.sequence >= self._preview_sequence and
                                time.monotonic() - self._last_overlay_monotonic >= 0.25):
                            self._preview_jpeg = encoded.tobytes()
                            self._preview_at = packet.captured_at
                            self._preview_sequence = packet.sequence
                            self._preview_mode = "raw"
            except Exception as exc:
                self._debug("Camera preview encoding failed",
                            {"error": type(exc).__name__}, "WARNING")
                self._stop.wait(1)

    def _presence_loop(self):
        try:
            import cv2
            cascade_type = getattr(cv2, "CascadeClassifier", None)
            cascade_file = os.path.join(getattr(getattr(cv2, "data", None), "haarcascades", ""),
                                        "haarcascade_frontalface_default.xml")
            if cascade_type is not None and os.path.isfile(cascade_file):
                detector = cascade_type(cascade_file)
                if detector.empty():
                    raise RuntimeError("Haar face detector unavailable")
                provider = "opencv-haar"
            else:
                detector = cv2.FaceDetectorYN.create(
                    str(model_path("yunet")), "", (320, 320),
                    score_threshold=0.9, nms_threshold=0.3)
                provider = "opencv-yunet-2023mar"
        except Exception as exc:
            with self._lock:
                self._presence_state = "error"
                self._present = None
                self._face_in_frame = None
                self._face_count = None
                self._presence_reason = "unknown"
                self._presence_sequence = None
                self._outbox.submit(False)
            self._debug("Presence detector unavailable", {
                "error": type(exc).__name__, "detail": str(exc)[:180]}, "ERROR")
            return
        with self._lock:
            self._presence_state = "ready"
        self._debug("Presence detector ready", {"provider": provider}, "SUCCESS")
        votes = deque(maxlen=3)
        last_face = 0.0
        last_run = 0.0
        last_log = 0.0
        sequence = -1
        generation = -1
        previous = None
        inference_errors = 0
        while not self._stop.is_set():
            packet = self._frames.wait_next(sequence)
            if packet is None:
                continue
            if self._paused.is_set():
                continue
            sequence = packet.sequence
            if generation != packet.generation:
                votes.clear()
                last_face = 0.0
                previous = None
                generation = packet.generation
            now = time.monotonic()
            if now - last_run < 0.45 or now - packet.captured_monotonic > 1:
                continue
            last_run = now
            try:
                rows = None
                if provider == "opencv-haar":
                    gray = cv2.cvtColor(packet.pixels, cv2.COLOR_BGR2GRAY)
                    faces = detector.detectMultiScale(gray, scaleFactor=1.1,
                                                      minNeighbors=5, minSize=(48, 48))
                else:
                    rows = detect_yunet(detector, packet.pixels)
                    faces = ([] if rows is None else
                             [(int(row[0]), int(row[1]), int(row[2]), int(row[3]))
                              for row in rows if min(row[2], row[3]) >= 48])
                inferred = time.monotonic()
                inference_errors = 0
                found = len(faces) > 0
                votes.append(found)
                if found:
                    last_face = inferred
                present = sum(votes) >= 2 or (previous is True and inferred - last_face < 5)
                reason = ("detected" if found and present else
                          "held" if present else
                          "candidate" if found else "not_detected")
                latency = round((inferred - packet.captured_monotonic) * 1000)
                with self._lock:
                    if (self._stop.is_set() or self._paused.is_set() or
                            packet.generation != self._generation):
                        continue
                    if self._state in ("error", "unavailable"):
                        self._state = "available"
                        self._last_error = None
                    self._presence_state = "ready"
                    self._last_presence_inference_monotonic = inferred
                    self._present = present
                    self._face_in_frame = found
                    self._face_count = len(faces)
                    self._presence_reason = reason
                    self._presence_sequence = packet.sequence
                    self._presence_latency_ms = latency
                    self._preview_faces = tuple(faces)
                    self._preview_faces_at = inferred
                    if found:
                        self._last_seen_at = utc_now()
                    preview_enabled = self._preview_enabled and not self._gesture_enabled
                    self._outbox.submit(present)
                    proximity = (self._proximity.observe(
                        faces, packet.pixels, provider, packet.generation, inferred)
                        if self.camera_role == "workstation_facing" else None)
                    proximity_handler = self._proximity_handler
                    if self.camera_role == "workstation_facing" and rows is not None:
                        head_row = rows[0] if len(rows) == 1 else None
                        head_event = self._head_motion.observe(
                            head_row, packet.generation, inferred)
                        head_started_at = self._head_motion.last_motion_started_at
                        head_handler = self._head_handler
                    else:
                        head_event = None
                        head_started_at = 0.0
                        head_handler = None
                        if provider == "opencv-haar":
                            self._head_motion.unavailable()
                        elif self.camera_role == "workstation_facing":
                            self._head_motion.observe(None, packet.generation, inferred)
                if proximity is not None:
                    current = (proximity["band"], proximity["observation_state"],
                               proximity["calibration"])
                    if current != self._last_proximity_state or inferred - self._last_proximity_log >= 10:
                        self._debug("Workstation proximity sample", {
                            "camera_id": self.camera_id, "sequence": packet.sequence,
                            "band": proximity["band"],
                            "visibility": proximity["visibility"],
                            "quality": proximity["quality"],
                            "calibration": proximity["calibration"],
                            "valid_samples": proximity["valid_samples"],
                        })
                        self._last_proximity_state = current
                        self._last_proximity_log = inferred
                    if proximity_handler is not None:
                        try:
                            proximity_handler(proximity)
                        except Exception as exc:
                            self._debug("Proximity consumer failed", {
                                "error": type(exc).__name__}, "ERROR")
                if head_event:
                    self._debug("Head motion shadow candidate", {
                        "label": head_event, "sequence": packet.sequence,
                        "provider": provider, "accepted": False,
                        "reason": ("confirmation_opt_in" if head_handler else
                                   "shadow_only")})
                    if head_handler is not None:
                        try:
                            head_handler(head_event, head_started_at)
                        except Exception as exc:
                            self._debug("Head motion consumer failed", {
                                "error": type(exc).__name__}, "ERROR")
                if preview_enabled:
                    overlay = packet.pixels.copy()
                    for x, y, w, h in faces:
                        cv2.rectangle(overlay, (x, y), (x + w, y + h), (70, 220, 150), 2)
                    ok, encoded = cv2.imencode(".jpg", overlay,
                                               [int(cv2.IMWRITE_JPEG_QUALITY), 72])
                    if ok:
                        with self._lock:
                            if (self._preview_enabled and not self._paused.is_set() and
                                    packet.generation == self._generation and
                                    self._state == "available" and
                                    packet.sequence >= self._preview_sequence):
                                self._preview_jpeg = encoded.tobytes()
                                self._preview_at = packet.captured_at
                                self._preview_sequence = packet.sequence
                                self._preview_mode = "detector_overlay"
                                self._last_overlay_monotonic = time.monotonic()
                if present != previous or inferred - last_log >= 3:
                    self._debug("Face detection sample", {
                        "kind": "camera.face_presence_proxy", "provider": provider,
                        "sequence": packet.sequence, "captured_at": packet.captured_at,
                        "face_count": len(faces), "positive_votes": sum(votes),
                        "window": len(votes), "present": present,
                        "presence_reason": reason, "latency_ms": latency,
                    }, "SUCCESS" if found and present else "INFO")
                    last_log = inferred
                previous = present
            except Exception as exc:
                with self._lock:
                    self._presence_state = "error"
                    self._present = None
                    self._face_in_frame = None
                    self._face_count = None
                    self._presence_reason = "unknown"
                    self._presence_sequence = None
                    self._outbox.submit(False)
                    self._proximity.reset()
                    self._head_motion.reset()
                inference_errors += 1
                if inference_errors == 1 or inference_errors == 3:
                    self._debug("Presence inference failed", {
                        "provider": provider, "error": type(exc).__name__,
                        "detail": str(exc)[:180], "failures": inference_errors,
                    }, "ERROR")
                if inference_errors >= 3:
                    return
                self._stop.wait(1)

    def _face_loop(self):
        engine = None
        template = None
        sequence = -1
        last_run = 0.0
        votes = deque(maxlen=3)
        previous_suggestion = "unknown"
        previous_quality = "unknown"
        last_generation = -1
        while not self._stop.is_set():
            with self._lock:
                enabled = self._face_enabled
            if not enabled:
                engine = None
                template = None
                votes.clear()
                previous_suggestion = "unknown"
                previous_quality = "unknown"
                self._stop.wait(0.3)
                continue
            if engine is None:
                try:
                    engine = FaceEngine()
                    template = self._store.load()
                    with self._lock:
                        if self._face_state == "loading":
                            self._face_state = "ready" if template is not None else "not_enrolled"
                except Exception as exc:
                    with self._lock:
                        self._face_enabled = False
                        self._face_state = "unavailable"
                        self._face_error = str(exc)[:180]
                    self._debug("Face suggestion unavailable",
                                {"error": type(exc).__name__}, "WARNING")
                    continue
            with self._lock:
                enrolling = self._face_state == "enrolling"
            if template is None and not enrolling:
                self._stop.wait(0.3)
                continue
            packet = self._frames.wait_next(sequence)
            if packet is None or self._paused.is_set():
                continue
            sequence = packet.sequence
            if packet.generation != last_generation:
                votes.clear()
                previous_suggestion = "unknown"
                previous_quality = "unknown"
                with self._lock:
                    self._enroll_samples.clear()
                last_generation = packet.generation
            now = time.monotonic()
            if now - last_run < 0.65 or now - packet.captured_monotonic > 1:
                continue
            last_run = now
            try:
                quality, embedding = engine.embedding(packet.pixels)
                inferred = time.monotonic()
                with self._lock:
                    if (self._stop.is_set() or self._paused.is_set() or
                            packet.generation != self._generation):
                        continue
                    self._face_latency_ms = round((inferred - packet.captured_monotonic) * 1000)
                    if self._face_state == "enrolling":
                        self._enroll_quality = quality
                        if quality == "ok" and inferred - self._enroll_last_at >= 0.5:
                            if (self._enroll_samples and
                                    match_score(embedding, self._enroll_samples[0]) < 0.4):
                                self._enroll_samples.clear()
                            self._enroll_samples.append(embedding)
                            self._enroll_last_at = inferred
                        if len(self._enroll_samples) >= 5:
                            import numpy as np
                            vector = np.mean(self._enroll_samples, axis=0)
                            vector /= np.linalg.norm(vector)
                            self._store.save(vector)
                            template = vector
                            self._enroll_samples.clear()
                            self._face_state = "ready"
                            self._debug("Owner face template enrolled", level="SUCCESS")
                    elif template is not None and self._face_enabled:
                        self._face_match_quality = quality
                        score = match_score(embedding, template) if quality == "ok" else None
                        if quality == "ok":
                            votes.append(score >= MATCH_THRESHOLD)
                        else:
                            votes.clear()
                        suggestion = ("unknown" if quality != "ok" or len(votes) < 3 else
                                      "matched" if sum(votes) >= 2 else "not_matched")
                        self._face_score = round(score, 3) if score is not None else None
                        self._face_suggestion = suggestion
                        self._face_suggestion_at = inferred
                        if suggestion != previous_suggestion or quality != previous_quality:
                            self._debug("Owner profile suggestion", {
                                "sequence": packet.sequence, "result": suggestion,
                                "score": self._face_score, "quality": quality,
                                "positive_votes": sum(votes), "window": len(votes),
                                "latency_ms": self._face_latency_ms,
                            })
                            previous_suggestion = suggestion
                            previous_quality = quality
            except Exception as exc:
                with self._lock:
                    self._face_enabled = False
                    self._face_state = "unavailable"
                    self._face_error = type(exc).__name__
                    self._enroll_samples.clear()
                engine = None
                self._debug("Face suggestion failed", {"error": type(exc).__name__}, "ERROR")

    def _emotion_loop(self):
        """Low-rate, opt-in expression estimates for the control/debug UI."""
        engine = None
        sequence = -1
        generation = -1
        last_run = 0.0
        last_log = 0.0
        previous = (None, None)
        while not self._stop.is_set():
            with self._lock:
                enabled = self._emotion_enabled and (self._emotion_debug_visible or self._emotion_control_visible)
                epoch = self._emotion_epoch
            if not enabled:
                engine = None
                previous = (None, None)
                self._stop.wait(0.25)
                continue
            if engine is None:
                try:
                    from features.camera.emotion import EmotionEngine
                    engine = EmotionEngine()
                    with self._lock:
                        if epoch != self._emotion_epoch or not self._emotion_enabled:
                            engine = None
                            continue
                        self._emotion_state = "waiting_camera"
                        self._emotion_error = None
                    self._debug("Emotion model ready", {
                        "provider": "emotiefflib-enet_b0_8_best_afew-onnx-cpu"}, "SUCCESS")
                except Exception as exc:
                    with self._lock:
                        if epoch != self._emotion_epoch:
                            continue
                        self._emotion_enabled = False
                        self._clear_emotion_locked("unavailable")
                        self._emotion_error = f"{type(exc).__name__}: {str(exc)[:140]}"
                    self._debug("Emotion model unavailable", {
                        "error": type(exc).__name__, "detail": str(exc)[:140]}, "ERROR")
                    continue
            packet = self._frames.wait_next(sequence)
            if packet is None or self._paused.is_set():
                continue
            sequence = packet.sequence
            if packet.generation != generation:
                generation = packet.generation
                last_run = 0.0
                previous = (None, None)
            now = time.monotonic()
            if now - last_run < 1.0 or now - packet.captured_monotonic > 1:
                continue
            with self._lock:
                if (epoch != self._emotion_epoch or not self._emotion_enabled or
                        not (self._emotion_debug_visible or self._emotion_control_visible)):
                    continue
            last_run = now
            try:
                quality, label, confidence = engine.estimate(packet.pixels)
                inferred = time.monotonic()
                latency = round((inferred - packet.captured_monotonic) * 1000)
                with self._lock:
                    if (self._stop.is_set() or self._paused.is_set() or
                            packet.generation != self._generation or
                            epoch != self._emotion_epoch or not self._emotion_enabled or
                            not (self._emotion_debug_visible or self._emotion_control_visible)):
                        continue
                    self._emotion_state = "ready"
                    self._emotion_quality = quality
                    self._emotion_label = label
                    self._emotion_confidence = (round(confidence, 3)
                                                if confidence is not None else None)
                    self._emotion_latency_ms = latency
                    self._emotion_sequence = packet.sequence
                    self._emotion_at = inferred
                current = (quality, label)
                if current != previous or inferred - last_log >= 3:
                    self._debug("Ước lượng biểu cảm", {
                        "kind": "face.expression_estimate",
                        "provider": "emotiefflib-enet_b0_8_best_afew-onnx-cpu",
                        "sequence": packet.sequence, "captured_at": packet.captured_at,
                        "quality": quality, "label": label,
                        "confidence": (round(confidence, 3)
                                       if confidence is not None else None),
                        "latency_ms": latency,
                    }, "INFO")
                    last_log = inferred
                previous = current
            except Exception as exc:
                with self._lock:
                    if epoch != self._emotion_epoch:
                        continue
                    self._emotion_enabled = False
                    self._clear_emotion_locked("unavailable")
                    self._emotion_error = f"{type(exc).__name__}: {str(exc)[:140]}"
                engine = None
                self._debug("Emotion inference failed", {
                    "error": type(exc).__name__, "detail": str(exc)[:140]}, "ERROR")

    def _gesture_loop(self):
        if self.camera_role != "workstation_facing":
            with self._lock:
                self._clear_gesture_locked("disabled")
            return
        """Always-on local hand landmarks; a held pose emits once per release."""
        while not self._stop.is_set() and not self._gesture_enabled:
            self._stop.wait(0.25)
        if self._stop.is_set():
            return
        try:
            from features.camera.gesture import (PROVIDER, GestureDebouncer,
                                                 HandGestureEngine)
            engine = HandGestureEngine()
        except Exception as exc:
            with self._lock:
                self._clear_gesture_locked("unavailable")
                self._gesture_error = f"{type(exc).__name__}: {str(exc)[:140]}"
            self._debug("Gesture model unavailable", {
                "error": type(exc).__name__, "detail": str(exc)[:140]}, "ERROR")
            return
        self._debug("Gesture model ready", {"provider": PROVIDER}, "SUCCESS")
        debounce = GestureDebouncer()
        temporal = HandTemporalTracker()
        sequence = -1
        generation = -1
        last_run = 0.0
        last_log = 0.0
        last_preview = 0.0
        inference_times = deque(maxlen=30)
        previous = (None, None)
        try:
            while not self._stop.is_set():
                packet = self._frames.wait_next(sequence)
                if packet is None:
                    continue
                sequence = packet.sequence
                if self._paused.is_set() or not self._gesture_enabled:
                    debounce.reset()
                    temporal.reset()
                    previous = (None, None)
                    last_run = 0.0
                    continue
                if packet.generation != generation:
                    generation = packet.generation
                    debounce.reset()
                    temporal.reset()
                    previous = (None, None)
                    last_run = 0.0
                now = time.monotonic()
                if now - last_run < 0.05 or now - packet.captured_monotonic > 0.75:
                    continue
                last_run = now
                try:
                    with self._lock:
                        preview_enabled = self._preview_enabled
                    quality, label, count, hand_score, geometry = engine.recognize(
                        packet.pixels, round(packet.captured_monotonic * 1000),
                        include_landmarks=preview_enabled)
                    hands = engine.last_landmarks
                    engine.last_landmarks = ()
                    features = getattr(engine, "last_features", None)
                    if features is not None:
                        engine.last_features = None
                    motion = temporal.observe(features, packet.captured_monotonic)
                    inferred = time.monotonic()
                    inference_times.append(inferred)
                    measured_gesture_fps = (
                        (len(inference_times) - 1) /
                        (inference_times[-1] - inference_times[0])
                        if len(inference_times) > 1 and
                        inference_times[-1] > inference_times[0] else 0.0)
                    latency = round((inferred - packet.captured_monotonic) * 1000)
                    with self._lock:
                        if (self._stop.is_set() or self._paused.is_set() or
                                packet.generation != self._generation or
                                self._state != "available" or not self._gesture_enabled):
                            debounce.reset()
                            temporal.reset()
                            continue
                        self._gesture_state = "ready"
                        self._gesture_error = None
                        self._gesture_quality = quality
                        self._gesture_label = label
                        self._gesture_basic_pose = motion.stable_pose
                        self._gesture_hand_count = count
                        self._gesture_latency_ms = latency
                        self._gesture_sequence = packet.sequence
                        self._gesture_at = inferred
                        self._gesture_fps = measured_gesture_fps
                        faces = (self._preview_faces if
                                 inferred - self._preview_faces_at <= 0.75 else ())
                        handler = self._gesture_handler
                    if preview_enabled and inferred - last_preview >= 0.05:
                        # Use the exact frame inferred by MediaPipe so fast hand
                        # movements do not shift the skeleton onto a later frame.
                        last_preview = inferred
                        try:
                            import cv2
                            overlay = packet.pixels.copy()
                            for x, y, width, height in faces:
                                cv2.rectangle(overlay, (x, y),
                                              (x + width, y + height), (70, 220, 150), 2)
                            draw_hand_skeleton(overlay, hands, cv2)
                            ok, encoded = cv2.imencode(
                                ".jpg", overlay, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
                            if ok:
                                with self._lock:
                                    if (self._preview_enabled and not self._paused.is_set() and
                                            packet.generation == self._generation and
                                            packet.sequence >= self._preview_sequence):
                                        self._preview_jpeg = encoded.tobytes()
                                        self._preview_at = packet.captured_at
                                        self._preview_sequence = packet.sequence
                                        self._preview_mode = "hand_skeleton"
                                        self._last_overlay_monotonic = time.monotonic()
                        except Exception as exc:
                            self._debug("Hand preview failed", {
                                "error": type(exc).__name__}, "WARNING")
                    fired = debounce.observe(label, inferred)
                    current = (quality, label, motion.stable_pose)
                    if (current != previous or inferred - last_log >= 4 or fired or
                            motion.swipe or motion.pinch_started or motion.pinch_ended):
                        self._debug("Hand gesture sample", {
                            "kind": "camera.hand_gesture", "provider": PROVIDER,
                            "sequence": packet.sequence,
                            "captured_at": packet.captured_at,
                            "quality": quality, "label": label,
                            "hand_count": count,
                            "handedness_score": (round(hand_score, 3)
                                                 if hand_score is not None else None),
                            "geometry": geometry,
                            "temporal": {"stable_pose": motion.stable_pose,
                                         "pose_changed": motion.pose_changed,
                                         "swipe": motion.swipe,
                                         "pinch_started": motion.pinch_started,
                                         "pinch_ended": motion.pinch_ended,
                                         "action": "debug_only"},
                            "latency_ms": latency, "accepted": bool(fired),
                        }, "SUCCESS" if fired else "INFO")
                        last_log = inferred
                    previous = current
                    if motion.swipe or motion.pinch_started:
                        self._debug("Hand interaction shadow event", {
                            "kind": "camera.hand_interaction_shadow",
                            "sequence": packet.sequence,
                            "pose": motion.stable_pose,
                            "event": motion.swipe or "pinch_started",
                            "action": "debug_only"})
                    if fired and handler is not None:
                        try:
                            handler(fired, debounce.candidate_started_at)
                        except Exception as exc:
                            self._debug("Gesture consumer failed", {
                                "error": type(exc).__name__}, "ERROR")
                except Exception as exc:
                    with self._lock:
                        self._clear_gesture_locked("unavailable")
                        self._gesture_error = f"{type(exc).__name__}: {str(exc)[:140]}"
                    self._debug("Gesture inference failed", {
                        "error": type(exc).__name__, "detail": str(exc)[:140]},
                        "ERROR")
                    return
        finally:
            engine.close()
