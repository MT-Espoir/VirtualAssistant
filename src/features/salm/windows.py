"""Adapter Win32 tối thiểu cho SALM.

Module chỉ trả metadata process/app. Không đọc title cửa sổ, phím, URL hay nội dung.
Mọi API đều fail-soft để SALM không thể làm chết vòng lặp trợ lý.
"""

import ctypes
import os
import re
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import psutil

from features.salm.app_identity import is_user_facing_app_id
from features.salm.models import ActivitySnapshot, DisplayState


_MEETING_APPS = frozenset(("zoom", "teams", "ms-teams"))
_SHELL_WINDOW_CLASSES = frozenset(("progman", "workerw", "shell_traywnd"))

_GWL_EXSTYLE = -20
_GW_OWNER = 4
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_DWMWA_CLOAKED = 14


def normalize_app_id(value):
    """Chuẩn hóa tên executable/AUMID nhưng không giữ path hay command line."""
    if not value:
        return None
    name = Path(str(value).replace("\\", "/")).name.lower().strip()
    if name.endswith(".exe"):
        name = name[:-4]
    compact = re.sub(r"[-_\s]+", "-", name).strip("-")
    aliases = {
        "msteams": "ms-teams",
        "microsoft-teams": "ms-teams",
        "teamsbootstrapper": "ms-teams",
        "zoom-meetings": "zoom",
        "code-insiders": "code",
    }
    for marker, app_id in (("googlechrome", "chrome"), ("chrome", "chrome"),
                           ("videolan", "vlc"), ("spotify", "spotify")):
        if marker in compact:
            return app_id
    return aliases.get(compact, compact or None)


if os.name == "nt":
    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = (("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD))

    class _GUID(ctypes.Structure):
        _fields_ = (("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8))

    class _POWERBROADCAST_SETTING(ctypes.Structure):
        _fields_ = (("PowerSetting", _GUID), ("DataLength", wintypes.DWORD),
                    ("Data", ctypes.c_ubyte * 1))

    _WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)

    class _WNDCLASSW(ctypes.Structure):
        _fields_ = (("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
                    ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR))

    # ctypes mặc định coi giá trị trả về là int 32-bit; HWND/HMONITOR trên máy 64-bit
    # sẽ bị cắt nếu không khai báo prototype.
    ctypes.windll.user32.GetForegroundWindow.restype = wintypes.HWND
    ctypes.windll.user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    ctypes.windll.user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    ctypes.windll.user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    ctypes.windll.user32.IsWindowVisible.restype = wintypes.BOOL
    ctypes.windll.user32.IsIconic.argtypes = (wintypes.HWND,)
    ctypes.windll.user32.IsIconic.restype = wintypes.BOOL
    ctypes.windll.user32.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
    ctypes.windll.user32.GetWindow.restype = wintypes.HWND
    ctypes.windll.user32.GetShellWindow.restype = wintypes.HWND
    ctypes.windll.user32.GetClassNameW.argtypes = (
        wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    ctypes.windll.user32.GetClassNameW.restype = ctypes.c_int
    ctypes.windll.user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    ctypes.windll.user32.GetWindowLongW.restype = ctypes.c_long
    ctypes.windll.user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    ctypes.windll.user32.GetWindowRect.restype = wintypes.BOOL
    ctypes.windll.kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    ctypes.windll.kernel32.GetCurrentProcessId.restype = wintypes.DWORD
    ctypes.windll.kernel32.ProcessIdToSessionId.argtypes = (
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    ctypes.windll.kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    ctypes.windll.user32.MonitorFromWindow.restype = wintypes.HANDLE
    ctypes.windll.user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    ctypes.windll.user32.CreateWindowExW.restype = wintypes.HWND
    ctypes.windll.user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
    ctypes.windll.user32.RegisterPowerSettingNotification.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(_GUID), wintypes.DWORD)
    ctypes.windll.user32.UnregisterPowerSettingNotification.argtypes = (wintypes.HANDLE,)
    ctypes.windll.user32.UnregisterPowerSettingNotification.restype = wintypes.BOOL
    ctypes.windll.user32.DefWindowProcW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    ctypes.windll.user32.DefWindowProcW.restype = ctypes.c_ssize_t
    ctypes.windll.user32.CreateWindowExW.argtypes = (
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
    ctypes.windll.user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
    ctypes.windll.user32.UnregisterClassW.restype = wintypes.BOOL
    ctypes.windll.user32.PostMessageW.argtypes = (
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    ctypes.windll.user32.PostMessageW.restype = wintypes.BOOL
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute.argtypes = (
            wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD)
        ctypes.windll.dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    except (AttributeError, OSError):
        pass


def _guid(text):
    import uuid
    raw = uuid.UUID(text).bytes_le
    return _GUID.from_buffer_copy(raw)


def _uptime_seconds():
    return ctypes.windll.kernel32.GetTickCount64() / 1000.0 if os.name == "nt" else time.monotonic()


def is_process_in_current_session(pid):
    """Whether PID belongs to SALM's interactive Windows session."""
    if os.name != "nt":
        return True
    current = wintypes.DWORD()
    candidate = wintypes.DWORD()
    kernel32 = ctypes.windll.kernel32
    if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(),
                                        ctypes.byref(current)):
        return False
    if not kernel32.ProcessIdToSessionId(int(pid), ctypes.byref(candidate)):
        return False
    return current.value == candidate.value


def _window_is_user_facing(*, visible, iconic, cloaked, is_shell,
                           class_name, ex_style, has_owner,
                           width, height):
    """Pure window-role filter; names/titles/content are deliberately not read."""
    if not (visible or iconic) or cloaked or is_shell:
        return False
    if str(class_name or "").lower() in _SHELL_WINDOW_CLASSES:
        return False
    if width <= 0 or height <= 0:
        return False
    is_tool = bool(ex_style & _WS_EX_TOOLWINDOW)
    is_app = bool(ex_style & _WS_EX_APPWINDOW)
    if is_tool and not is_app:
        return False
    # Owned popups/dialogs count only when Windows explicitly exposes them as app windows.
    if has_owner and not is_app:
        return False
    return True


class PowerEventWatcher:
    """Hidden-window listener cho display, session lock và suspend/resume."""

    WM_POWERBROADCAST = 0x0218
    WM_WTSSESSION_CHANGE = 0x02B1
    WM_CLOSE = 0x0010
    PBT_APMSUSPEND = 0x0004
    PBT_APMRESUMESUSPEND = 0x0007
    PBT_APMRESUMEAUTOMATIC = 0x0012
    PBT_POWERSETTINGCHANGE = 0x8013
    WTS_SESSION_LOCK = 0x7
    WTS_SESSION_UNLOCK = 0x8
    DEVICE_NOTIFY_WINDOW_HANDLE = 0
    NOTIFY_FOR_THIS_SESSION = 0
    DISPLAY_GUID = "6fe69556-704a-47a0-8f24-c28d936fda47"

    def __init__(self):
        # App vừa được người dùng mở thường bắt đầu khi display đang sáng; Windows sẽ
        # sửa lại bằng event ngay khi dim/off. Trên non-Windows dùng UNKNOWN.
        self.display = DisplayState.ON if os.name == "nt" else DisplayState.UNKNOWN
        self.session_locked = None
        self.suspended = False
        self._lock = threading.Lock()
        self._thread = None
        self._started = threading.Event()
        self._hwnd = None
        self._wndproc_ref = None
        self._suspend_started = None
        self._pending_no_screen_break = 0.0
        self._resume_at = None

    def start(self):
        if os.name != "nt" or self._thread is not None:
            return os.name == "nt"
        self._thread = threading.Thread(target=self._run, name="salm-power", daemon=True)
        self._thread.start()
        self._started.wait(3)
        ok = self._hwnd is not None
        if not ok:
            with self._lock:
                self.display = DisplayState.UNKNOWN
        return ok

    def stop(self):
        hwnd = self._hwnd
        if os.name == "nt" and hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, self.WM_CLOSE, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)

    def snapshot(self):
        with self._lock:
            return self.display, self.session_locked, self.suspended

    def consume_no_screen_break(self):
        with self._lock:
            value = self._pending_no_screen_break
            self._pending_no_screen_break = 0.0
            return value

    def gate_idle_after_resume(self, idle_seconds, now_monotonic=None):
        """Resume tự động vẫn UNKNOWN cho tới khi có input mới sau resume."""
        with self._lock:
            if self._resume_at is None:
                return idle_seconds
            elapsed = max(0.0, _uptime_seconds() - self._resume_at)
            if idle_seconds is not None and idle_seconds <= elapsed + 0.05:
                self._resume_at = None
                return idle_seconds
            return None

    def _run(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        wtsapi32 = ctypes.windll.wtsapi32
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = f"SALM_POWER_{os.getpid()}_{id(self)}"

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == self.WM_POWERBROADCAST:
                if wparam == self.PBT_POWERSETTINGCHANGE and lparam:
                    setting = ctypes.cast(lparam, ctypes.POINTER(_POWERBROADCAST_SETTING)).contents
                    if bytes(setting.PowerSetting) == bytes(_guid(self.DISPLAY_GUID)):
                        value = int(setting.Data[0]) if setting.DataLength else -1
                        with self._lock:
                            self.display = {0: DisplayState.OFF, 1: DisplayState.ON,
                                            2: DisplayState.DIM}.get(value, DisplayState.UNKNOWN)
                elif wparam == self.PBT_APMSUSPEND:
                    with self._lock:
                        self.suspended = True
                        if self._suspend_started is None:
                            self._suspend_started = _uptime_seconds()
                elif wparam in (self.PBT_APMRESUMESUSPEND, self.PBT_APMRESUMEAUTOMATIC):
                    with self._lock:
                        self.suspended = False
                        now = _uptime_seconds()
                        if self._suspend_started is not None:
                            self._pending_no_screen_break += max(
                                0.0, now - self._suspend_started)
                        self._suspend_started = None
                        self._resume_at = now
                return 1
            if msg == self.WM_WTSSESSION_CHANGE:
                if wparam in (self.WTS_SESSION_LOCK, self.WTS_SESSION_UNLOCK):
                    with self._lock:
                        self.session_locked = wparam == self.WTS_SESSION_LOCK
                return 0
            if msg == self.WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == 0x0002:  # WM_DESTROY
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = _WNDPROC(wndproc)
        wc = _WNDCLASSW(lpfnWndProc=self._wndproc_ref, hInstance=hinstance,
                        lpszClassName=class_name)
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            self._started.set()
            return
        hwnd = user32.CreateWindowExW(0, class_name, class_name, 0, 0, 0, 0, 0,
                                     None, None, hinstance, None)
        if not hwnd:
            user32.UnregisterClassW(class_name, hinstance)
            self._started.set()
            return
        self._hwnd = hwnd
        power_handle = ctypes.windll.user32.RegisterPowerSettingNotification(
            hwnd, ctypes.byref(_guid(self.DISPLAY_GUID)), self.DEVICE_NOTIFY_WINDOW_HANDLE)
        wtsapi32.WTSRegisterSessionNotification(hwnd, self.NOTIFY_FOR_THIS_SESSION)
        self._started.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        try:
            if power_handle:
                user32.UnregisterPowerSettingNotification(power_handle)
            wtsapi32.WTSUnRegisterSessionNotification(hwnd)
            user32.UnregisterClassW(class_name, hinstance)
        finally:
            self._hwnd = None


class WindowsActivityProbe:
    def __init__(self, power=None, meeting_state=None):
        self.power = power or PowerEventWatcher()
        self.meeting_state = meeting_state or (lambda: None)

    @staticmethod
    def idle_seconds():
        if os.name != "nt":
            return None
        info = _LASTINPUTINFO(cbSize=ctypes.sizeof(_LASTINPUTINFO))
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        now = ctypes.windll.kernel32.GetTickCount()
        return ((int(now) - int(info.dwTime)) & 0xFFFFFFFF) / 1000.0

    @staticmethod
    def _foreground():
        if os.name != "nt":
            return None, None, False
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None, None, False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value or 0) == os.getpid():
            return None, int(pid.value), False
        try:
            app_id = normalize_app_id(psutil.Process(pid.value).name())
        except (psutil.Error, OSError):
            app_id = None
        return app_id, int(pid.value) or None, _is_fullscreen(hwnd)

    @staticmethod
    def _window_app_ids():
        """Return apps owning real top-level windows on the interactive desktop.

        EnumWindows is the source of candidates. Process enumeration is intentionally not
        used: a service/helper merely existing is not evidence of a user-facing app.
        """
        if os.name != "nt":
            return frozenset()
        user32 = ctypes.windll.user32
        try:
            dwmapi = ctypes.windll.dwmapi
        except (AttributeError, OSError):
            dwmapi = None
        shell_hwnd = user32.GetShellWindow()
        pids = set()
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _):
            try:
                visible = bool(user32.IsWindowVisible(hwnd))
                iconic = bool(user32.IsIconic(hwnd))
                rect = wintypes.RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
                class_buffer = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
                ex_style = int(user32.GetWindowLongW(hwnd, _GWL_EXSTYLE))
                owner = user32.GetWindow(hwnd, _GW_OWNER)
                cloaked = False
                if dwmapi is not None:
                    value = wintypes.DWORD()
                    try:
                        result = dwmapi.DwmGetWindowAttribute(
                            hwnd, _DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
                        cloaked = result == 0 and bool(value.value)
                    except (AttributeError, OSError):
                        pass
                if not _window_is_user_facing(
                        visible=visible, iconic=iconic, cloaked=cloaked,
                        is_shell=bool(shell_hwnd and hwnd == shell_hwnd),
                        class_name=class_buffer.value, ex_style=ex_style,
                        has_owner=bool(owner), width=int(rect.right - rect.left),
                        height=int(rect.bottom - rect.top)):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value and int(pid.value) != os.getpid():
                    pids.add(int(pid.value))
            except (OSError, ValueError):
                pass
            return True

        callback = callback_type(visit)
        user32.EnumWindows(callback, 0)
        apps = set()
        for pid in pids:
            try:
                app_id = normalize_app_id(psutil.Process(pid).name())
                if is_user_facing_app_id(app_id):
                    apps.add(app_id)
            except (psutil.Error, OSError):
                continue
        return frozenset(apps)

    @classmethod
    def _running_apps(cls, foreground_app=None, media_apps=frozenset()):
        """Apps with current user-facing evidence, not the machine's process list."""
        apps = set(cls._window_app_ids())
        if is_user_facing_app_id(foreground_app):
            apps.add(foreground_app)
        apps.update(app for app in media_apps if is_user_facing_app_id(app))
        return frozenset(apps)

    @staticmethod
    def _desktop_meeting_open():
        if os.name != "nt":
            return False
        pids = set()
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def visit(hwnd, _):
            if ctypes.windll.user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    pids.add(int(pid.value))
            return True

        callback = callback_type(visit)
        ctypes.windll.user32.EnumWindows(callback, 0)
        for pid in pids:
            try:
                if normalize_app_id(psutil.Process(pid).name()) in _MEETING_APPS:
                    return True
            except (psutil.Error, OSError):
                continue
        return False

    def collect(self, gsmtc_apps=frozenset(), audible_apps=frozenset()):
        mono = time.monotonic()
        wall = datetime.now().astimezone()
        gsmtc_apps = frozenset(
            app for app in gsmtc_apps if is_user_facing_app_id(app))
        audible_apps = frozenset(
            app for app in audible_apps if is_user_facing_app_id(app))
        try:
            foreground, pid, fullscreen = self._foreground()
        except Exception:
            foreground, pid, fullscreen = None, None, False
        try:
            display, locked, suspended = self.power.snapshot()
        except Exception:
            display, locked, suspended = DisplayState.UNKNOWN, None, False
        try:
            desktop_meeting = self._desktop_meeting_open()
            meet = self.meeting_state()
            meeting_open = True if desktop_meeting or meet is True else (False if meet is False else None)
        except Exception:
            meeting_open = None
        try:
            media_apps = frozenset(gsmtc_apps) | frozenset(audible_apps)
            running = self._running_apps(foreground, media_apps)
        except Exception:
            running = frozenset()
        try:
            idle = self.idle_seconds()
        except Exception:
            idle = None
        try:
            idle = self.power.gate_idle_after_resume(idle, mono)
            no_screen_break = self.power.consume_no_screen_break()
        except (AttributeError, TypeError):
            no_screen_break = 0.0
        return ActivitySnapshot(
            monotonic=mono, wall_time=wall, idle_seconds=idle,
            foreground_app=foreground, foreground_pid=pid,
            foreground_fullscreen=fullscreen, display=display,
            session_locked=locked, suspended=suspended, running_apps=running,
            gsmtc_apps=frozenset(gsmtc_apps), audible_apps=frozenset(audible_apps),
            meeting_open=meeting_open,
            no_screen_break_seconds=no_screen_break,
        )


def _is_fullscreen(hwnd, tolerance=2):
    if os.name != "nt" or not hwnd:
        return False
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False

    class _MONITORINFO(ctypes.Structure):
        _fields_ = (("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD))

    user32 = ctypes.windll.user32
    user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_MONITORINFO))
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    monitor = user32.MonitorFromWindow(hwnd, 2)  # nearest
    info = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    monitor_rect = info.rcMonitor
    return (abs(rect.left - monitor_rect.left) <= tolerance
            and abs(rect.top - monitor_rect.top) <= tolerance
            and abs(rect.right - monitor_rect.right) <= tolerance
            and abs(rect.bottom - monitor_rect.bottom) <= tolerance)
