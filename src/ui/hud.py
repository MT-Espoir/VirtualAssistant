"""
Khung HUD dùng chung cho MỌI panel của trợ lý — kiểu dáng chuẩn của dự án.

Đây là file Tk duy nhất của phần panel. Mỗi tính năng KHÔNG dựng cửa sổ riêng nữa mà
chỉ mô tả nội dung bằng một danh sách KHỐI (xem `ui/panels.py`), rồi `HudPanel.show`
vẽ ra. Nhờ vậy thêm tính năng là thêm một hàm thuần, không phải thêm một file UI.

VỐN TỪ VỰNG KHỐI — cố ý nhỏ, đủ cho mọi panel đang có:

    ("header", "chuỗi")                     tiêu đề một mục
    ("field", "nhãn", "giá trị")            một dòng nhãn: giá trị
    ("body", "đoạn văn dài")                văn bản nhiều dòng, tự xuống dòng
    ("card", {...}, khoá_bấm)               thẻ có viền, bấm được
    ("buttons", [("nhãn", khoá, kiểu)])     hàng nút

Thẻ `card` nhận dict {title, meta[], lines[], photos[]}; trường nào rỗng thì không vẽ.

HAI CANVAS, và đó là điều kiện để cuộn đúng:

    canvas ngoài  vẽ KHUNG — đứng yên, không bao giờ cuộn
    canvas trong  vẽ NỘI DUNG — cuộn được, và tự CẮT phần tràn ra ngoài kích thước nó

Gộp làm một canvas thì `yview_scroll` kéo trôi cả khung viền, và nội dung vẽ tiếp ở
ngoài khung vì canvas không cắt theo hình vẽ, chỉ cắt theo widget.

TRONG SUỐT: `-transparentcolor` của Windows là NHỊ PHÂN — pixel hoặc đục hẳn hoặc đặc
hẳn, không có alpha. Nên nền khung phải TÔ ĐẶC, còn độ mờ lấy từ `-alpha` cấp cửa sổ
(alpha thật, trộn màu thật). Từng dùng `stipple` cho nền: nó chỉ là lưới rây 75% pixel
đen + 25% lỗ thủng, nhìn ổn trên nền tối nhưng chữ chìm hẳn khi sau lưng là trang sáng.
Phần NGOÀI khung vẫn để màu chroma-key nên panel giữ đúng hình vát góc, không thành
hình chữ nhật.
"""

import tkinter as tk

# Màu chroma-key: vùng nào tô màu này sẽ bị đục thủng hoàn toàn. Phải KHÁC mọi màu dùng
# để vẽ, nếu không nét vẽ cũng bị đục theo.
TRANSPARENT_KEY = "#010101"

# Bảng màu XANH BIỂN, cùng tông với dòng báo lỗi của avatar
# (`ui/avatar.py::HINT_COLOR`) — panel và avatar là một hệ thống, không phải hai cửa sổ
# của hai ứng dụng khác nhau.
HUD_COLOR = "#4cc9f0"         # nét chính: viền, tiêu đề, nút chính
HUD_DIM = "#2c6f8c"           # nét phụ: nhãn, viền thẻ, nút phụ
HUD_TEXT = "#cbe9f7"          # chữ thường
HUD_QUOTE = "#a8d7b4"         # TRÍCH DẪN cố ý LỆCH tông: mắt phải phân biệt được ngay
HUD_BG = "#0b0b0e"            # nền khung, TÔ ĐẶC (xem ghi chú TRONG SUỐT ở đầu file)
HUD_ALPHA = 0.90              # độ mờ cả cửa sổ; càng thấp càng thấy nền sau, chữ càng nhạt

FONT = ("Consolas", 9)
FONT_BOLD = ("Consolas", 9, "bold")
FONT_TITLE = ("Consolas", 10, "bold")
FONT_SMALL = ("Consolas", 8)

PAD = 18                      # lề từ mép cửa sổ tới khung viền
TOP_CUT = 34                  # độ vát góc trên phải
BOT_CUT = 22                  # độ vát góc dưới phải
INNER = 14                    # lề từ khung viền vào nội dung
CARD_GAP = 8
PHOTO_BOX = (88, 66)
MAX_CARDS = 8
WHEEL_STEP = 40               # số pixel cuộn mỗi nấc lăn chuột


class HudPanel:
    """Một cửa sổ HUD. Nhận `master` từ AvatarWindow — KHÔNG tự tạo `Tk()` thứ hai.

    `on_pick(value)` được gọi khi người dùng bấm vào một thẻ hoặc một nút; `value` là
    khoá do khối nội dung đặt ra, nên panel không cần biết gì về ý nghĩa của nó.
    """

    def __init__(self, master, title="HUD", on_pick=None, size=(430, 560),
                 close_value=None, alpha=HUD_ALPHA):
        self.master = master
        self.title = title
        self.on_pick = on_pick
        # Khoá được chọn khi người dùng TỰ đóng panel (ESC hoặc nút đóng của cửa sổ).
        # Panel xác nhận PHẢI đặt nó thành lựa chọn an toàn: đóng cửa sổ rồi hệ thống vẫn
        # gửi thư là cái bẫy tệ nhất mà một panel xác nhận có thể có.
        self.close_value = close_value
        self.alpha = alpha
        self.size = size
        self.win = None
        self.canvas = None         # canvas NGOÀI: khung, đứng yên
        self.inner = None          # canvas TRONG: nội dung, cuộn được
        self._photo_refs = []      # Tk không giữ tham chiếu ảnh -> phải tự giữ
        self._blocks = []
        self._drag = (0, 0)
        self._content_h = 0        # chiều cao thật của nội dung, để vẽ vạch cuộn
        # Chiều cao khung nhìn do `_redraw` TÍNH RA. Không hỏi `winfo_height()` vì lúc
        # `_redraw` chạy, canvas trong vừa được tạo và Tk chưa bố trí xong nên nó trả 1
        # -> panel ngắn cũng bị coi là dài hơn khung và vẽ thừa vạch cuộn.
        self._view_h = 0

    # ------------------------- vòng đời cửa sổ ------------------------- #
    def _ensure(self):
        if self.win is not None and self.win.winfo_exists():
            return
        self.win = tk.Toplevel(self.master)
        self.win.title(self.title)
        self.win.geometry("%dx%d" % self.size)
        self.win.configure(bg=TRANSPARENT_KEY)
        try:
            self.win.overrideredirect(True)
            self.win.wm_attributes("-topmost", True)
            self.win.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
            self.win.wm_attributes("-alpha", self.alpha)
        except tk.TclError:
            # Nền tảng không hỗ trợ đục thủng / alpha -> giữ cửa sổ thường, vẫn dùng được.
            pass

        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT_KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        # Canvas nội dung: đặt vào trong khung ở `_redraw`. Nền cùng màu khung nên chỗ
        # tiếp giáp không thấy đường nối.
        self.inner = tk.Canvas(self.canvas, bg=HUD_BG, highlightthickness=0)

        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        # Kéo cửa sổ CHỈ từ canvas ngoài (viền + dải tiêu đề) — canvas trong để dành cho
        # bấm thẻ/nút, nếu không thì mỗi cú bấm thẻ đều có nguy cơ kéo lệch cửa sổ.
        self.canvas.bind("<ButtonPress-1>", self._start_move)
        self.canvas.bind("<B1-Motion>", self._do_move)
        for widget in (self.canvas, self.inner):
            widget.bind("<MouseWheel>", self._on_wheel)
        self.win.bind("<Escape>", lambda _e: self._closed_by_user())
        self.win.protocol("WM_DELETE_WINDOW", self._closed_by_user)

    def hide(self):
        """Ẩn panel, KHÔNG báo gì cho tầng trên (dùng khi hệ thống chủ động dẹp panel)."""
        if self.win is not None and self.win.winfo_exists():
            self.win.withdraw()

    def _closed_by_user(self):
        """Người dùng tự đóng -> ẩn, và báo lựa chọn an toàn nếu panel có khai báo."""
        self.hide()
        if self.close_value is not None:
            self._picked(self.close_value)

    def show(self, blocks):
        """Vẽ lại panel với danh sách khối mới. Danh sách rỗng -> ẩn đi."""
        if not blocks:
            self.hide()
            return
        self._ensure()
        self._blocks = list(blocks)
        self.win.deiconify()
        self.win.lift()
        self._redraw()

    # ------------------------- kéo thả / cuộn ------------------------- #
    def _start_move(self, event):
        self._drag = (event.x_root - self.win.winfo_x(),
                      event.y_root - self.win.winfo_y())

    def _do_move(self, event):
        self.win.geometry("+%d+%d" % (event.x_root - self._drag[0],
                                      event.y_root - self._drag[1]))

    def _on_wheel(self, event):
        """Lăn chuột cuộn canvas TRONG. Nội dung ngắn hơn khung thì không cuộn gì."""
        if self.inner is None or self._content_h <= self._view_h:
            return
        self.inner.yview_scroll(-1 if event.delta > 0 else 1, "units")
        self._scroll_mark()

    # ------------------------- vẽ ------------------------- #
    def _redraw(self):
        if self.canvas is None or not self.canvas.winfo_exists():
            return
        self.canvas.delete("all")
        self._photo_refs = []
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 120 or h < 120:
            return

        self._frame(w, h)

        # Vùng nội dung là hình chữ nhật NẰM TRỌN trong đa giác vát góc: né cả góc vát
        # trên phải lẫn dưới phải, nếu không canvas trong (vốn là hình chữ nhật) sẽ tô
        # đè lên đúng hai chỗ vát và phá mất hình dáng khung.
        cx = PAD + INNER
        cy = PAD + TOP_CUT + 4
        cw = max(40, w - 2 * (PAD + INNER))
        ch = max(40, h - cy - PAD - BOT_CUT - 4)
        self.canvas.create_window(cx, cy, window=self.inner, anchor="nw",
                                  width=cw, height=ch)
        self._view_h = ch

        self.inner.delete("all")
        self.inner.configure(scrollregion=(0, 0, cw, 0))
        self._content_h = self._content(cw, 0)
        self.inner.configure(scrollregion=(0, 0, cw, self._content_h),
                             yscrollincrement=WHEEL_STEP)
        self.inner.yview_moveto(0)
        self._scroll_mark()

    def _scroll_mark(self):
        """Vạch chỉ vị trí cuộn ở mép phải. Nội dung vừa khung -> không vẽ gì.

        Canvas trong CẮT phần tràn nên không còn dấu hiệu nào cho thấy phía dưới còn
        nội dung; thiếu vạch này thì người dùng tưởng danh sách chỉ có ngần đó.
        """
        self.canvas.delete("scrollmark")
        if self.inner is None or not self.inner.winfo_exists():
            return
        view_h = self._view_h
        if view_h <= 0 or self._content_h <= view_h:
            return
        w = self.canvas.winfo_width()
        top = PAD + TOP_CUT + 4
        x = w - PAD - 5
        self.canvas.create_line(x, top, x, top + view_h, fill=HUD_DIM, width=2,
                                tags="scrollmark")
        first, last = self.inner.yview()
        self.canvas.create_line(x, top + view_h * first, x, top + view_h * last,
                                fill=HUD_COLOR, width=3, tags="scrollmark")

    def _frame(self, w, h):
        """Khung viền vát góc + nền đặc + các vạch trang trí."""
        x0, y0 = PAD, PAD
        x1, y1 = w - PAD, h - PAD

        body = [
            x0, y0,
            x1 - TOP_CUT, y0,
            x1, y0 + TOP_CUT,
            x1, y1 - BOT_CUT,
            x1 - BOT_CUT, y1,
            x0, y1,
        ]
        self.canvas.create_polygon(body, fill=HUD_BG, outline="")

        # Viền chính, cố ý ĐỨT QUÃNG ở cạnh trên và cạnh dưới cho đúng kiểu HUD.
        gap = min(120, max(40, int(w * 0.22)))
        self.canvas.create_line(x0, y0 + 22, x0, y0, x0 + gap, y0,
                                fill=HUD_COLOR, width=2)
        self.canvas.create_line(x0 + gap + 40, y0, x1 - TOP_CUT, y0,
                                x1, y0 + TOP_CUT, x1, y1 - BOT_CUT,
                                x1 - BOT_CUT, y1, x0 + 70, y1,
                                fill=HUD_COLOR, width=2)
        self.canvas.create_line(x0 + 40, y1, x0, y1, x0, y1 - 46,
                                fill=HUD_COLOR, width=2)

        # Vạch dày + hàng chấm: chi tiết trang trí, không mang thông tin.
        self.canvas.create_line(x0 + 8, y0 - 6, x0 + gap - 12, y0 - 6,
                                fill=HUD_COLOR, width=3)
        self.canvas.create_line(x0 + 60, y1 + 6, x0 + 130, y1 + 6, fill=HUD_COLOR, width=4)
        for i in range(5):
            top = y0 + 52 + i * 13
            self.canvas.create_rectangle(x0 - 9, top, x0 - 4, top + 5,
                                         fill=HUD_COLOR, outline="")

        self.canvas.create_text(x0 + 12, y0 + 9, text="[ %s ]" % self.title.upper(),
                                anchor="w", fill=HUD_COLOR, font=FONT_BOLD)
        self.canvas.create_text(x1 - 10, y1 + 6, text="ESC: ĐÓNG",
                                anchor="e", fill=HUD_DIM, font=FONT_SMALL)

    def _content(self, cw, y):
        """Vẽ lần lượt các khối lên canvas TRONG, trả về chiều cao nội dung."""
        x = 8
        wrap = max(80, cw - 16)
        for block in self._blocks:
            kind = block[0]
            if kind == "header":
                y = self._header(x, y, wrap, block[1])
            elif kind == "field":
                y = self._field(x, y, wrap, block[1], block[2])
            elif kind == "body":
                y = self._body(x, y, wrap, block[1])
            elif kind == "card":
                y = self._card(x, y, wrap, block[1], block[2] if len(block) > 2 else None)
            elif kind == "buttons":
                y = self._buttons(x, y, cw, block[1])
        return y + 8

    def _text(self, x, y, wrap, text, fill=HUD_TEXT, font=FONT):
        item = self.inner.create_text(x, y, text=text, anchor="nw", fill=fill,
                                      font=font, width=wrap)
        return self.inner.bbox(item)[3]

    def _header(self, x, y, wrap, text):
        y = self._text(x, y + 4, wrap, text, fill=HUD_COLOR, font=FONT_TITLE)
        self.inner.create_line(x, y + 3, x + wrap, y + 3, fill=HUD_DIM, width=1)
        return y + 10

    def _field(self, x, y, wrap, label, value):
        self.inner.create_text(x, y, text=label + ":", anchor="nw", fill=HUD_DIM,
                               font=FONT_SMALL)
        return self._text(x + 62, y, wrap - 62, value, fill=HUD_COLOR, font=FONT_BOLD) + 4

    def _body(self, x, y, wrap, text):
        return self._text(x, y + 2, wrap, text) + 6

    def _card(self, x, y, wrap, data, value):
        """Một thẻ bấm được. Vẽ nội dung trước, rồi mới vẽ viền ôm đúng chiều cao thật."""
        tag = "card%d" % id(data)
        top = y + 2
        inner_x = x + 8
        inner_wrap = wrap - 16
        cy = top + 7

        title = (data.get("title") or "").strip()
        if title:
            cy = self._text(inner_x, cy, inner_wrap, title, fill=HUD_COLOR, font=FONT_BOLD)
        if data.get("meta"):
            cy = self._text(inner_x, cy + 2, inner_wrap, " · ".join(data["meta"]),
                            fill=HUD_DIM, font=FONT_SMALL)
        cy = self._photos(inner_x, cy, data.get("photos") or [])
        for line in data.get("lines") or []:
            quoted = line.startswith("“")
            cy = self._text(inner_x, cy + 2, inner_wrap, line,
                            fill=HUD_QUOTE if quoted else HUD_TEXT, font=FONT)
        bottom = cy + 7

        self.inner.create_rectangle(x, top, x + wrap, bottom, outline=HUD_DIM, width=1)
        if value is not None:
            # Vùng bấm PHỦ cả thẻ nhưng trong suốt, để không che chữ đã vẽ.
            hit = self.inner.create_rectangle(x, top, x + wrap, bottom,
                                              outline="", fill="", tags=tag)
            self.inner.tag_bind(tag, "<Button-1>", lambda _e, v=value: self._picked(v))
            self.inner.tag_raise(hit)
        return bottom + CARD_GAP

    def _photos(self, x, y, photos):
        if not photos:
            return y
        left = x
        tallest = 0
        for src in photos[:3]:
            image = self._load_photo(src)
            if image is None:
                continue
            self._photo_refs.append(image)
            self.inner.create_image(left, y + 4, image=image, anchor="nw")
            left += image.width() + 5
            tallest = max(tallest, image.height())
        return y + tallest + 6 if tallest else y

    def _load_photo(self, src):
        """Đường dẫn/bytes -> PhotoImage đã thu nhỏ. Lỗi -> None, KHÔNG làm vỡ panel."""
        try:
            import io

            from PIL import Image, ImageTk
            image = Image.open(io.BytesIO(src) if isinstance(src, bytes) else src)
            image.thumbnail(PHOTO_BOX)
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def _buttons(self, x, y, cw, items):
        """Hàng nút xếp từ PHẢI sang trái — nút chính (kiểu 'go') nằm ngoài cùng phải."""
        right = cw - 8
        top = y + 6
        height = 26
        for label, value, kind in reversed(items):
            colour = HUD_COLOR if kind == "go" else HUD_DIM
            width = max(64, 11 * len(label) + 22)
            tag = "btn%s" % value
            self.inner.create_rectangle(right - width, top, right, top + height,
                                        outline=colour, width=1, tags=tag)
            self.inner.create_text(right - width / 2, top + height / 2, text=label,
                                   fill=colour, font=FONT_BOLD, tags=tag)
            self.inner.tag_bind(tag, "<Button-1>", lambda _e, v=value: self._picked(v))
            right -= width + 8
        return top + height + 6

    def _picked(self, value):
        if self.on_pick is not None:
            self.on_pick(value)
