"""A single pending-action gate for hand and head confirmation signals."""

import threading
import time


class VisualConfirmationArbiter:
    def __init__(self, agent, agent_lock, on_result=None, debug=None,
                 conflict_window=0.4, is_active=None):
        self.agent = agent
        self.agent_lock = agent_lock
        self.on_result = on_result
        self.debug = debug
        self.conflict_window = max(0.25, float(conflict_window))
        self.is_active = is_active
        self._lock = threading.Lock()
        self._candidate = None
        self._conflicted_pending = None
        self._epoch = 0

    def cancel(self):
        with self._lock:
            self._epoch += 1
            self._candidate = None
            self._conflicted_pending = None

    def _log(self, message, data=None, level="INFO"):
        if self.debug is not None:
            self.debug("camera", message, data or {}, level=level)

    def submit(self, modality, decision, pose_started_at, label=None):
        if modality not in {"hand", "head"} or decision not in {"yes", "no"}:
            return False
        if not 0 <= time.monotonic() - pose_started_at <= 5:
            return False
        if self.is_active is not None and not self.is_active():
            return False
        if not self.agent_lock.acquire(timeout=1):
            self._log("Visual confirmation ignored: agent busy", {
                "modality": modality}, "WARNING")
            return False
        try:
            pending = self.agent.pending
            if (pending is None or pending.get("_camera_gesture_ready_at",
                                                float("inf")) > pose_started_at):
                return False
        finally:
            self.agent_lock.release()
        with self._lock:
            if self._conflicted_pending is not None:
                if self._conflicted_pending is pending:
                    return False
                self._conflicted_pending = None
            candidate = self._candidate
            if candidate is not None and candidate["pending"] is pending:
                if candidate["decision"] != decision:
                    candidate["conflict"] = True
                    self._conflicted_pending = pending
                    self._log("Visual confirmation conflict", {
                        "first": candidate["modality"], "second": modality})
                return False
            candidate = {"pending": pending, "decision": decision,
                         "modality": modality, "label": label or decision,
                         "pose_started_at": pose_started_at, "conflict": False,
                         "epoch": self._epoch}
            self._candidate = candidate
        try:
            threading.Thread(target=self._resolve, args=(candidate,),
                             name="alice-visual-confirmation", daemon=True).start()
        except RuntimeError:
            with self._lock:
                if self._candidate is candidate:
                    self._candidate = None
            self._log("Visual confirmation worker unavailable", level="WARNING")
            return False
        return True

    def _resolve(self, candidate):
        time.sleep(self.conflict_window)
        with self._lock:
            if self._candidate is not candidate:
                return
            if candidate["conflict"]:
                self._candidate = None
                return
        if not self.agent_lock.acquire(timeout=1):
            with self._lock:
                if self._candidate is candidate:
                    self._candidate = None
            self._log("Visual confirmation ignored: agent busy", {
                "modality": candidate["modality"]}, "WARNING")
            return
        try:
            pending = candidate["pending"]
            with self._lock:
                valid = (self._candidate is candidate and not candidate["conflict"] and
                         candidate["epoch"] == self._epoch)
                if self._candidate is candidate:
                    self._candidate = None
            result = (self.agent.confirm_pending(candidate["decision"])
                      if valid and (self.is_active is None or self.is_active()) and
                      0 <= time.monotonic() - candidate["pose_started_at"] <= 5 and
                      self.agent.pending is pending and
                      pending.get("_camera_gesture_ready_at", float("inf")) <=
                      candidate["pose_started_at"] else None)
        except Exception as exc:
            self._log("Visual confirmation failed", {
                "error": type(exc).__name__}, "ERROR")
            result = None
        finally:
            self.agent_lock.release()
        self._log("Visual confirmation applied", {
            "modality": candidate["modality"], "label": candidate["label"],
            "decision": candidate["decision"], "confirmation": bool(result)},
            "SUCCESS" if result else "INFO")
        if result and self.on_result is not None:
            self.on_result(result, candidate["modality"], candidate["label"],
                           candidate["decision"])
