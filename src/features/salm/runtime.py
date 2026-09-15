"""Lifecycle runtime của SALM: collector 0A + policy/intervention 0B."""

import threading
import time
from datetime import datetime
from pathlib import Path

from features.salm.care_action import CareActionPolicy
from features.salm.care_dnd import UserCareDnd
from features.salm.checkin import (CheckInResponseWindow, match_resume_care,
                                   match_snooze, checkin_text)
from features.salm.dialogue import CareDialogue, CareIntent
from features.salm.engine import SalmEngine
from features.salm.intervention import Intervention, InterventionGate
from features.salm.media import GsmtcProbe, WasapiProbe
from features.salm.policy import BreakOutcomeTracker, BreakPolicy
from features.salm.presenter import CARE_PULSE_SECONDS
from features.salm.storage import SalmStorage
from features.salm.welcome import ReturnWelcomeTracker
from features.salm.windows import PowerEventWatcher, WindowsActivityProbe
from utils.logger import get_logger

logger = get_logger(__name__)


class SalmRuntime:
    """Orchestrate collector -> engine -> policy; UI/TTS chỉ đi qua callback đã tiêm."""

    def __init__(self, data_dir, browser=None, poll_seconds=1.0,
                 wasapi_fallback=False, ttl_days=14,
                 engine=None, storage=None, power=None, windows_probe=None,
                 gsmtc=None, wasapi=None, gate=None, dispatcher=None,
                 policy=None, policy_shadow=True, silent_care=False,
                 on_care=None, outcome_tracker=None, on_return=None,
                 welcome_tracker=None, gentle_checkin=False, on_checkin=None,
                 checkin_window=None, care_llm=None, care_llm_intent=False,
                 user_dnd=False, care_dnd=None, care_actions=None):
        self.poll_seconds = max(0.25, float(poll_seconds))
        self.wasapi_fallback = bool(wasapi_fallback)
        self.engine = engine or SalmEngine(max_sample_gap=max(30.0, self.poll_seconds * 4))
        self.storage = storage or SalmStorage(data_dir, ttl_days=ttl_days)
        self.power = power or PowerEventWatcher()
        meeting_state = (lambda: browser.meeting_open) if browser is not None else (lambda: None)
        self.windows = windows_probe or WindowsActivityProbe(self.power, meeting_state)
        self.gsmtc = gsmtc or GsmtcProbe()
        self.wasapi = wasapi or WasapiProbe()
        self.gate = gate or InterventionGate(salm_enabled=True)
        self.dispatcher = dispatcher
        self.policy = policy or BreakPolicy()
        # Policy được chạm từ collector thread và assistant-input thread (care response).
        self._policy_lock = threading.RLock()
        self.outcomes = outcome_tracker or BreakOutcomeTracker()
        self.policy_shadow = bool(policy_shadow)
        self.silent_care = bool(silent_care)
        self.on_care = on_care
        self.on_return = on_return
        self.welcome = welcome_tracker or ReturnWelcomeTracker()
        self.gentle_checkin = bool(gentle_checkin)
        self.on_checkin = on_checkin
        self.checkins = checkin_window or CheckInResponseWindow()
        self.care_llm_intent = bool(care_llm_intent and care_llm is not None)
        self.dialogue = CareDialogue(care_llm) if self.care_llm_intent else None
        dnd_path = Path(data_dir) / "care-dnd.json" if data_dir else None
        self.care_dnd = care_dnd or UserCareDnd(dnd_path, enabled=user_dnd)
        self.user_dnd = bool(user_dnd)
        self.care_actions = care_actions or CareActionPolicy(
            self.policy, self.care_dnd, self.gate, user_dnd_enabled=self.user_dnd)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._last_error = None
        self._last_policy_signature = None
        self._last_policy_record = None

    def start(self):
        if self._thread is not None:
            return False
        self._stop.clear()
        self.gate.set_salm_enabled(True)
        dnd = self.care_dnd.refresh(datetime.now().astimezone())
        self.gate.set_user_care_dnd(dnd.active)
        self.power.start()
        gsmtc_started = self.gsmtc.start()
        if not gsmtc_started:
            logger.warning("SALM: GSMTC binding unavailable; primary media signal is unknown "
                           "(WASAPI fallback=%s).", self.wasapi_fallback)
        self.storage.purge_expired()
        self._thread = threading.Thread(target=self._run, name="salm-runtime", daemon=True)
        self._thread.start()
        logger.info("SALM đã bật (policy shadow=%s, silent care=%s, gentle check-in=%s, "
                    "WASAPI fallback=%s).", self.policy_shadow, self.silent_care,
                    self.gentle_checkin, self.wasapi_fallback)
        return True

    def stop(self):
        self.gate.set_salm_enabled(False)
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=max(3.0, self.poll_seconds * 2))
        self.gsmtc.stop()
        self.power.stop()
        self.care_dnd.end_session()
        if self.care_dnd.state is None:
            self.gate.set_user_care_dnd(False)

    @property
    def alive(self):
        return bool(self._thread and self._thread.is_alive())

    def diagnostic(self):
        with self._lock:
            value = self.engine.diagnostic()
            value["runtime"] = {
                "alive": self.alive,
                "gsmtc_available": bool(self.gsmtc.available),
                "wasapi_fallback": self.wasapi_fallback,
                "last_error": self._last_error,
                "policy_shadow": self.policy_shadow,
                "silent_care": self.silent_care,
                "gentle_checkin": self.gentle_checkin,
                "care_llm_intent": self.care_llm_intent,
                "user_dnd": self.user_dnd,
                "user_dnd_mode": (
                    self.care_dnd.state.mode if self.care_dnd.state else None),
                "checkin_waiting_response": (
                    self.checkins.active(time.monotonic()) is not None),
            }
            gate = self.gate.snapshot()
            value["gate"] = {
                "salm_enabled": gate.salm_enabled,
                "work_mode": gate.work_mode,
                "meeting_open": gate.meeting_open,
                "meeting_signal": gate.meeting_signal,
                "assistant_busy": gate.assistant_busy,
                "presence": gate.presence.value,
                "display": gate.display.value,
                "activity": gate.activity.value,
                "confidence": gate.confidence.value,
                "session_locked": gate.session_locked,
                "foreground_fullscreen": gate.foreground_fullscreen,
                "user_care_dnd": gate.user_care_dnd,
                "block_reasons": list(self.gate.reasons("break_care")),
            }
            value["last_policy_decision"] = (
                dict(self._last_policy_record) if self._last_policy_record else None)
            return value

    def _run(self):
        com_initialized = False
        if self.wasapi_fallback:
            try:
                import comtypes
                comtypes.CoInitialize()
                com_initialized = True
            except Exception as exc:
                logger.warning("Không khởi tạo được COM cho WASAPI SALM: %s", exc)
        next_flush = time.monotonic() + 60.0
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    gsmtc_apps = self.gsmtc.apps()
                    audible_apps = (self.wasapi.sample(now=started)
                                    if self.wasapi_fallback else frozenset())
                    snapshot = self.windows.collect(gsmtc_apps, audible_apps)
                    with self._lock:
                        update = self.engine.update(snapshot)
                        clocks = {
                            "work_engagement": self.engine.work_clock,
                            "screen_exposure": self.engine.screen_clock,
                        }
                        cycles = dict(self.engine.cycle_ids)
                    dnd = self.care_dnd.refresh(
                        snapshot.wall_time,
                        cycle_id=cycles.get("work_engagement"),
                        presence=update.state.presence)
                    self.gate.set_user_care_dnd(dnd.active)
                    if dnd.released:
                        with self._policy_lock:
                            if dnd.mode == "timed_dnd":
                                self.policy.expire_user_dnd()
                            else:
                                self.policy.discard_pending()
                    for outcome in self.outcomes.observe(
                            cycles, snapshot.monotonic, snapshot.wall_time):
                        self.storage.append(outcome.to_record())
                    for interval in update.closed_intervals:
                        self.storage.append(interval.to_record())
                    for opportunity in update.opportunities:
                        self.storage.append(opportunity.to_record())
                    self.gate.update_activity(snapshot, update.state,
                                              now=snapshot.monotonic)
                    returned = self.welcome.observe(
                        update.state, snapshot.monotonic, snapshot.wall_time)
                    if returned is not None:
                        self.storage.append(returned.to_record())
                        if self.on_return is not None:
                            try:
                                self.on_return(returned)
                            except Exception:
                                logger.warning("SALM không nộp được lời mừng quay lại",
                                               exc_info=True)
                    if (self.policy_shadow or self.silent_care
                            or self.gentle_checkin):
                        with self._policy_lock:
                            decision = self.policy.evaluate(
                                update.opportunities, update.state, snapshot,
                                self.gate, clocks, cycles)
                        self._handle_policy_decision(
                            decision, snapshot.monotonic, cycles)
                    self._last_error = None
                    if time.monotonic() >= next_flush:
                        with self._lock:
                            self.storage.write_daily(self.engine.daily)
                        next_flush = time.monotonic() + 60.0
                except Exception as exc:
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning("SALM tick lỗi, sẽ thử lại: %s", exc)
                elapsed = time.monotonic() - started
                self._stop.wait(max(0.0, self.poll_seconds - elapsed))
        finally:
            try:
                with self._lock:
                    for interval in self.engine.finish():
                        self.storage.append(interval.to_record())
                    self.storage.write_daily(self.engine.daily)
            except Exception as exc:
                logger.warning("SALM không flush gọn được lúc dừng: %s", exc)
            if com_initialized:
                try:
                    import comtypes
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    def _handle_policy_decision(self, decision, now=0.0, cycles=None):
        if decision is None:
            self._last_policy_signature = None
            return
        signature = (decision.action, decision.candidate_id,
                     decision.reason_codes, decision.coalesced_ids)
        record = decision.to_record(
            shadow=not (self.silent_care or self.gentle_checkin))
        with self._lock:
            self._last_policy_record = record
        if signature != self._last_policy_signature:
            self.storage.append(record)
            self._last_policy_signature = signature
        if decision.action != "dispatch":
            return
        if self.gentle_checkin:
            self._dispatch_checkin(decision, now, cycles or {})
            return
        if not self.silent_care:
            return
        if self.dispatcher is None or self.on_care is None:
            logger.warning("SALM silent care bật nhưng chưa có dispatcher/presenter.")
            return
        token = decision.candidate_id
        cycles = cycles or {}
        self.outcomes.watch(decision, cycles.get(decision.clock, 0), now)
        intervention = Intervention(
            kind="salm_break_care",
            scope="break_care",
            token=token,
            active_seconds=CARE_PULSE_SECONDS,
            present=lambda: self.on_care("pulse", token),
            cancel=lambda: self._cancel_care(token),
            on_drop=lambda: self.outcomes.discard(token),
        )
        if not self.dispatcher.submit(intervention):
            self.outcomes.discard(token)
            logger.debug("SALM cue bị gate chặn sát lúc dispatch: %s", token)

    def _dispatch_checkin(self, decision, now, cycles):
        if self.dispatcher is None or self.on_checkin is None:
            logger.warning("SALM gentle check-in bật nhưng chưa có dispatcher/presenter.")
            return
        token = decision.candidate_id
        cycle_id = cycles.get(decision.clock, 0)
        text = checkin_text(decision.clock, decision.level)
        self.outcomes.watch(decision, cycle_id, now, checkin=True)

        def present():
            try:
                shown = self.on_checkin("present", decision, text)
            except Exception:
                self.outcomes.discard(token)
                raise
            if shown is False:
                self.outcomes.discard(token)
                return
            self.checkins.arm(
                decision, cycle_id, time.monotonic(),
                work_cycle_id=cycles.get("work_engagement", cycle_id))

        intervention = Intervention(
            kind="salm_gentle_checkin",
            scope="break_care",
            token=token,
            present=present,
            cancel=lambda: self._cancel_checkin(decision, text),
            on_drop=lambda: self._drop_checkin(token),
        )
        if not self.dispatcher.submit(intervention):
            self._drop_checkin(token)
            logger.debug("SALM check-in bị gate chặn sát lúc dispatch: %s", token)

    def try_care_response(self, text, now=None, at=None):
        """Hiểu phản hồi check-in; None nghĩa là trả nguyên câu về pipeline Agent."""
        if not self.gentle_checkin:
            return None
        live_clock = now is None
        now = time.monotonic() if live_clock else float(now)
        at = datetime.now().astimezone() if at is None else at

        # Escape hatch không cần LLM và hoạt động cả ngoài response window.
        if match_resume_care(text) and self.care_dnd.state is not None:
            intent = CareIntent(
                "resume_care", None, None, "explicit_resume", 1.0,
                "explicit_resume", source="fallback")
            with self._policy_lock:
                result = self.care_actions.apply(intent, None, now, at)
            self.storage.append(result.to_record(at))
            return result.reply if result.handled else None

        session = self.checkins.active(now)
        if session is None:
            return None

        intent = None
        if self.dialogue is not None:
            intent = self.dialogue.classify(text, session.clock, session.level)
            if live_clock and time.monotonic() > session.deadline:
                self.checkins.close(session.candidate_id)
                return None
            if live_clock:
                now = time.monotonic()
                at = datetime.now().astimezone()
        if intent is None and match_snooze(text):
            intent = CareIntent(
                "snooze", None, None, None, 1.0, "short_delay",
                source="fallback")
        if intent is None:
            return None

        with self._policy_lock:
            result = self.care_actions.apply(intent, session, now, at)
        if not result.handled:
            return None
        self.storage.append(result.to_record(at))
        if not result.committed:
            if result.reason_code == "clarification_required":
                if not self.checkins.extend_for_clarification(
                        session.candidate_id, now):
                    return None
            return result.reply

        self.checkins.close(session.candidate_id)
        outcome = None
        if result.action == "snooze":
            outcome = self.outcomes.snooze(session.candidate_id, at)
        elif result.action in ("timed_dnd", "cycle_dnd", "session_dnd"):
            outcome = self.outcomes.resolve(session.candidate_id, at, "care_dnd")
        elif result.action == "decline_once":
            outcome = self.outcomes.resolve(session.candidate_id, at, "declined")
        # accept giữ watch: chỉ sensor/cycle reset mới được ghi accepted.
        if outcome is not None:
            self.storage.append(outcome.to_record())
        return result.reply

    def try_snooze(self, text, now=None, at=None):
        """Alias tương thích SALM-1 cũ; đường mới xử lý toàn bộ care response."""
        return self.try_care_response(text, now=now, at=at)

    def _drop_checkin(self, token):
        self.checkins.close(token)
        self.outcomes.discard(token)

    def _cancel_checkin(self, decision, text):
        token = decision.candidate_id
        self.checkins.close(token)
        try:
            self.on_checkin("cancel", decision, text)
        finally:
            outcome = self.outcomes.cancel(token, datetime.now().astimezone())
            if outcome is not None:
                self.storage.append(outcome.to_record())

    def _cancel_care(self, token):
        self.on_care("cancel", token)
        outcome = self.outcomes.cancel(token, datetime.now().astimezone())
        if outcome is not None:
            self.storage.append(outcome.to_record())
