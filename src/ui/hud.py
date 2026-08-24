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

Vẽ TRÊN CANVAS chứ không dùng widget: nền HUD là màu chroma-key bị đục thủng, nên một
widget đặc đè lên sẽ phá mất phần trong suốt vốn là điểm nhận dạng của khung này.
"""

import tkinter as tk

# Màu chroma-key: vùng nào tô màu này sẽ bị đục thủng hoàn toàn. Phải KHÁC mọi màu dùng
# để vẽ, nếu không nét vẽ cũng bị đục theo.
TRANSPARENT_KEY = "#010101"

HUD_COLOR = "#ff9d00"
HUD_DIM = "#995e00"
HUD_TEXT = "#ffd9a0"
HUD_QUOTE = "#c9d7a8"
HUD_FILL = "#000000"          # nền ám đen, phủ một phần qua stipple

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


def _wrap_width(width):
    """Bề rộng tối đa cho chữ bên trong khung."""
    return max(80, width - 2 * PAD - 2 * INNER)


class HudPanel:
    """Một cửa sổ HUD. Nhận `master` từ AvatarWindow — KHÔNG tự tạo `Tk()` thứ hai.

    `on_pick(value)` được gọi khi người dùng bấm vào một thẻ hoặc một nút; `value` là
    khoá do khối nội dung đặt ra, nên panel không cần biết gì về ý nghĩa của nó.
    """

    def __init__(self, master, title="HUD", on_pick=None, size=(430, 560),
                 close_value=None):
        self.master = master
        self.title = title
        self.on_pick = on_pick
        # Khoá được chọn khi người dùng TỰ đóng panel (ESC hoặc nút đóng của cửa sổ).
        # Panel xác nhận PHẢI đặt nó thành lựa chọn an toàn: đóng cửa sổ rồi hệ thống vẫn
        # gửi thư là cái bẫy tệ nhất mà một panel xác nhận có thể có.
        self.close_value = close_value
        self.size = size
        self.win = None
        self.canvas = None
        self._photo_refs = []      # Tk không giữ tham chiếu ảnh -> phải tự giữ
        self._blocks = []
        self._drag = (0, 0)

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
        except tk.TclError:
            # Nền tảng không hỗ trợ đục thủng -> giữ cửa sổ thường, panel vẫn dùng được.
            pass

        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT_KEY, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._start_move)
        self.canvas.bind("<B1-Motion>", self._do_move)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
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
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

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
        y = self._content(w, PAD + INNER + 18)
        # Cuộn được khi nội dung dài hơn cửa sổ; ngắn hơn thì giữ nguyên, không nhảy.
        self.canvas.configure(scrollregion=(0, 0, w, max(h, y + PAD)))

    def _frame(self, w, h):
        """Khung viền vát góc + nền ám đen + các vạch trang trí."""
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
        self.canvas.create_polygon(body, fill=HUD_FILL, outline="", stipple="gray75")

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

    def _content(self, w, y):
        """Vẽ lần lượt các khối, trả về toạ độ y sau khối cuối."""
        x = PAD + INNER
        wrap = _wrap_width(w)
        for block in self._blocks:
            kind = block[0]
            if kind == "header":
                y = self._header(x, y, wrap, block[1])
            elif kind == "field":
                y = self._field(x, y, wrap, block[1], block[2])
            elif kind == "body":
                y = self._body(x, y, wrap, block[1])
            elif kind == "card":
                y = self._card(x, y, w, wrap, block[1], block[2] if len(block) > 2 else None)
            elif kind == "buttons":
                y = self._buttons(x, y, w, block[1])
        return y

    def _text(self, x, y, wrap, text, fill=HUD_TEXT, font=FONT):
        item = self.canvas.create_text(x, y, text=text, anchor="nw", fill=fill,
                                       font=font, width=wrap)
        return self.canvas.bbox(item)[3]

    def _header(self, x, y, wrap, text):
        y = self._text(x, y + 4, wrap, text, fill=HUD_COLOR, font=FONT_TITLE)
        self.canvas.create_line(x, y + 3, x + wrap, y + 3, fill=HUD_DIM, width=1)
        return y + 10

    def _field(self, x, y, wrap, label, value):
        self.canvas.create_text(x, y, text=label + ":", anchor="nw", fill=HUD_DIM,
                                font=FONT_SMALL)
        return self._text(x + 62, y, wrap - 62, value, fill=HUD_COLOR, font=FONT_BOLD) + 4

    def _body(self, x, y, wrap, text):
        return self._text(x, y + 2, wrap, text) + 6

    def _card(self, x, y, w, wrap, data, value):
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

        # KHÔNG `tag_lower`: nền khung là polygon stipple vẽ trước, đẩy viền thẻ xuống
        # dưới nó thì viền bị lưới stipple ăn mất và thẻ trông như chỉ có gạch ngang.
        # Viền chỉ là nét mảnh không tô nền nên nằm trên cùng cũng không che chữ.
        self.canvas.create_rectangle(x, top, x + wrap, bottom, outline=HUD_DIM, width=1)
        if value is not None:
            # Vùng bấm PHỦ cả thẻ nhưng trong suốt, để không che chữ đã vẽ.
            hit = self.canvas.create_rectangle(x, top, x + wrap, bottom,
                                               outline="", fill="", tags=tag)
            self.canvas.tag_bind(tag, "<Button-1>",
                                 lambda _e, v=value: self._picked(v))
            self.canvas.tag_raise(hit)
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
            self.canvas.create_image(left, y + 4, image=image, anchor="nw")
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

    def _buttons(self, x, y, w, items):
        """Hàng nút xếp từ PHẢI sang trái — nút chính (kiểu 'go') nằm ngoài cùng phải."""
        right = w - PAD - INNER
        top = y + 6
        height = 26
        for label, value, kind in reversed(items):
            colour = HUD_COLOR if kind == "go" else HUD_DIM
            width = max(64, 11 * len(label) + 22)
            tag = "btn%s" % value
            self.canvas.create_rectangle(right - width, top, right, top + height,
                                         outline=colour, width=1, tags=tag)
            self.canvas.create_text(right - width / 2, top + height / 2, text=label,
                                    fill=colour, font=FONT_BOLD, tags=tag)
            self.canvas.tag_bind(tag, "<Button-1>",
                                 lambda _e, v=value: self._picked(v))
            right -= width + 8
        return top + height + 6

    def _picked(self, value):
        if self.on_pick is not None:
            self.on_pick(value)
