"""Lifecycle runtime của SALM: collector 0A + policy/intervention 0B."""

import threading
import time
from datetime import datetime
from pathlib import Path

from features.salm.care_action import CareActionPolicy
from features.salm.care_dnd import UserCareDnd
from features.salm.care_language import (CARE_LANGUAGE_TIMEOUT_SECONDS,
                                         CareLanguage)
from features.salm.care_style import (CareStyleStore, match_care_style_command,
                                      style_confirmation)
from features.salm.checkin import (CheckInResponseWindow, match_resume_care,
                                   match_snooze, checkin_text)
from features.salm.dialogue import CareDialogue, CareIntent
from features.salm.engine import SalmEngine
from features.salm.intervention import Intervention, InterventionGate
from features.salm.late_night import (LateNightEvaluator, LateNightLanguage,
                                      LateNightPolicyStore, format_clock,
                                      match_late_night_command)
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
                 on_activity=None,
                 welcome_tracker=None, gentle_checkin=False, on_checkin=None,
                 checkin_window=None, care_llm=None, care_llm_intent=False,
                 care_llm_language=False,
                 care_language_timeout=CARE_LANGUAGE_TIMEOUT_SECONDS,
                 address_form_provider=None, user_dnd=False, care_dnd=None,
                 care_actions=None, care_language=None,
                 care_style_enabled=False, care_style=None,
                 on_care_style=None, on_debug=None,
                 persona_context_provider=None, proactive_text_provider=None,
                 late_night_enabled=True, late_night_language_enabled=False,
                 late_night_min_active_seconds=15 * 60.0,
                 late_night_policy=None, late_night_evaluator=None,
                 late_night_language=None, on_late_night=None):
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
        self.on_activity = on_activity
        self.welcome = welcome_tracker or ReturnWelcomeTracker()
        self.gentle_checkin = bool(gentle_checkin)
        self.on_checkin = on_checkin
        self.checkins = checkin_window or CheckInResponseWindow()
        self.care_style_enabled = bool(care_style_enabled)
        self._address_form_provider = address_form_provider
        self.on_care_style = on_care_style
        self.on_debug = on_debug
        style_path = Path(data_dir) / "care-style.json" if data_dir else None
        self.care_style = care_style or CareStyleStore(style_path)
        self.care_llm_intent = bool(care_llm_intent and care_llm is not None)
        self.dialogue = CareDialogue(care_llm) if self.care_llm_intent else None
        self.care_llm_language = bool(care_llm_language and care_llm is not None)
        self.care_language = care_language or CareLanguage(
            care_llm if self.care_llm_language else None,
            timeout_seconds=care_language_timeout,
            address_form_provider=address_form_provider,
            style_provider=(self.care_style.snapshot
                            if self.care_style_enabled else None),
            persona_context_provider=persona_context_provider,
            proactive_text_provider=proactive_text_provider)
        self.late_night_enabled = bool(late_night_enabled)
        self.on_late_night = on_late_night
        late_policy_path = (Path(data_dir) / "late-night-policy.json"
                            if data_dir else None)
        self.late_night_policy = late_night_policy or LateNightPolicyStore(
            late_policy_path, database=getattr(self.storage, "database", None))
        self.late_night = late_night_evaluator or LateNightEvaluator(
            self.late_night_policy,
            min_active_seconds=late_night_min_active_seconds)
        self.late_night_language = late_night_language or LateNightLanguage(
            care_llm if late_night_language_enabled else None,
            timeout_seconds=care_language_timeout,
            address_form_provider=address_form_provider,
            persona_context_provider=persona_context_provider,
            proactive_text_provider=proactive_text_provider)
        dnd_path = Path(data_dir) / "care-dnd.json" if data_dir else None
        self.care_dnd = care_dnd or UserCareDnd(dnd_path, enabled=user_dnd)
        self.user_dnd = bool(user_dnd)
        self.care_actions = care_actions or CareActionPolicy(
            self.policy, self.care_dnd, self.gate,
            user_dnd_enabled=self.user_dnd,
            address_form_provider=address_form_provider)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._last_error = None
        self._last_policy_signature = None
        self._last_policy_record = None
        self._last_debug_signature = None

    def _debug(self, category, message, data=None, level="INFO"):
        if self.on_debug is None:
            return
        try:
            self.on_debug(category, message, data or {}, level=level)
        except Exception:
            # Observer debug không được làm chết collector sức khỏe.
            pass

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
                    "late-night=%s, WASAPI fallback=%s).", self.policy_shadow,
                    self.silent_care, self.gentle_checkin,
                    self.late_night_enabled, self.wasapi_fallback)
        self._debug("activity", "Bộ nhận diện hoạt động máy đã khởi động", {
            "poll_seconds": self.poll_seconds,
            "policy_shadow": self.policy_shadow,
            "silent_care": self.silent_care,
            "gentle_checkin": self.gentle_checkin,
            "late_night_enabled": self.late_night_enabled,
            "late_night_policy": self.late_night_policy.snapshot(),
            "gsmtc_available": bool(self.gsmtc.available),
            "wasapi_fallback": self.wasapi_fallback,
        })
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
        self._debug("activity", "Bộ nhận diện hoạt động máy đã dừng")

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
                "care_llm_language": self.care_llm_language,
                "care_style_learning": self.care_style_enabled,
                "care_style": self.care_style.snapshot(),
                "late_night_enabled": self.late_night_enabled,
                "late_night_policy": self.late_night_policy.snapshot(),
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

    def clear_activity_history(self):
        """Xoá dữ liệu đã lưu và reset projection đang giữ để nó không hồi sinh lúc flush."""
        with self._lock:
            result = self.storage.clear_history()
            self.engine = SalmEngine(max_sample_gap=self.engine.max_sample_gap)
            self.late_night.reset_runtime()
            self._last_debug_signature = None
        self._debug("activity", "Đã xóa lịch sử Activity Insights", result,
                    level="SUCCESS")
        return result

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
                    self._emit_activity_change(snapshot, update.state, clocks)
                    if self.on_activity is not None:
                        try:
                            self.on_activity(update.state, snapshot)
                        except Exception:
                            logger.warning("SALM activity observer failed", exc_info=True)
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
                    late_dispatched = False
                    if self.late_night_enabled:
                        with self._policy_lock:
                            shared_cooldown = self.policy.cue_cooldown_active(
                                snapshot.monotonic)
                        signal = self.late_night.evaluate(
                            snapshot, update.state, self.gate,
                            shared_cooldown=shared_cooldown)
                        late_dispatched = self._handle_late_night_signal(signal)
                        if late_dispatched:
                            with self._policy_lock:
                                self.policy.register_external_cue(snapshot.monotonic)
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
                    self._debug("activity", "Lỗi khi đọc hoạt động máy",
                                {"error": self._last_error}, level="ERROR")
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

    def _emit_activity_change(self, snapshot, state, clocks):
        """Phát khi trạng thái suy diễn đổi; không spam panel theo nhịp poll một giây."""
        signature = (state.signature(), state.confidence, state.evidence,
                     bool(snapshot.foreground_fullscreen), snapshot.session_locked)
        if signature == self._last_debug_signature:
            return
        self._last_debug_signature = signature
        app = state.primary_app or "không rõ ứng dụng"
        message = (f"{state.activity.value} · {state.presence.value} · {app}"
                   f" · màn hình {state.display.value}")
        self._debug("activity", message, {
            "presence": state.presence.value,
            "activity": state.activity.value,
            "display": state.display.value,
            "media": state.media.value,
            "foreground_app": state.primary_app,
            "foreground_fullscreen": bool(snapshot.foreground_fullscreen),
            "idle_seconds": (None if snapshot.idle_seconds is None
                             else round(snapshot.idle_seconds, 1)),
            "session_locked": snapshot.session_locked,
            "meeting_open": state.meeting_open,
            "confidence": state.confidence.value,
            "evidence": list(state.evidence),
            "work_seconds": round(clocks.get("work_engagement", 0.0), 1),
            "screen_seconds": round(clocks.get("screen_exposure", 0.0), 1),
            "gate_reasons": list(self.gate.reasons("break_care")),
        })

    def _handle_late_night_signal(self, signal):
        if signal is None:
            return False
        record = signal.to_record()
        self.storage.append(record)
        self._debug("care", f"Late-night Care: {signal.action}", record,
                    level=("INFO" if signal.action == "dispatch" else "DEBUG"))
        if signal.action != "dispatch":
            return False
        if self.dispatcher is None or self.on_late_night is None:
            logger.warning("Late-night Care đủ điều kiện nhưng chưa có presenter.")
            return False
        cancelled = threading.Event()

        def present():
            text = self.late_night_language.generate(signal)
            if cancelled.is_set() or self.gate.reasons("break_care"):
                return
            self.on_late_night("present", signal, text)

        def cancel():
            cancelled.set()
            self.on_late_night("cancel", signal, None)

        intervention = Intervention(
            kind="salm_late_night", scope="break_care",
            token=signal.candidate_id, present=present, cancel=cancel)
        if not self.dispatcher.submit(intervention):
            logger.debug("Late-night Care bị gate chặn sát lúc dispatch: %s",
                         signal.candidate_id)
            return False
        return True

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
            self._debug("care", f"SALM policy: {decision.action}", record,
                        level=("INFO" if decision.action == "dispatch" else "DEBUG"))
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
        fallback_text = checkin_text(decision.clock, decision.level)
        cancelled = threading.Event()
        self.outcomes.watch(decision, cycle_id, now, checkin=True)

        def present():
            text = self.care_language.generate_initial(
                decision.clock, decision.level)
            # Model chạy sau lần gate-check của dispatcher; kiểm lại ngay trước TTS để
            # work mode/meeting/fullscreen bật trong lúc generate vẫn chặn tuyệt đối.
            if (cancelled.is_set() or (self.care_llm_language
                                       and self.gate.reasons("break_care"))):
                self.outcomes.discard(token)
                return
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

        def cancel():
            cancelled.set()
            self._cancel_checkin(decision, fallback_text)

        intervention = Intervention(
            kind="salm_gentle_checkin",
            scope="break_care",
            token=token,
            present=present,
            cancel=cancel,
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
            return (self._generated_reply(result, None)
                    if result.handled else None)

        session = self.checkins.active(now)
        if session is None:
            return None

        # Trong response window, một lệnh chỉnh rõ phạm vi SALM là follow-up tự nhiên
        # và không được rơi sang intent LLM rồi biến nhầm thành snooze/DND.
        style_reply = self.try_style_command(text)
        if style_reply is not None:
            return style_reply

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
        return self._generated_reply(result, session)

    def care_style_snapshot(self):
        """Snapshot cho HUD; cách gọi chỉ được đọc động, tuyệt đối không ghi vào kho SALM."""
        payload = self.care_style.snapshot()
        try:
            address = (self._address_form_provider()
                       if self._address_form_provider is not None else None)
        except Exception:
            address = None
        from features.salm.welcome import safe_address_form
        payload["address_form"] = safe_address_form(address)
        return payload

    def try_style_command(self, text):
        """Áp preference chỉ khi cờ bật và câu lệnh có phạm vi nhắc nghỉ tường minh."""
        if not self.care_style_enabled:
            return None
        command = match_care_style_command(text)
        if command is None:
            return None
        action = command["action"]
        if action == "show":
            self._emit_care_style()
            return "Em đã mở phần phong cách nhắc nghỉ."
        if action == "reset":
            self.care_style.reset()
            self._emit_care_style()
            return style_confirmation({}, reset=True)
        changes = command["changes"]
        if not self.care_style.update(changes):
            return None
        self._emit_care_style()
        return style_confirmation(changes)

    def try_late_night_command(self, text, now=None, at=None):
        """Áp policy nhắc khuya chỉ từ câu lệnh có phạm vi tường minh."""
        command = match_late_night_command(text)
        if command is None:
            return None
        if not self.late_night_enabled:
            return "Tính năng nhắc khuya đang bị tắt trong cấu hình hệ thống."

        now = time.monotonic() if now is None else float(now)
        at = at or datetime.now().astimezone()
        action = command["action"]
        if action == "show":
            policy = self.late_night_policy.snapshot()
            if not policy.get("enabled"):
                return "Nhắc khuya hiện đang tắt."
            return ("Nhắc khuya đang bật sau "
                    f"{format_clock(policy['cutoff_minute'])}.")
        if action == "need_cutoff":
            return "Bạn muốn tôi bắt đầu nhắc khuya từ mấy giờ?"
        if action == "invalid_snooze":
            return "Bạn có thể hoãn nhắc khuya từ 1 đến 180 phút."
        if action in ("mute_tonight", "snooze"):
            if not self.late_night_policy.snapshot().get("enabled"):
                return "Nhắc khuya hiện đang tắt."
        if action == "enable":
            policy = self.late_night_policy.configure(command["cutoff_minute"])
            self.late_night.reset_runtime()
            reply = ("Đã bật nhắc khuya sau "
                     f"{format_clock(policy['cutoff_minute'])}.")
        elif action == "disable":
            self.late_night_policy.disable()
            self.late_night.reset_runtime()
            reply = "Đã tắt nhắc khuya."
        elif action == "reset":
            self.late_night_policy.reset()
            self.late_night.reset_runtime()
            reply = "Đã đặt lại và tắt nhắc khuya."
        elif action == "mute_tonight":
            self.late_night.mute_tonight(at)
            reply = "Được, tối nay tôi sẽ không nhắc khuya nữa."
        elif action == "snooze":
            minutes = self.late_night.snooze(now, command["minutes"])
            reply = f"Được, tôi sẽ hoãn nhắc khuya {minutes} phút."
        else:
            return None

        record = {
            "kind": "late_night_policy_change",
            "at": at.isoformat(),
            "action": action,
            "source": "explicit_user",
        }
        if "cutoff_minute" in command:
            record["cutoff_minute"] = command["cutoff_minute"]
        if "minutes" in command:
            record["minutes"] = command["minutes"]
        self.storage.append(record)
        self._debug("care", "Đã cập nhật Late-night Care", record,
                    level="SUCCESS")
        return reply

    def reset_care_style(self):
        if not self.care_style_enabled:
            return None
        self.care_style.reset()
        snapshot = self.care_style_snapshot()
        self._emit_care_style(snapshot)
        return snapshot

    def _emit_care_style(self, snapshot=None):
        if self.on_care_style is not None:
            try:
                self.on_care_style(snapshot or self.care_style_snapshot())
            except Exception:
                logger.warning("SALM không mở được HUD care style", exc_info=True)

    def _generated_reply(self, result, session):
        """Chỉ gọi NLG sau khi CareActionPolicy đã validate và commit."""
        if not result.committed:
            return result.reply
        return self.care_language.generate_reply(
            result,
            clock=(session.clock if session is not None else None),
            level=(session.level if session is not None else None))

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
