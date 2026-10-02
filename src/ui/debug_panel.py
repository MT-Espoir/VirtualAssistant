"""Panel debug thời gian thực cho assistant.

Chỉ lớp này biết Tkinter. Mọi producer chạy nền phát event qua AssistantBus; AvatarWindow
gọi ``append`` trên main thread khi poll queue.
"""

import io
import json
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = ImageTk = None


BG = "#080d12"
PANEL = "#0d1720"
CYAN = "#4cc9f0"
TEXT = "#d5edf7"
DIM = "#7193a3"
GREEN = "#72d6a0"
YELLOW = "#ffd166"
RED = "#ff6b6b"
MAX_LINES = 2500
MAX_PENDING = 2500

TAB_ROUTES = {
    "conversation": frozenset(("voice", "assistant", "agent", "llm", "ui")),
    "tools": frozenset(("tool",)),
    "activity": frozenset(("activity", "care")),
    "system": frozenset(("system", "log", "error")),
    "camera": frozenset(("camera",)),
}

TAB_LABELS = (
    ("all", "TẤT CẢ"),
    ("conversation", "LUỒNG CHÍNH"),
    ("tools", "TOOLS"),
    ("activity", "HOẠT ĐỘNG MÁY"),
    ("system", "HỆ THỐNG"),
    ("camera", "CAMERA"),
)


def event_tabs(category):
    """Các tab nhận category này; tách riêng để test không cần màn hình."""
    category = str(category or "system").lower()
    tabs = ["all"]
    tabs.extend(name for name, categories in TAB_ROUTES.items()
                if category in categories)
    if len(tabs) == 1:
        tabs.append("system")
    return tuple(tabs)


def format_event(event):
    raw_time = str(event.get("time") or "")
    shown_time = raw_time[11:23] if len(raw_time) >= 23 else raw_time
    category = str(event.get("category") or "system").upper()
    level = str(event.get("level") or "INFO").upper()
    thread = str(event.get("thread") or "").strip()
    message = str(event.get("message") or "").strip()
    source = f" [{thread}]" if thread and thread != "MainThread" else ""
    head = f"{shown_time}  {category:<10} {level:<7}{source} {message}\n"
    data = event.get("data") or {}
    if not data:
        return head
    details = json.dumps(data, ensure_ascii=False, separators=(", ", ": "), default=str)
    return head + f"              {details}\n"


class DebugPanel:
    def __init__(self, master, title="ASSISTANT DEBUG", camera=None):
        self.master = master
        self.title = title
        self.camera = camera
        self.win = None
        self._texts = {}
        self._event_count = 0
        self._paused = False
        self._pending = []
        self._auto_scroll = None
        self._status_var = None
        self._count_var = None
        self._pause_button = None
        self._camera_status = None
        self._camera_preview = None
        self._camera_log = None
        self._camera_photo = None
        self._camera_poll_id = None
        self._last_preview_at = None
        self._emotion_button = None
        self._emotion_status = None
        self._gesture_status = None
        self._proximity_status = None
        self._proximity_button = None
        self._head_status = None

    def _ensure(self):
        if self.win is not None and self.win.winfo_exists():
            return
        self.win = tk.Toplevel(self.master)
        self.win.title(self.title)
        self.win.configure(bg=BG)
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        width, height = min(900, max(680, sw - 120)), min(680, max(460, sh - 120))
        self.win.geometry(f"{width}x{height}+28+{max(28, sh - height - 70)}")
        self.win.minsize(620, 380)
        try:
            self.win.wm_attributes("-topmost", True)
            self.win.wm_attributes("-alpha", 0.96)
        except tk.TclError:
            pass
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        self.win.bind("<F12>", lambda _e: self.toggle())

        bar = tk.Frame(self.win, bg=PANEL, padx=10, pady=8)
        bar.pack(fill="x")
        self._status_var = tk.StringVar(value="TRẠNG THÁI: KHỞI ĐỘNG")
        tk.Label(bar, textvariable=self._status_var, bg=PANEL, fg=CYAN,
                 font=("Consolas", 10, "bold")).pack(side="left")
        self._count_var = tk.StringVar(value="0 EVENT")
        tk.Label(bar, textvariable=self._count_var, bg=PANEL, fg=DIM,
                 font=("Consolas", 9)).pack(side="left", padx=(18, 0))
        tk.Button(bar, text="XOÁ", command=self.clear, bg=PANEL, fg=TEXT,
                  activebackground=BG, activeforeground=CYAN, bd=0,
                  font=("Consolas", 9, "bold")).pack(side="right", padx=4)
        self._pause_button = tk.Button(
            bar, text="DỪNG LOG", command=self.toggle_pause, bg=PANEL, fg=TEXT,
            activebackground=BG, activeforeground=CYAN, bd=0,
            font=("Consolas", 9, "bold"))
        self._pause_button.pack(side="right", padx=4)
        self._auto_scroll = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="TỰ CUỘN", variable=self._auto_scroll,
                       bg=PANEL, fg=DIM, selectcolor=BG, activebackground=PANEL,
                       activeforeground=CYAN, font=("Consolas", 8)).pack(side="right")

        style = ttk.Style(self.win)
        style.configure("Debug.TNotebook", background=BG, borderwidth=0)
        style.configure("Debug.TNotebook.Tab", background=PANEL, foreground=DIM,
                        padding=(12, 7), font=("Consolas", 9, "bold"))
        style.map("Debug.TNotebook.Tab", background=[("selected", CYAN)],
                  foreground=[("selected", "#041016")])
        notebook = ttk.Notebook(self.win, style="Debug.TNotebook")
        notebook.pack(fill="both", expand=True, padx=8, pady=(6, 8))
        for key, label in TAB_LABELS:
            frame = tk.Frame(notebook, bg=BG)
            if key == "camera":
                self._build_camera_tab(frame)
                notebook.add(frame, text=label)
                continue
            text = ScrolledText(frame, bg=BG, fg=TEXT, insertbackground=TEXT,
                                selectbackground="#24506a", relief="flat", bd=0,
                                wrap="word", font=("Consolas", 9), padx=9, pady=8,
                                state="disabled")
            text.pack(fill="both", expand=True)
            text.tag_configure("DEBUG", foreground=DIM)
            text.tag_configure("INFO", foreground=TEXT)
            text.tag_configure("WARNING", foreground=YELLOW)
            text.tag_configure("ERROR", foreground=RED)
            text.tag_configure("SUCCESS", foreground=GREEN)
            notebook.add(frame, text=label)
            self._texts[key] = text

        footer = tk.Label(self.win, text="F12: ẩn/hiện  ·  đóng panel không tắt trợ lý",
                          bg=BG, fg=DIM, anchor="e", font=("Consolas", 8))
        footer.pack(fill="x", padx=12, pady=(0, 5))

    def show(self):
        self._ensure()
        self.win.deiconify()
        self.win.lift()
        setter = getattr(self.camera, "set_emotion_debug_visible", None)
        if setter is not None:
            setter(True)
        self._set_camera_preview_enabled(True)
        self._schedule_camera_refresh()

    def hide(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.withdraw()
            setter = getattr(self.camera, "set_emotion_debug_visible", None)
            if setter is not None:
                setter(False)
            self._set_camera_preview_enabled(False)
            if self._camera_preview is not None:
                self._camera_preview.configure(image="", text="Preview đang tạm ẩn.")
            self._camera_photo = None
            self._last_preview_at = None
            if self._camera_poll_id is not None:
                try:
                    self.win.after_cancel(self._camera_poll_id)
                except tk.TclError:
                    pass
                self._camera_poll_id = None

    def _set_camera_preview_enabled(self, enabled):
        if self.camera is not None:
            setter = getattr(self.camera, "set_preview_enabled", None)
            if setter is not None:
                setter(enabled)

    def _build_camera_tab(self, parent):
        proximity_bar = tk.Frame(parent, bg=PANEL, padx=10, pady=5)
        proximity_bar.pack(fill="x", padx=8, pady=(8, 0))
        self._proximity_status = tk.StringVar(value="VÙNG BÀN: CHƯA HIỆU CHỈNH · CHỈ DEBUG")
        tk.Label(proximity_bar, textvariable=self._proximity_status, bg=PANEL, fg=DIM,
                 font=("Consolas", 9, "bold"), anchor="w").pack(side="left", fill="x",
                                                               expand=True)
        self._proximity_button = tk.Button(
            proximity_bar, text="HIỆU CHỈNH", command=self._calibrate_proximity,
            bg=BG, fg=TEXT, activebackground=BG, activeforeground=CYAN,
            bd=1, font=("Consolas", 8, "bold"))
        self._proximity_button.pack(side="right")
        if self.camera is None or not hasattr(self.camera, "calibrate_proximity"):
            self._proximity_button.configure(state="disabled")
        self._head_status = tk.StringVar(value="CỬ CHỈ ĐẦU: CHỜ CAMERA · CHỈ DEBUG")
        tk.Label(parent, textvariable=self._head_status, bg=PANEL, fg=DIM,
                 font=("Consolas", 9, "bold"), anchor="w", padx=10,
                 pady=3).pack(fill="x", padx=8)
        gesture_bar = tk.Frame(parent, bg=PANEL, padx=10, pady=5)
        gesture_bar.pack(fill="x", padx=8, pady=(0, 0))
        self._gesture_status = tk.StringVar(value="GESTURE: CHỜ CAMERA · TỰ ĐỘNG")
        tk.Label(gesture_bar, textvariable=self._gesture_status, bg=PANEL, fg=DIM,
                 font=("Consolas", 9, "bold"), anchor="w").pack(fill="x")
        emotion_bar = tk.Frame(parent, bg=PANEL, padx=10, pady=5)
        emotion_bar.pack(fill="x", padx=8, pady=(0, 0))
        self._emotion_status = tk.StringVar(value="EMOTION: TẮT · CHỈ DEBUG")
        tk.Label(emotion_bar, textvariable=self._emotion_status, bg=PANEL, fg=DIM,
                 font=("Consolas", 9, "bold"), anchor="w").pack(side="left", fill="x",
                                                               expand=True)
        self._emotion_button = tk.Button(
            emotion_bar, text="BẬT EMOTION", command=self._toggle_emotion,
            bg=BG, fg=TEXT, activebackground=BG, activeforeground=CYAN,
            bd=1, font=("Consolas", 8, "bold"))
        self._emotion_button.pack(side="right")
        if self.camera is None or not hasattr(self.camera, "emotion_status"):
            self._emotion_button.configure(state="disabled")
        initial_status = ("CAMERA ĐANG TẮT TRONG CẤU HÌNH"
                          if self.camera is None else "Đang chờ trạng thái camera…")
        self._camera_status = tk.StringVar(value=initial_status)
        tk.Label(parent, textvariable=self._camera_status, bg=PANEL, fg=CYAN,
                 anchor="w", justify="left", padx=10, pady=7,
                 font=("Consolas", 9, "bold")).pack(fill="x", padx=8, pady=(8, 4))
        preview_box = tk.Frame(parent, bg="#020609", height=260)
        preview_box.pack(fill="x", padx=8, pady=4)
        preview_box.pack_propagate(False)
        self._camera_preview = tk.Label(
            preview_box,
            text="Chưa có hình webcam\nKiểm tra trạng thái camera bên trên.",
            bg="#020609", fg=DIM, font=("Consolas", 10), justify="center")
        self._camera_preview.pack(fill="both", expand=True)
        tk.Label(parent,
                 text="Xem trước cục bộ · xanh lá: mặt · tay: cái cam, trỏ xanh, giữa lục, áp út tím, út vàng · không lưu ảnh",
                 bg=BG, fg=DIM, anchor="w", font=("Consolas", 8)).pack(
                     fill="x", padx=10, pady=(1, 4))
        self._camera_log = ScrolledText(
            parent, bg=BG, fg=TEXT, insertbackground=TEXT,
            selectbackground="#24506a", relief="flat", bd=0,
            wrap="word", font=("Consolas", 9), padx=9, pady=6,
            height=7, state="disabled")
        self._camera_log.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        for tag, color in (("DEBUG", DIM), ("INFO", TEXT), ("WARNING", YELLOW),
                           ("ERROR", RED), ("SUCCESS", GREEN)):
            self._camera_log.tag_configure(tag, foreground=color)
        self._texts["camera"] = self._camera_log

    def _toggle_emotion(self):
        if self.camera is None or not hasattr(self.camera, "emotion_status"):
            return
        try:
            enabled = self.camera.emotion_status()["enabled"]
            self.camera.set_emotion_enabled(not enabled)
            self._emotion_button.configure(
                text="TẮT EMOTION" if not enabled else "BẬT EMOTION")
        except Exception as exc:
            if self._emotion_status is not None:
                self._emotion_status.set(f"EMOTION: {type(exc).__name__}: {exc}")

    def _calibrate_proximity(self):
        if self.camera is None:
            return
        try:
            self.camera.calibrate_proximity()
            self._proximity_status.set(
                "VÙNG BÀN: ngồi đúng vị trí thường dùng khoảng 6–10 giây…")
        except Exception as exc:
            self._proximity_status.set(f"VÙNG BÀN: {type(exc).__name__}: {exc}")

    def _schedule_camera_refresh(self):
        if (self.win is None or not self.win.winfo_exists() or
                self._camera_poll_id is not None):
            return
        self._refresh_camera()

    def _refresh_camera(self):
        self._camera_poll_id = None
        if self.win is None or not self.win.winfo_exists() or self.camera is None:
            return
        try:
            if self.win.state() == "withdrawn":
                return
            snapshot = self.camera.diagnostics()
            getter = getattr(self.camera, "emotion_status", None)
            emotion = getter() if getter is not None else {
                "state": "disabled", "enabled": False, "error": None}
            emotion_state = {
                "disabled": "TẮT", "loading": "ĐANG NẠP MODEL",
                "waiting_camera": "CHỜ CAMERA", "ready": "ĐANG CHẠY",
                "paused": "CAMERA TẠM DỪNG", "unavailable": "LỖI",
                "stale": "TRỄ MẪU",
            }.get(emotion["state"], emotion["state"].upper())
            emotion_detail = f"EMOTION: {emotion_state} · CHỈ DEBUG"
            if emotion["error"]:
                emotion_detail += f" · {emotion['error'][:72]}"
            self._emotion_status.set(emotion_detail)
            self._emotion_button.configure(
                text="TẮT EMOTION" if emotion["enabled"] else "BẬT EMOTION")
            gesture_getter = getattr(self.camera, "gesture_status", None)
            if gesture_getter is not None:
                gesture = gesture_getter()
                gesture_state = {
                    "starting": "ĐANG NẠP MODEL", "waiting_camera": "CHỜ CAMERA",
                    "ready": "ĐANG NHẬN DIỆN", "paused": "CAMERA TẠM DỪNG",
                    "stale": "TRỄ MẪU", "unavailable": "LỖI", "stopped": "DỪNG",
                }.get(gesture["state"], gesture["state"].upper())
                detail = f"GESTURE: {gesture_state} · TỰ ĐỘNG"
                if gesture["state"] == "ready":
                    detail += f" · {gesture['label']}"
                    basic_pose = gesture.get("basic_pose", "unknown")
                    if basic_pose != "unknown":
                        detail += f" · pose: {basic_pose}"
                    if gesture["latency_ms"] is not None:
                        detail += f" · {gesture['latency_ms']} ms"
                    detail += f" · {gesture.get('inference_fps', 0):.1f} mẫu/s"
                if gesture["error"]:
                    detail += f" · {gesture['error'][:72]}"
                self._gesture_status.set(detail)
            status = snapshot["status"]
            proximity = status.get("proximity") or {}
            if self._proximity_status is not None:
                calibration = proximity.get("calibration", "missing")
                band = proximity.get("band", "unknown")
                visibility = proximity.get("visibility", "degraded")
                self._proximity_status.set(
                    f"VÙNG BÀN: {band.upper()} · {visibility} · "
                    f"hiệu chỉnh {calibration} · CHỈ DEBUG")
                self._proximity_button.configure(
                    state=("normal" if status.get("available") and
                           status.get("camera_role") == "workstation_facing"
                           else "disabled"))
            head = status.get("head_motion") or {}
            if self._head_status is not None:
                head_mode = ("XÁC NHẬN BẬT" if status.get("head_confirmation_enabled")
                             else "CHỈ DEBUG")
                self._head_status.set(
                    f"CỬ CHỈ ĐẦU: {head.get('state', 'unknown').upper()} "
                    f"· {head.get('label', 'unknown')} · {head_mode}")
            state = status.get("state", "unknown").upper()
            state_color = (GREEN if status["available"] else
                           RED if state in ("ERROR", "UNAVAILABLE", "STOPPED") else YELLOW)
            detection = {
                "detected": "MẪU DETECTOR CÓ MẶT · PRESENCE CÓ",
                "held": "MẪU DETECTOR KHÔNG THẤY MẶT · PRESENCE ĐANG GIỮ",
                "candidate": "MẪU DETECTOR CÓ MẶT · CHỜ THÊM MẪU",
                "not_detected": "MẪU DETECTOR KHÔNG THẤY MẶT · PRESENCE KHÔNG",
            }.get(status.get("presence_reason"), "KHÔNG XÁC ĐỊNH")
            detail = (f"CAMERA {state} · {detection}\n"
                      f"{status.get('camera_label', 'Webcam')} "
                      f"[{status.get('camera_role', 'unknown')}] "
                      f"· #{status.get('camera_index', 0)} · phòng {status['room_id']} "
                      f"· frame capture {status.get('frame_sequence', 0)} "
                      f"· {status.get('capture_fps', 0):.1f} FPS "
                      f"(mục tiêu {status.get('requested_fps', 0)})")
            if status.get("presence_sequence") is not None:
                detail += f" · mẫu detector {status['presence_sequence']}"
            if status.get("last_frame_at"):
                detail += f" · {status['last_frame_at']}"
            if status.get("presence_latency_ms") is not None:
                detail += f" · {status['presence_latency_ms']} ms"
            if status.get("presence_state") == "error":
                detail += " · DETECTOR LỖI"
            if snapshot.get("preview_mode") == "raw":
                detail += " · PREVIEW GỐC"
            elif snapshot.get("preview_mode") == "hand_skeleton":
                detail += " · KHUNG XƯƠNG TAY"
            face = status.get("face_auth") or {}
            if face.get("enabled"):
                detail += f" · Face: {face.get('suggestion', 'unknown')}"
                if face.get("suggestion") == "unknown":
                    quality = face.get("match_quality")
                    if quality in ("multiple_faces", "no_face", "low_quality"):
                        detail += f" ({quality})"
                if face.get("latency_ms") is not None:
                    detail += f" {face['latency_ms']} ms"
            if status.get("last_error"):
                detail += f"  ·  {status['last_error']}"
            self._camera_status.set(detail)
            if self._camera_preview is not None:
                self._camera_preview.configure(
                    fg=state_color if not status["available"] else TEXT)

            preview_at = snapshot.get("preview_at")
            preview = snapshot.get("preview_jpeg")
            if preview and preview_at != self._last_preview_at:
                if Image is None or ImageTk is None:
                    self._camera_preview.configure(
                        image="", text="Cần Pillow để hiển thị ảnh webcam trong panel.")
                else:
                    image = Image.open(io.BytesIO(preview))
                    image.thumbnail((640, 320))
                    self._camera_photo = ImageTk.PhotoImage(image)
                    self._camera_preview.configure(image=self._camera_photo, text="")
                self._last_preview_at = preview_at
            elif not preview and self._last_preview_at is not None:
                self._camera_preview.configure(image="", text="Chưa có hình webcam.")
                self._camera_photo = None
                self._last_preview_at = None
            self._camera_poll_id = self.win.after(50, self._refresh_camera)
        except (tk.TclError, OSError, ValueError) as exc:
            if self._camera_status is not None:
                self._camera_status.set(f"Không thể cập nhật preview: {exc}")
            if self.win is not None and self.win.winfo_exists():
                self._camera_poll_id = self.win.after(1000, self._refresh_camera)

    def toggle(self):
        self._ensure()
        if self.win.state() == "withdrawn":
            self.show()
        else:
            self.hide()

    def update_state(self, state):
        if self._status_var is not None and state:
            labels = {"idle": "SẴN SÀNG", "listening": "ĐANG NGHE",
                      "thinking": "ĐANG XỬ LÝ", "speaking": "ĐANG NÓI"}
            self._status_var.set("TRẠNG THÁI: " + labels.get(state, str(state).upper()))

    def append(self, event):
        self._event_count += 1
        if self._count_var is not None:
            self._count_var.set(f"{self._event_count} EVENT")
        if self._paused:
            self._pending.append(dict(event))
            if len(self._pending) > MAX_PENDING:
                del self._pending[:len(self._pending) - MAX_PENDING]
            return
        self._append_now(event)

    def _append_now(self, event):
        line = format_event(event)
        tag = str(event.get("level") or "INFO").upper()
        if tag not in ("DEBUG", "INFO", "WARNING", "ERROR", "SUCCESS"):
            tag = "INFO"
        for tab in event_tabs(event.get("category")):
            widget = self._texts.get(tab)
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.insert("end", line, tag)
            lines = int(widget.index("end-1c").split(".")[0])
            if lines > MAX_LINES:
                widget.delete("1.0", f"{lines - MAX_LINES + 1}.0")
            if self._auto_scroll is None or self._auto_scroll.get():
                widget.see("end")
            widget.configure(state="disabled")

    def toggle_pause(self):
        self._paused = not self._paused
        if self._pause_button is not None:
            self._pause_button.configure(text="TIẾP LOG" if self._paused else "DỪNG LOG")
        if not self._paused and self._pending:
            pending, self._pending = self._pending, []
            for event in pending:
                self._append_now(event)

    def clear(self):
        self._pending.clear()
        self._event_count = 0
        if self._count_var is not None:
            self._count_var.set("0 EVENT")
        for widget in self._texts.values():
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")
