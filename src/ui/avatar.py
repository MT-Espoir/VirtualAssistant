"""
Cửa sổ avatar (Tkinter) — hiện nhân vật bằng ẢNH, mỗi cảm xúc một khung hình.

Khung hình nằm ở `ui/image/frames/`, do `packaging/make_avatar_frames.py` cắt ra từ
ảnh gốc toàn thân trong `ui/image/`. Cửa sổ không tự cắt/canh gì cả: mọi tấm đã cùng
cỡ và khớp nhau từ lúc bake, nên đổi cảm xúc chỉ là đổi ảnh.
"""

import logging
import random
import tkinter as tk
from pathlib import Path

from ui.avatar_face import BLINK_FRAME, blink_frame, frame_spec

try:
    from PIL import Image, ImageTk
except ImportError:
    # Thiếu Pillow thì cửa sổ vẫn mở và vẫn báo được lý do, thay vì làm chết cả trợ lý
    # ngay từ lúc import.
    Image = ImageTk = None

try:
    from utils.config import config
    _DEF_SCALE = float(getattr(config, "AVATAR_SCALE", 0.7))
    _DEF_OPACITY = float(getattr(config, "AVATAR_OPACITY", 1.0))
except Exception:
    _DEF_SCALE, _DEF_OPACITY = 0.7, 1.0

# Màu "chìa khoá" cho vùng trong suốt (Windows -transparentcolor). Phải KHÁC mọi màu
# có trong khung hình để không đục thủng nhầm vào người nhân vật.
TRANSPARENT_KEY = "#ff00ff"
HINT_COLOR = "#4cc9f0"                     # cùng tông với panel HUD (`ui/hud.py`)

BLINK_MIN_MS, BLINK_MAX_MS = 3000, 5500   # khoảng ngẫu nhiên giữa 2 lần chớp mắt
BLINK_DURATION_MS = 150
EMOTION_HOLD_MS = 5000                     # giữ cảm xúc rồi tự về neutral

FRAMES_DIR = Path(__file__).resolve().parent / "image" / "frames"
FRAME_OVERSAMPLE = 2                       # khung hình bake ở 2x cỡ gốc cho nét
ALPHA_CUT = 128                            # ngưỡng ép alpha nhị phân, xem `_photo`
FALLBACK_SIZE = (305, 280)                 # cỡ cửa sổ khi chưa nạp được khung hình nào
MISSING_FRAMES_HINT = ("Thiếu khung hình avatar.\n"
                       "Chạy: python packaging/make_avatar_frames.py")

SCALE_MIN, SCALE_MAX = 0.4, 1.5
OPACITY_MIN, OPACITY_MAX = 0.25, 1.0

logger = logging.getLogger(__name__)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _load_frames():
    """{tên: ảnh RGBA} đọc từ `FRAMES_DIR`. Thiếu Pillow hoặc thiếu thư mục -> {}.

    Nạp một lần lúc dựng cửa sổ: thêm ảnh mới thì phải bake lại VÀ mở lại trợ lý.
    """
    if Image is None:
        logger.warning("Không có Pillow -> avatar không hiện được khung hình")
        return {}
    frames = {}
    for path in sorted(FRAMES_DIR.glob("*.png")):
        try:
            frames[path.stem] = Image.open(path).convert("RGBA")
        except OSError:
            logger.warning("Không đọc được khung hình %s", path.name, exc_info=True)
    if not frames:
        logger.warning("Không thấy khung hình nào trong %s", FRAMES_DIR)
    return frames


class AvatarWindow:
    def __init__(self, bus=None, title="Trợ lý AI", scale=None, opacity=None,
                 emotion_hold_ms=None, on_open_place=None, on_draft_decision=None,
                 on_open_mail=None):
        self.bus = bus
        # Panel dùng chung khung HUD (`ui/hud.py`), tạo LƯỜI ở lần dùng đầu: phiên nào
        # không dùng tới tính năng đó thì không phải trả chi phí dựng cửa sổ nào.
        self._panels = {}
        self.on_open_place = on_open_place
        self.on_draft_decision = on_draft_decision
        self.on_open_mail = on_open_mail
        self.state, self.emotion, self.message = "idle", "neutral", ""
        # Giữ cảm xúc bao lâu rồi tự về neutral. <=0 = KHÔNG tự reset (để Persona/tâm trạng
        # dẫn dắt khuôn mặt). None = dùng mặc định EMOTION_HOLD_MS.
        self.emotion_hold_ms = EMOTION_HOLD_MS if emotion_hold_ms is None else emotion_hold_ms
        self._blinking = False
        self._emotion_reset_id = None
        self._drag_origin = (0, 0)
        self._frames = _load_frames()
        # Ảnh đã thu về đúng cỡ đang hiển thị. Tk KHÔNG giữ tham chiếu ảnh nên phải tự
        # giữ, nếu không ảnh bị thu gom và canvas trống trơn.
        self._photos = {}
        self.base_w, self.base_h = self._base_size()
        self.scale = _clamp(_DEF_SCALE if scale is None else scale, SCALE_MIN, SCALE_MAX)
        self.opacity = _clamp(_DEF_OPACITY if opacity is None else opacity,
                              OPACITY_MIN, OPACITY_MAX)
        self.W, self.H = self._scaled_size()

        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=TRANSPARENT_KEY)
        self._place_top_right()
        self._setup_frameless()      # bỏ viền + nền trong suốt: chỉ hiện nhân vật
        self._apply_opacity()

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H,
                                highlightthickness=0, bg=TRANSPARENT_KEY)
        self.canvas.pack(fill="both", expand=True)
        self._bind_controls()
        self._render()
        if bus is not None:
            self.root.after(100, self._poll)
        self._schedule_blink()

    def _base_size(self):
        """Cỡ cửa sổ ở scale 1.0, suy từ chính khung hình đã bake."""
        frame = next(iter(self._frames.values()), None)
        if frame is None:
            return FALLBACK_SIZE
        return (frame.width // FRAME_OVERSAMPLE, frame.height // FRAME_OVERSAMPLE)

    def _scaled_size(self):
        return int(self.base_w * self.scale), int(self.base_h * self.scale)

    # ------------------------- kích thước / độ mờ ------------------------- #
    def set_scale(self, value):
        self.scale = _clamp(value, SCALE_MIN, SCALE_MAX)
        self.W, self.H = self._scaled_size()
        self._photos.clear()               # ảnh cũ sai cỡ, thu lại từ khung hình gốc
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
        """Chỉ hiện nhân vật: bỏ viền cửa sổ + nền trong suốt (Windows). Nền tảng
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
        """Sau emotion_hold_ms kể từ cảm xúc gần nhất, đưa mặt về neutral.
        emotion_hold_ms <= 0 -> KHÔNG tự reset (Persona/tâm trạng dẫn dắt)."""
        if self._emotion_reset_id is not None:
            self.root.after_cancel(self._emotion_reset_id)
            self._emotion_reset_id = None
        if self.emotion_hold_ms and self.emotion_hold_ms > 0 and self.emotion != "neutral":
            self._emotion_reset_id = self.root.after(self.emotion_hold_ms, self._reset_emotion)

    def _reset_emotion(self):
        self._emotion_reset_id = None
        self.emotion = "neutral"
        self._render()

    def _panel(self, key, title, on_pick, close_value=None):
        """Lấy (hoặc dựng lười) một HudPanel theo khoá. Mọi panel dùng CHUNG khung HUD."""
        if self._panels.get(key) is None:
            from ui.hud import HudPanel
            self._panels[key] = HudPanel(self.root, title=title, on_pick=on_pick,
                                         close_value=close_value)
        return self._panels[key]

    # cập nhật trực tiếp (dùng ở demo/test tay)
    def _show_places(self, payload):
        """Mở/cập nhật panel kết quả địa điểm. Tạo lười — không hỏi địa điểm thì không tốn gì.

        Panel là tầng KIỂM CHỨNG BẰNG MẮT cho các thuộc tính không đo được (yên tĩnh,
        nhiều cây, phong cách cổ).
        """
        try:
            from ui.panels import places_blocks
            panel = self._panel("places", "CHỖ TÌM ĐƯỢC", self.on_open_place)
            panel.show(places_blocks(payload.get("rows"), payload.get("need")))
        except Exception:
            # Panel hỏng KHÔNG được làm chết avatar hay vòng lặp trợ lý.
            import logging
            logging.getLogger(__name__).warning("Không mở được panel địa điểm", exc_info=True)

    def _show_draft(self, draft):
        """Mở/cập nhật panel nháp email; dict rỗng = đóng.

        Panel hỏng KHÔNG được nuốt mất việc xác nhận: người dùng vẫn nói được 'có'/'không'
        vì đường xác nhận bằng giọng nằm ở agent, không nằm ở đây.
        """
        try:
            from ui.panels import pending_blocks, pending_title
            # Đóng panel = KHÔNG gửi. Im lặng đóng rồi vẫn gửi là cái bẫy tệ nhất.
            panel = self._panel("draft", "NHÁP EMAIL", self.on_draft_decision,
                                close_value="no")
            panel.title = pending_title(draft)   # panel dùng chung cho mọi hành động chờ duyệt
            panel.show(pending_blocks(draft))
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Không mở được panel nháp", exc_info=True)

    def _show_mail(self, mail):
        """Mở/cập nhật panel THƯ ĐẾN; dict rỗng = đóng.

        Không truyền `on_pick` thật và không có `close_value`: panel này chỉ để ĐỌC, đóng
        nó không kích hoạt hành động nào. Xem `ui/panels.py::mail_blocks`.
        """
        try:
            from ui.panels import mail_blocks
            panel = self._panel("mail", "THƯ ĐẾN", self.on_open_mail)
            panel.title = "THƯ ĐẾN"       # dùng CHUNG panel với danh sách -> phải đặt lại mỗi lần
            panel.show(mail_blocks(mail))
        except Exception:
            # Panel hỏng KHÔNG được làm chết avatar hay vòng lặp trợ lý.
            import logging
            logging.getLogger(__name__).warning("Không mở được panel thư", exc_info=True)

    def _show_mail_list(self, payload):
        """Mở/cập nhật panel DANH SÁCH thư; danh sách rỗng = đóng.

        Dùng CHUNG panel "mail" với `_show_mail`: bấm một thẻ thì chi tiết thư thay chỗ
        danh sách, thay vì mở thêm một cửa sổ nữa đè lên nhân vật.
        """
        try:
            from ui.panels import mail_list_blocks
            panel = self._panel("mail", "THƯ TÌM ĐƯỢC", self.on_open_mail)
            panel.title = "THƯ TÌM ĐƯỢC"
            panel.show(mail_list_blocks(payload.get("rows"), payload.get("q")))
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Không mở được panel danh sách thư",
                                                exc_info=True)

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
            if getattr(ev, "places", None) is not None:
                self._show_places(ev.places)
                continue
            if getattr(ev, "draft", None) is not None:
                self._show_draft(ev.draft)
                continue
            if getattr(ev, "mail", None) is not None:
                self._show_mail(ev.mail)
                continue
            if getattr(ev, "mails", None) is not None:
                self._show_mail_list(ev.mails)
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

    # ------------------------- chớp mắt ------------------------- #
    def _schedule_blink(self):
        """Hẹn lần chớp mắt kế tiếp. Chưa có ảnh chớp mắt thì không hẹn gì cả."""
        if BLINK_FRAME not in self._frames:
            return
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
        name = frame_spec(self.state, self.emotion)["frame"]
        if self._blinking:
            # Chỉ vài tư thế chớp được, và chỉ khi ảnh chớp đã có mặt.
            blink = blink_frame(name)
            if blink in self._frames:
                name = blink

        c = self.canvas
        c.delete("all")
        c.configure(bg=TRANSPARENT_KEY)     # nền trong suốt: chỉ nhân vật hiện ra

        photo = self._photo(name)
        if photo is None:
            c.create_text(self.W // 2, self.H // 2, text=MISSING_FRAMES_HINT,
                          fill=HINT_COLOR, justify="center", width=self.W - 20)
            return
        c.create_image(self.W // 2, self.H // 2, image=photo)

    def _photo(self, name):
        """Khung hình `name` đã thu về đúng cỡ cửa sổ hiện tại; không có -> None.

        Thu bằng Pillow chứ không phải `canvas.scale` như hồi vẽ tay: đây là ảnh bitmap,
        `canvas.scale` chỉ kéo giãn toạ độ của hình vẽ chứ không đụng tới ảnh.

        Thu xong phải ÉP LẠI alpha về nhị phân: khung hình bake ra đã nhị phân, nhưng
        phép thu làm mềm mép trở lại, mà `-transparentcolor` không có alpha nửa vời —
        mép mềm sẽ trộn với màu chìa khoá và hiện thành quầng hồng quanh nhân vật.
        """
        photo = self._photos.get(name)
        if photo is not None:
            return photo
        frame = self._frames.get(name)
        if frame is None:
            return None
        small = frame.resize((self.W, self.H), Image.LANCZOS)
        small.putalpha(small.getchannel("A").point(
            lambda v: 255 if v >= ALPHA_CUT else 0))
        photo = ImageTk.PhotoImage(small)
        self._photos[name] = photo
        return photo

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
