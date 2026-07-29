"""
Cửa sổ avatar (Tkinter) — khuôn mặt robot kiểu màn hình thiết bị: khung bezel
trắng bo tròn, màn hình đen cố định bên trong, mắt/miệng vẽ nét xanh dương
(neutral/happy/sad/cry/confused). Không dùng file ảnh — vẽ thuần bằng Canvas.

Cửa sổ KHÔNG viền + nền TRONG SUỐT: chỉ khuôn mặt nổi trên desktop (kéo chuột trái
để di chuyển; Esc hoặc chuột phải để đóng). Cảm xúc tự trở về neutral sau vài giây.

Chạy trên MAIN thread (Tk yêu cầu). Nhận cập nhật từ AssistantBus qua .after() poll.
Chạy thử độc lập:  python ui/avatar.py   (chế độ demo, không cần Ollama)
"""

import random
import tkinter as tk

from ui.avatar_face import face_spec

try:
    from utils.config import config
    _DEF_SCALE = float(getattr(config, "AVATAR_SCALE", 0.7))
    _DEF_OPACITY = float(getattr(config, "AVATAR_OPACITY", 1.0))
except Exception:
    _DEF_SCALE, _DEF_OPACITY = 0.7, 1.0

BLUE = "#4cc9f0"
BEZEL_COLOR = "#f5f5f5"
RING_COLOR = "#4a4a4a"
SCREEN_COLOR = "#050505"
# Màu "chìa khoá" cho vùng trong suốt (Windows -transparentcolor). Phải KHÁC mọi màu
# dùng vẽ khuôn mặt để không bị đục thủng nhầm.
TRANSPARENT_KEY = "#ff00ff"

BLINK_MIN_MS, BLINK_MAX_MS = 3000, 5500   # khoảng ngẫu nhiên giữa 2 lần chớp mắt
BLINK_DURATION_MS = 150
EMOTION_HOLD_MS = 5000                     # giữ cảm xúc rồi tự về neutral

BASE_W, BASE_H = 360, 340                  # kích thước gốc (scale=1.0), đủ ôm khuôn mặt
SCALE_MIN, SCALE_MAX = 0.4, 1.5
OPACITY_MIN, OPACITY_MAX = 0.25, 1.0


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


# Toạ độ khung/màn hình (vẽ ở kích thước gốc 360x340, rồi scale toàn bộ canvas)
BEZEL = (40, 30, 320, 310)
RING = (52, 42, 308, 298)
SCREEN = (68, 58, 292, 282)
SCREEN_CX = (SCREEN[0] + SCREEN[2]) // 2      # 180
SCREEN_CY = (SCREEN[1] + SCREEN[3]) // 2      # 170
EYE_DX, EYE_Y = 45, SCREEN_CY - 22
MOUTH_Y = SCREEN_CY + 48


def _round_rect(canvas, x1, y1, x2, y2, radius=10, **kwargs):
    """Vẽ hình chữ nhật bo góc bằng polygon làm mượt (Canvas không có sẵn)."""
    r = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1, x1 + r, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class AvatarWindow:
    def __init__(self, bus=None, title="Trợ lý AI", scale=None, opacity=None):
        self.bus = bus
        self.state, self.emotion, self.message = "idle", "neutral", ""
        self._blinking = False
        self._emotion_reset_id = None
        self._drag_origin = (0, 0)
        self.scale = _clamp(_DEF_SCALE if scale is None else scale, SCALE_MIN, SCALE_MAX)
        self.opacity = _clamp(_DEF_OPACITY if opacity is None else opacity,
                              OPACITY_MIN, OPACITY_MAX)
        self.W, self.H = self._scaled_size()

        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=TRANSPARENT_KEY)
        self._place_top_right()
        self._setup_frameless()      # bỏ viền + nền trong suốt: chỉ hiện khuôn mặt
        self._apply_opacity()

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H,
                                highlightthickness=0, bg=TRANSPARENT_KEY)
        self.canvas.pack(fill="both", expand=True)
        self._bind_controls()
        self._render()
        if bus is not None:
            self.root.after(100, self._poll)
        self._schedule_blink()

    def _scaled_size(self):
        return int(BASE_W * self.scale), int(BASE_H * self.scale)

    # ------------------------- kích thước / độ mờ ------------------------- #
    def set_scale(self, value):
        self.scale = _clamp(value, SCALE_MIN, SCALE_MAX)
        self.W, self.H = self._scaled_size()
        self.canvas.config(width=self.W, height=self.H)
        x, y = self.root.winfo_x(), self.root.winfo_y()
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self._render()

    def nudge_scale(self, delta):
        self.set_scale(self.scale + delta)

    def set_opacity(self, value):
        self.opacity = _clamp(value, OPACITY_MIN, OPACITY_MAX)
        self._apply_opacity()

    def nudge_opacity(self, delta):
        self.set_opacity(self.opacity + delta)

    def _apply_opacity(self):
        try:
            self.root.wm_attributes("-alpha", self.opacity)
        except tk.TclError:
            pass

    def _apply_ui(self, ui):
        """Áp lệnh giao diện từ AssistantBus (đổi kích thước / độ mờ)."""
        if "scale" in ui:
            self.set_scale(ui["scale"])
        if "scale_delta" in ui:
            self.nudge_scale(ui["scale_delta"])
        if "opacity" in ui:
            self.set_opacity(ui["opacity"])
        if "opacity_delta" in ui:
            self.nudge_opacity(ui["opacity_delta"])

    # ------------------------- cửa sổ không viền / trong suốt ------------------------- #
    def _place_top_right(self):
        """Đặt cửa sổ ở góc trên phải màn hình."""
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        self.root.geometry(f"{self.W}x{self.H}+{max(0, sw - self.W - 40)}+40")

    def _setup_frameless(self):
        """Chỉ hiện khuôn mặt: bỏ viền cửa sổ + nền trong suốt (Windows). Nền tảng
        không hỗ trợ thì giữ cửa sổ thường (không làm vỡ app)."""
        try:
            self.root.overrideredirect(True)
            self.root.wm_attributes("-topmost", True)
            self.root.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            pass

    def _bind_controls(self):
        """Không có thanh tiêu đề: kéo chuột trái để di chuyển, Esc/chuột phải để đóng."""
        self.canvas.bind("<Button-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<Button-3>", lambda e: self.root.destroy())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    def _start_drag(self, e):
        self._drag_origin = (e.x, e.y)

    def _on_drag(self, e):
        x = self.root.winfo_x() + e.x - self._drag_origin[0]
        y = self.root.winfo_y() + e.y - self._drag_origin[1]
        self.root.geometry(f"+{x}+{y}")

    # ------------------------- cảm xúc tự về neutral ------------------------- #
    def _schedule_emotion_reset(self):
        """Sau EMOTION_HOLD_MS kể từ cảm xúc gần nhất, đưa mặt về neutral."""
        if self._emotion_reset_id is not None:
            self.root.after_cancel(self._emotion_reset_id)
            self._emotion_reset_id = None
        if self.emotion != "neutral":
            self._emotion_reset_id = self.root.after(EMOTION_HOLD_MS, self._reset_emotion)

    def _reset_emotion(self):
        self._emotion_reset_id = None
        self.emotion = "neutral"
        self._render()

    # cập nhật trực tiếp (dùng ở demo/test tay)
    def set(self, state=None, emotion=None, text=None):
        if state:
            self.state = state
        if emotion:
            self.emotion = emotion
            self._schedule_emotion_reset()
        if text is not None:
            self.message = text
        self._render()

    def _poll(self):
        emotion_changed = False
        for ev in self.bus.drain():
            if getattr(ev, "ui", None):        # lệnh giao diện (đổi size/độ mờ)
                self._apply_ui(ev.ui)
                continue
            if ev.state:
                self.state = ev.state
            if ev.emotion:
                self.emotion = ev.emotion
                emotion_changed = True
            if ev.text is not None:
                self.message = ev.text
        if emotion_changed:
            self._schedule_emotion_reset()
        self._render()
        self.root.after(100, self._poll)

    # ------------------------- chớp mắt (chỉ áp dụng cho pose "neutral") ------------------------- #
    def _schedule_blink(self):
        self.root.after(random.randint(BLINK_MIN_MS, BLINK_MAX_MS), self._start_blink)

    def _start_blink(self):
        self._blinking = True
        self._render()
        self.root.after(BLINK_DURATION_MS, self._end_blink)

    def _end_blink(self):
        self._blinking = False
        self._render()
        self._schedule_blink()

    # ------------------------- vẽ ------------------------- #
    def _render(self):
        spec = face_spec(self.state, self.emotion)
        c = self.canvas
        c.delete("all")
        c.configure(bg=TRANSPARENT_KEY)     # nền trong suốt: chỉ khuôn mặt hiện ra

        _round_rect(c, *BEZEL, radius=55, fill=BEZEL_COLOR, outline="")
        _round_rect(c, *RING, radius=45, fill=RING_COLOR, outline="")
        _round_rect(c, *SCREEN, radius=35, fill=SCREEN_COLOR, outline="")
        c.create_arc(BEZEL[2] - 55, BEZEL[1] - 5, BEZEL[2] + 15, BEZEL[1] + 55,
                     start=200, extent=70, style="arc", width=6, outline="#ffffff")

        pose = spec["pose"]
        blinking = self._blinking and pose == "neutral"
        self._draw_pose(pose, blinking)
        # (Bỏ nhãn trạng thái + câu nói: chỉ hiển thị khuôn mặt.)

        # Vẽ ở toạ độ gốc rồi thu/phóng toàn bộ theo scale (đơn giản, không phải sửa
        # từng toạ độ). Nét/độ dày không đổi -> chấp nhận với mức scale vừa phải.
        if self.scale != 1.0:
            c.scale("all", 0, 0, self.scale, self.scale)

    def _draw_pose(self, pose, blinking):
        cx, cy = SCREEN_CX, SCREEN_CY
        ex_l, ex_r, ey = cx - EYE_DX, cx + EYE_DX, EYE_Y

        if pose == "neutral":
            self._eyes_neutral(ex_l, ex_r, ey, blinking)
            self._mouth_flat(cx, MOUTH_Y)
        elif pose == "happy":
            self._eyes_arc(ex_l, ex_r, ey, up=True)      # mắt chữ U ngược lên: ∩
            self._mouth_d_down(cx, MOUTH_Y)              # miệng chữ D lật xuống
        elif pose == "sad":
            self._eyes_arc(ex_l, ex_r, ey, up=False)     # mắt chữ U: ∪
            self._mouth_frown(cx, MOUTH_Y)               # miệng vòm úp: ∩
        elif pose == "cry":
            self._eyes_cry(ex_l, ex_r, ey)               # mắt nhắm nghiền + dòng lệ
            self._mouth_wail(cx, MOUTH_Y)
        elif pose == "confused":
            self._eyes_confused(ex_l, ex_r, ey)
            # không vẽ miệng — giống mẫu (chỉ mắt + dấu hỏi + chấm)

    # --- neutral: 2 khối vuông đặc, chớp mắt = dẹt lại --- #
    def _eyes_neutral(self, ex_l, ex_r, ey, blinking):
        half = 12
        for ex in (ex_l, ex_r):
            h = 3 if blinking else half
            self.canvas.create_rectangle(ex - half, ey - h, ex + half, ey + h,
                                         fill=BLUE, outline="")

    def _mouth_flat(self, cx, my):
        _round_rect(self.canvas, cx - 42, my - 6, cx + 42, my + 6, radius=6,
                   fill=BLUE, outline="")

    # --- happy/sad: mắt cung (∩ = happy, ∪ = sad) --- #
    def _eyes_arc(self, ex_l, ex_r, ey, up):
        r = 24
        start = 0 if up else 180
        for ex in (ex_l, ex_r):
            self.canvas.create_arc(ex - r, ey - r, ex + r, ey + r,
                                   start=start, extent=180, style="arc",
                                   width=7, outline=BLUE)

    def _mouth_d_down(self, cx, my):
        """Chữ D lật xuống: cạnh phẳng ở trên, bụng cong xuống dưới (đặc)."""
        self.canvas.create_arc(cx - 36, my - 26, cx + 36, my + 26,
                               start=180, extent=180, style="chord",
                               fill=BLUE, outline="")

    def _mouth_frown(self, cx, my):
        self.canvas.create_arc(cx - 40, my - 8, cx + 40, my + 40,
                               start=0, extent=180, style="arc", width=7, outline=BLUE)

    # --- cry: mắt nhắm nghiền (thanh ngang) + dòng lệ rơi --- #
    def _eyes_cry(self, ex_l, ex_r, ey):
        bar_half, thick = 22, 4
        for ex, out in ((ex_l, -1), (ex_r, 1)):
            self.canvas.create_rectangle(ex - bar_half, ey - thick, ex + bar_half, ey + thick,
                                         fill=BLUE, outline="")
            # nét xiên nối xuống từ mép ngoài
            tip_x = ex + out * bar_half
            self.canvas.create_line(tip_x, ey, tip_x + out * 6, ey + 16,
                                    fill=BLUE, width=5, capstyle="round")
            # giọt lệ rơi thành chuỗi ô nhỏ, thưa dần
            for i, (dy, size) in enumerate(((24, 5), (38, 4), (52, 3))):
                dx = tip_x + out * (7 + i * 2)
                self.canvas.create_rectangle(dx - size, ey + dy - size, dx + size, ey + dy + size,
                                             fill=BLUE, outline="")

    def _mouth_wail(self, cx, my):
        """Miệng méo khi khóc: vòm úp dày, hai chân buông xuống."""
        self.canvas.create_arc(cx - 44, my - 10, cx + 44, my + 34,
                               start=0, extent=180, style="arc", width=9, outline=BLUE)

    # --- confused: 1 mắt đặc + 1 mắt vòng + dấu hỏi + chấm nhỏ --- #
    def _eyes_confused(self, ex_l, ex_r, ey):
        self.canvas.create_oval(ex_l - 17, ey - 17, ex_l + 17, ey + 17, fill=BLUE, outline="")
        self.canvas.create_oval(ex_r - 14, ey - 14, ex_r + 14, ey + 14, outline=BLUE, width=5)
        self.canvas.create_text(ex_r + 30, ey - 30, text="?", fill=BLUE,
                                font=("Segoe UI", 30, "bold"))
        self.canvas.create_oval((ex_l + ex_r) // 2 - 6, ey + 42, (ex_l + ex_r) // 2 + 6,
                                ey + 54, fill=BLUE, outline="")

    def run(self):
        self.root.mainloop()


def demo():
    """Xem thử: tự đổi trạng thái/cảm xúc mỗi 1.8s (không cần Ollama/mic)."""
    win = AvatarWindow(title="Trợ lý AI — Demo")
    seq = [("idle", "neutral"), ("listening", "happy"), ("thinking", "neutral"),
           ("speaking", "happy"), ("idle", "sad"), ("speaking", "cry"), ("idle", "neutral")]
    i = {"k": 0}

    def tick():
        s, e = seq[i["k"] % len(seq)]
        win.set(state=s, emotion=e, text=f"Demo: {s} / {e}")
        i["k"] += 1
        win.root.after(1800, tick)

    win.root.after(400, tick)
    win.run()


if __name__ == "__main__":
    demo()
