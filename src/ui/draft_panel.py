"""
Panel xem trước bản nháp email (Tkinter), trước khi gửi.

VÌ SAO PANEL, CHỨ KHÔNG ĐỌC BẰNG GIỌNG: gửi email là hành động KHÔNG rút lại được, mà
thân thư do LLM viết ra thì lỗi nằm ở CHI TIẾT — sai tên, sai ngày, sai giọng văn với
sếp. Nghe TTS đọc một lá thư mất cả phút và không soát được; liếc mắt thì thấy ngay.
Đây đúng cùng lý lẽ với panel địa điểm (`ui/place_panel.py`): biến một khẳng định
không kiểm chứng được bằng tai thành một trình bày kiểm chứng được bằng mắt.

Giọng nói vẫn nói MỘT câu ngắn ("gửi email tới X, bạn xem trên màn hình giúp tôi") —
hai kênh bổ sung nhau chứ không lặp lại nhau.

Chia tầng như place_panel: `draft_header()` THUẦN (test không cần Tk), `DraftPanel`
chỉ vẽ. Nhận dạng "đây là email" nằm ở `actions/email_draft.py`, không nằm ở đây.
"""

import tkinter as tk

BG = "#1b1b1f"
CARD_BG = "#26262c"
FG = "#f2f2f5"
DIM = "#a0a0aa"
ACCENT = "#4cc9f0"
SEND_BG = "#2e7d32"
CANCEL_BG = "#4a4a52"

PAD = 10
BODY_HEIGHT = 14          # số dòng thân thư hiện ra trước khi phải cuộn


def draft_header(draft):
    """Bản nháp -> danh sách (nhãn, giá trị) cho phần đầu thư. Hàm THUẦN.

    Chỉ trả trường CÓ dữ liệu thật — thiếu người nhận thì KHÔNG hiện ô 'Tới:' trống,
    vì ô trống trông như đã điền mà rỗng, dễ khiến người dùng bấm Gửi mà không để ý.
    Cùng quy tắc phát ngôn với thẻ địa điểm (place_panel §12).
    """
    draft = draft or {}
    rows = []
    if (draft.get("to") or "").strip():
        rows.append(("Tới", draft["to"].strip()))
    if (draft.get("subject") or "").strip():
        rows.append(("Tiêu đề", draft["subject"].strip()))
    return rows


class DraftPanel:
    """Cửa sổ phụ hiện bản nháp + hai nút Gửi / Huỷ. Chạy trên MAIN THREAD (Tk).

    Không tự tạo `Tk()` — nhận `master` từ `AvatarWindow` để dùng chung một mainloop
    (tạo `Tk()` thứ hai trong cùng tiến trình là nguồn lỗi khó lần).
    """

    def __init__(self, master, on_decide=None):
        self.master = master
        self.on_decide = on_decide      # callable('yes'|'no')
        self.win = None
        self.body = None

    # ---------- vòng đời ----------
    def _ensure(self):
        if self.win is not None and self.win.winfo_exists():
            return
        self.win = tk.Toplevel(self.master)
        self.win.title("Nháp email")
        self.win.configure(bg=BG)
        self.win.geometry("460x520")
        # Đóng cửa sổ bằng dấu X = KHÔNG gửi. Im lặng đóng rồi vẫn gửi là cái bẫy tệ nhất
        # mà một panel xác nhận có thể có.
        self.win.protocol("WM_DELETE_WINDOW", lambda: self._decide("no"))

    def hide(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.withdraw()

    def show(self, draft):
        """Vẽ lại panel với bản nháp mới. Nháp rỗng/None -> ẩn đi."""
        if not draft:
            self.hide()
            return
        self._ensure()
        for child in self.win.winfo_children():
            child.destroy()

        tk.Label(self.win, text="Xem lại trước khi gửi", bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold"), anchor="w").pack(
                     fill="x", padx=PAD, pady=(PAD, 6))

        head = tk.Frame(self.win, bg=CARD_BG)
        head.pack(fill="x", padx=PAD)
        for label, value in draft_header(draft):
            row = tk.Frame(head, bg=CARD_BG)
            row.pack(fill="x", padx=8, pady=3)
            tk.Label(row, text=f"{label}:", bg=CARD_BG, fg=DIM, width=8,
                     font=("Segoe UI", 9), anchor="w").pack(side="left")
            tk.Label(row, text=value, bg=CARD_BG, fg=ACCENT, font=("Segoe UI", 9, "bold"),
                     anchor="w", justify="left", wraplength=350).pack(side="left")

        self._body_box(draft.get("body") or "")
        self._buttons()

        self.win.deiconify()
        self.win.lift()
        try:
            self.win.focus_force()
        except tk.TclError:
            pass

    # ---------- thân thư ----------
    def _body_box(self, text):
        """Thân thư trong ô CHỌN được (không phải Label): người dùng hay muốn copy lại,
        và thư dài phải cuộn được thay vì tràn khỏi cửa sổ."""
        wrap = tk.Frame(self.win, bg=BG)
        wrap.pack(fill="both", expand=True, padx=PAD, pady=8)

        scroll = tk.Scrollbar(wrap)
        scroll.pack(side="right", fill="y")
        self.body = tk.Text(wrap, height=BODY_HEIGHT, bg=CARD_BG, fg=FG,
                            font=("Segoe UI", 10), wrap="word", relief="flat",
                            padx=8, pady=8, yscrollcommand=scroll.set,
                            insertbackground=FG)
        self.body.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.body.yview)
        self.body.insert("1.0", text)
        # Chỉ ĐỌC: panel này để soát, không phải trình soạn thảo. Cho sửa ở đây thì phần
        # sửa sẽ KHÔNG đi vào lệnh gửi (lệnh đã chốt tham số lúc hoãn) -> hỏng im lặng.
        self.body.config(state="disabled")

    # ---------- nút ----------
    def _buttons(self):
        bar = tk.Frame(self.win, bg=BG)
        bar.pack(fill="x", padx=PAD, pady=(0, PAD))
        tk.Button(bar, text="Gửi", bg=SEND_BG, fg=FG, font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=18, pady=6, cursor="hand2",
                  command=lambda: self._decide("yes")).pack(side="right", padx=(6, 0))
        tk.Button(bar, text="Huỷ", bg=CANCEL_BG, fg=FG, font=("Segoe UI", 10),
                  relief="flat", padx=18, pady=6, cursor="hand2",
                  command=lambda: self._decide("no")).pack(side="right")
        tk.Label(bar, text="hoặc nói \"có\" / \"không\"", bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(side="left")

    def _decide(self, decision):
        self.hide()
        if self.on_decide is not None:
            self.on_decide(decision)
