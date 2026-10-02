"""Media probes của SALM: GSMTC chính, WASAPI rolling fallback tùy chọn."""

import asyncio
import os
import threading
import time
from collections import defaultdict, deque

from features.salm.windows import is_process_in_current_session, normalize_app_id
from utils.logger import get_logger

logger = get_logger(__name__)

AUDIO_PEAK_EPSILON = 0.001
AUDIO_ACTIVE_WINDOW_SECONDS = 3.0
AUDIO_HANGOVER_SECONDS = 8.0
AUDIO_MIN_ACTIVE_SAMPLES = 2


class RollingAudioActivity:
    """Lọc peak tức thời: 2 mẫu/3s mới active, mất peak 8s mới inactive."""

    def __init__(self, epsilon=AUDIO_PEAK_EPSILON,
                 active_window=AUDIO_ACTIVE_WINDOW_SECONDS,
                 hangover=AUDIO_HANGOVER_SECONDS,
                 min_samples=AUDIO_MIN_ACTIVE_SAMPLES):
        self.epsilon = float(epsilon)
        self.active_window = float(active_window)
        self.hangover = float(hangover)
        self.min_samples = int(min_samples)
        self._peaks = defaultdict(deque)
        self._activated = set()
        self._last_peak = {}

    def update(self, samples, now=None):
        now = time.monotonic() if now is None else float(now)
        # Nhiều audio session của cùng process trong MỘT poll vẫn chỉ là một mẫu;
        # nếu không, hai session Chrome có thể giả thành "2 mẫu trong 3 giây".
        aggregated = {}
        for app_id, peak, session_active in samples:
            if not app_id or not session_active:
                continue
            peak = 0.0 if peak is None else float(peak)
            aggregated[app_id] = max(peak, aggregated.get(app_id, 0.0))
        for app_id, peak in aggregated.items():
            points = self._peaks[app_id]
            while points and now - points[0] > self.active_window:
                points.popleft()
            if peak > self.epsilon:
                points.append(now)
                self._last_peak[app_id] = now
            if len(points) >= self.min_samples:
                self._activated.add(app_id)

        active = set()
        for app_id in list(self._activated):
            last = self._last_peak.get(app_id)
            if last is not None and now - last <= self.hangover:
                active.add(app_id)
            else:
                self._activated.discard(app_id)
                self._last_peak.pop(app_id, None)
                self._peaks.pop(app_id, None)
        return frozenset(active)


class WasapiProbe:
    def __init__(self, rolling=None):
        self.rolling = rolling or RollingAudioActivity()
        self.available = os.name == "nt"

    def sample(self, now=None):
        if not self.available:
            return frozenset()
        samples = []
        try:
            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
            for session in AudioUtilities.GetAllSessions():
                try:
                    process = session.Process
                    if process and not is_process_in_current_session(process.pid):
                        continue
                    app_id = normalize_app_id(process.name() if process else None)
                    meter = session._ctl.QueryInterface(IAudioMeterInformation)
                    peak = meter.GetPeakValue()
                    state = session.State
                    state_value = getattr(state, "value", state)
                    if process is None or int(process.pid) != os.getpid():
                        samples.append((app_id, peak, int(state_value) == 1))
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("WASAPI SALM tạm không khả dụng: %s", exc)
            return self.rolling.update((), now=now)
        return self.rolling.update(samples, now=now)


class GsmtcProbe:
    """Cache GSMTC trên thread asyncio riêng; thiếu WinRT thì tự tắt."""

    def __init__(self, poll_seconds=1.0):
        self.poll_seconds = max(0.25, float(poll_seconds))
        self.available = False
        self._apps = frozenset()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._manager_type = self._find_manager()

    @staticmethod
    def _find_manager():
        for module in ("winsdk.windows.media.control", "winrt.windows.media.control"):
            try:
                imported = __import__(module, fromlist=["GlobalSystemMediaTransportControlsSessionManager"])
                return imported.GlobalSystemMediaTransportControlsSessionManager
            except (ImportError, AttributeError):
                continue
        return None

    def start(self):
        if self._manager_type is None or self._thread is not None:
            return False
        self._thread = threading.Thread(target=self._run, name="salm-gsmtc", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def apps(self):
        with self._lock:
            return self._apps

    def _run(self):
        try:
            asyncio.run(self._poll())
        except Exception as exc:
            logger.warning("GSMTC SALM dừng; media sẽ degrade/fallback: %s", exc)
        finally:
            self.available = False

    async def _poll(self):
        manager = await self._manager_type.request_async()
        self.available = True
        while not self._stop.is_set():
            playing = set()
            for session in manager.get_sessions():
                try:
                    info = session.get_playback_info()
                    status = getattr(info.playback_status, "value", info.playback_status)
                    if int(status) == 4:  # GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING
                        app_id = normalize_app_id(session.source_app_user_model_id)
                        if app_id:
                            playing.add(app_id)
                except Exception:
                    continue
            with self._lock:
                self._apps = frozenset(playing)
            await asyncio.sleep(self.poll_seconds)
