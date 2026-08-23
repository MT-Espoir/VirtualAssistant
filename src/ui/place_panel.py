"""
Panel kết quả địa điểm (Tkinter) — L3-4 của `docs/research_lane_spec.md` §12.

VÌ SAO CẦN PANEL, chứ không chỉ đọc bằng giọng: thuộc tính thẩm mỹ ("nhiều cây xanh",
"phong cách cổ") **không có ground truth** và không có hàm nào kiểm chứng được — khác hẳn
khoảng cách (haversine) hay tên (khớp token). Đó là chỗ bịa đặt sẽ sống.

Lời giải không phải là làm cho trợ lý tự tin hơn, mà là **trưng bằng chứng ra để mắt người
dùng làm tầng kiểm chứng**. Một khẳng định không kiểm chứng được biến thành một trình bày
kiểm chứng được. Rẻ hơn nhiều so với xây hệ thống hiệu chỉnh confidence, và đúng tinh thần
I3 / F1.5 §9.

Chia tầng: `card_text()` là hàm THUẦN (test không cần Tk), `PlacesPanel` chỉ vẽ. Giữ đúng
ranh giới của repo — phần core không import Tkinter, phần UI không chứa luật.
"""

import tkinter as tk

from utils.units import say_distance

BG = "#1b1b1f"
CARD_BG = "#26262c"
FG = "#f2f2f5"
DIM = "#a0a0aa"
ACCENT = "#4cc9f0"
QUOTE_FG = "#c9d7a8"

CARD_PAD = 10
MAX_CARDS = 8
PHOTO_BOX = (96, 72)


def card_text(row, need=None):
    """Một ứng viên -> {title, meta, evidence, photos}. Hàm THUẦN.

    QUY TẮC PHÁT NGÔN (spec §12, I-L3-3): chỉ hiện trường CÓ DỮ LIỆU THẬT. Không có thì
    im lặng, KHÔNG hiện ô trống và KHÔNG đoán.

    Số nguồn hiện ra dưới dạng MỘT CON SỐ, không phải tính từ: "3 nguồn nhắc tới" chứ
    không phải "rất nổi tiếng". Người đọc phải tự đánh giá được sức nặng của bằng chứng.
    """
    title = (row.get("name") or "").strip() or "(không rõ tên)"

    meta = []
    far = say_distance(row.get("distance_km"))
    if far:
        meta.append(far)
    if row.get("rating") is not None:
        # Điểm LUÔN kèm số lượt: 4,8 với 3 lượt khác hẳn 4,8 với 646 lượt (F1.5 §7).
        reviews = row.get("reviews")
        meta.append(f"★ {row['rating']}" + (f" ({reviews} lượt)" if reviews else ""))
    opening = (row.get("opening") or {}).get("state")
    if opening == "open_24h":
        meta.append("mở cả ngày")
    elif opening == "closing_soon":
        meta.append("sắp đóng cửa")
    elif opening == "closed":
        meta.append("đang đóng cửa")
    elif opening == "open":
        meta.append("đang mở cửa")

    evidence = []
    n = row.get("sources")
    if n:
        about = f" khi nói về {need}" if need else ""
        evidence.append(f"{n} nguồn nhắc tới{about}")
    if row.get("quote"):
        # Trích dẫn kèm TÊN NGUỒN. Câu vô danh thì người dùng không lần lại được, mà cả
        # tấm thẻ này tồn tại để họ TỰ kiểm chứng chứ không phải để tin lời trợ lý (§12).
        where = row.get("quote_source")
        evidence.append(f"“{row['quote']}”" + (f" — {where}" if where else ""))
    if not row.get("resolved", True):
        # Nói thẳng là chưa tra được trên bản đồ, thay vì để người dùng tưởng đã xác minh.
        evidence.append("(chưa tra được trên bản đồ)")

    # Ưu tiên BYTES đã tải sẵn; URL chỉ là dự phòng (panel không được gọi mạng).
    return {"title": title, "meta": meta, "evidence": evidence,
            "photos": list(row.get("photo_data") or row.get("photos") or [])}


def panel_title(need, rows):
    """Tiêu đề panel. Nêu SỐ chỗ, không nêu nhận định về chất lượng."""
    what = " ".join(str(need or "").split())
    n = len(rows or [])
    if not n:
        return f"Không có chỗ nào cho: {what}" if what else "Không có kết quả"
    return f"{n} chỗ được nhiều nguồn nhắc tới" + (f" — {what}" if what else "")


class PlacesPanel:
    """Cửa sổ phụ hiện các ứng viên kèm bằng chứng. Chạy trên MAIN THREAD (Tk).

    Không tự tạo `Tk()` — nhận `master` từ `AvatarWindow` để hai cửa sổ dùng chung một
    mainloop. Tạo `Tk()` thứ hai trong cùng tiến trình là nguồn lỗi khó lần.
    """

    def __init__(self, master, on_open=None):
        self.master = master
        self.on_open = on_open
        self.win = None
        self._photo_refs = []          # Tk không giữ tham chiếu ảnh -> phải tự giữ

    # ---------- vòng đời ----------
    def _ensure(self):
        if self.win is not None and self.win.winfo_exists():
            return
        self.win = tk.Toplevel(self.master)
        self.win.title("Chỗ tìm được")
        self.win.configure(bg=BG)
        self.win.geometry("380x520")
        self.win.protocol("WM_DELETE_WINDOW", self.hide)

    def hide(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.withdraw()

    def show(self, rows, need=None):
        """Vẽ lại toàn bộ panel với danh sách mới. Danh sách rỗng -> ẩn đi."""
        if not rows:
            self.hide()
            return
        self._ensure()
        self._photo_refs = []
        for child in self.win.winfo_children():
            child.destroy()

        tk.Label(self.win, text=panel_title(need, rows), bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold"), wraplength=350, justify="left",
                 anchor="w").pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 4))

        for i, row in enumerate(rows[:MAX_CARDS], 1):
            self._card(i, card_text(row, need))

        self.win.deiconify()
        self.win.lift()

    # ---------- một thẻ ----------
    def _card(self, index, data):
        frame = tk.Frame(self.win, bg=CARD_BG, bd=0, highlightthickness=0)
        frame.pack(fill="x", padx=CARD_PAD, pady=4)

        head = tk.Frame(frame, bg=CARD_BG)
        head.pack(fill="x", padx=8, pady=(8, 2))
        tk.Label(head, text=f"{index}. {data['title']}", bg=CARD_BG, fg=FG,
                 font=("Segoe UI", 10, "bold"), anchor="w", justify="left",
                 wraplength=300).pack(side="left")

        if data["meta"]:
            tk.Label(frame, text=" · ".join(data["meta"]), bg=CARD_BG, fg=DIM,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=8)

        self._photos(frame, data["photos"])

        for line in data["evidence"]:
            quoted = line.startswith("“")
            tk.Label(frame, text=line, bg=CARD_BG, fg=QUOTE_FG if quoted else ACCENT,
                     font=("Segoe UI", 9, "italic" if quoted else "normal"),
                     anchor="w", justify="left", wraplength=330).pack(fill="x", padx=8)

        tk.Frame(frame, bg=CARD_BG, height=6).pack()
        for widget in (frame,) + tuple(frame.winfo_children()):
            widget.bind("<Button-1>", lambda _e, i=index: self._clicked(i))

    def _photos(self, parent, photos):
        """Dải ảnh — bằng chứng MẠNH NHẤT cho thuộc tính thị giác.

        Ảnh lấy từ chính bài viết đã tải ở bước thu thập, không phải từ nguồn bản đồ: đo
        được độ phủ **100%** trên 3 truy vấn / 2 thành phố (spec §2.8), miễn phí và không
        tốn thêm lời gọi nào. Bytes đã được tải sẵn ở tầng research — panel KHÔNG gọi mạng.

        Ảnh blog là ảnh MARKETING (quán tự chụp hoặc bài PR), yếu hơn ảnh khách chụp. Vì
        vậy nó chỉ để người dùng NHÌN mà tự đánh giá, không phải căn cứ để hệ thống khẳng
        định điều gì.
        """
        if not photos:
            return
        strip = tk.Frame(parent, bg=CARD_BG)
        strip.pack(fill="x", padx=8, pady=4)
        for src in photos[:3]:
            image = self._load_photo(src)
            if image is None:
                continue
            self._photo_refs.append(image)
            tk.Label(strip, image=image, bg=CARD_BG).pack(side="left", padx=(0, 4))

    def _load_photo(self, src):
        """Đường dẫn/bytes -> PhotoImage đã thu nhỏ. Lỗi -> None, KHÔNG làm vỡ panel."""
        try:
            from PIL import Image, ImageTk
            import io
            image = Image.open(io.BytesIO(src) if isinstance(src, bytes) else src)
            image.thumbnail(PHOTO_BOX)
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def _clicked(self, index):
        if self.on_open is not None:
            self.on_open(index)
