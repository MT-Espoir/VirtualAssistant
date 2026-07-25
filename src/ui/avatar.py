"""
Cửa sổ avatar (Tkinter) — vẽ khuôn mặt cảm xúc bằng Canvas (không cần file ảnh).

Chạy trên MAIN thread (Tk yêu cầu). Nhận cập nhật từ AssistantBus qua .after() poll.
Chạy thử độc lập:  python ui/avatar.py   (chế độ demo, không cần Ollama)
"""

import tkinter as tk

from ui.avatar_face import face_spec


class AvatarWindow:
    W, H = 360, 440

    def __init__(self, bus=None, title="Trợ lý AI"):
        self.bus = bus
        self.state, self.emotion, self.message = "idle", "neutral", ""
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry(f"{self.W}x{self.H}")
        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._render()
        if bus is not None:
            self.root.after(100, self._poll)

    # cập nhật trực tiếp (dùng ở demo/test tay)
    def set(self, state=None, emotion=None, text=None):
        if state:
            self.state = state
        if emotion:
            self.emotion = emotion
        if text is not None:
            self.message = text
        self._render()

    def _poll(self):
        for ev in self.bus.drain():
            if ev.state:
                self.state = ev.state
            if ev.emotion:
                self.emotion = ev.emotion
            if ev.text is not None:
                self.message = ev.text
        self._render()
        self.root.after(100, self._poll)

    # ------------------------- vẽ ------------------------- #
    def _render(self):
        spec = face_spec(self.state, self.emotion)
        c = self.canvas
        c.delete("all")
        c.configure(bg=spec["bg"])
        cx, cy, r = self.W // 2, 175, 110
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#ffe0b2", outline="")
        self._draw_eyes(cx, cy, spec["eyes"])
        self._draw_mouth(cx, cy, spec["mouth"])
        c.create_text(cx, cy + r + 45, text=spec["label"], fill="#ffffff",
                      font=("Segoe UI", 16, "bold"))
        if self.message:
            c.create_text(cx, self.H - 45, text=self.message[:80], fill="#dddddd",
                          font=("Segoe UI", 10), width=self.W - 40)

    def _draw_eyes(self, cx, cy, style):
        ey, dx, er = cy - 30, 45, 14
        for x in (cx - dx, cx + dx):
            if style == "happy":
                self.canvas.create_arc(x - er, ey - er, x + er, ey + er,
                                       start=0, extent=180, style="arc", width=4, outline="#333")
            elif style == "think":
                self.canvas.create_oval(x - er, ey - er - 8, x + er, ey + er - 8,
                                        fill="#333", outline="")
            else:
                self.canvas.create_oval(x - er, ey - er, x + er, ey + er,
                                        fill="#333", outline="")

    def _draw_mouth(self, cx, cy, style):
        my, w = cy + 45, 60
        if style == "smile":
            self.canvas.create_arc(cx - w, my - 30, cx + w, my + 30,
                                   start=200, extent=140, style="arc", width=5, outline="#a33")
        elif style == "frown":
            self.canvas.create_arc(cx - w, my + 10, cx + w, my + 70,
                                   start=20, extent=140, style="arc", width=5, outline="#a33")
        elif style == "open":
            self.canvas.create_oval(cx - 25, my - 5, cx + 25, my + 35, fill="#7a2b2b", outline="")
        else:  # neutral
            self.canvas.create_line(cx - w + 10, my + 10, cx + w - 10, my + 10, width=5, fill="#a33")

    def run(self):
        self.root.mainloop()


def demo():
    """Xem thử: tự đổi trạng thái/cảm xúc mỗi 1.5s (không cần Ollama/mic)."""
    win = AvatarWindow(title="Trợ lý AI — Demo")
    seq = [("idle", "neutral"), ("listening", "neutral"), ("thinking", "neutral"),
           ("speaking", "happy"), ("idle", "happy"), ("speaking", "sad"), ("idle", "neutral")]
    i = {"k": 0}

    def tick():
        s, e = seq[i["k"] % len(seq)]
        win.set(state=s, emotion=e, text=f"Demo: {s} / {e}")
        i["k"] += 1
        win.root.after(1500, tick)

    win.root.after(400, tick)
    win.run()


if __name__ == "__main__":
    demo()
