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
    ("bar_chart", [{label,value,...}])       biểu đồ thanh ngang
    ("sparkline", [{label,value,...}])       xu hướng nhỏ theo ngày
    ("badge", "chuỗi", "info|warn")         nhãn trạng thái có chữ

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

from ui.scale import ContinuousScale

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
                 close_value=None, alpha=HUD_ALPHA, scale=1.0,
                 on_visibility=None):
        self.master = master
        self.title = title
        self.on_pick = on_pick
        self.on_visibility = on_visibility
        # Khoá được chọn khi người dùng TỰ đóng panel (ESC hoặc nút đóng của cửa sổ).
        # Panel xác nhận PHẢI đặt nó thành lựa chọn an toàn: đóng cửa sổ rồi hệ thống vẫn
        # gửi thư là cái bẫy tệ nhất mà một panel xác nhận có thể có.
        self.close_value = close_value
        self.alpha = alpha
        self.base_size = tuple(size)
        self._scale = ContinuousScale(scale)
        self.size = self._scaled_size()
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
        self._visible = False

    def _set_visible(self, visible):
        visible = bool(visible)
        if visible == self._visible:
            return
        self._visible = visible
        if self.on_visibility is not None:
            try:
                self.on_visibility(visible)
            except Exception:
                # Callback ngữ cảnh là phụ trợ; không được làm hỏng panel chính.
                pass

    @property
    def scale(self):
        return self._scale.value

    def _scaled_size(self):
        return tuple(max(1, round(value * self.scale)) for value in self.base_size)

    def _u(self, value):
        """Đổi đơn vị thiết kế sang pixel ở tỷ lệ hiện tại."""
        return max(1, round(value * self.scale)) if value > 0 else round(value * self.scale)

    def _font(self, spec):
        family, size, *style = spec
        return (family, max(6, round(size * self.scale)), *style)

    def set_scale(self, value):
        """Đặt tỷ lệ thực bất kỳ; giữ vị trí panel và vẽ lại nếu cửa sổ đã tồn tại."""
        before = self.scale
        self._scale.set(value)
        self.size = self._scaled_size()
        if self.scale == before or self.win is None or not self.win.winfo_exists():
            return self.scale
        x, y = self.win.winfo_x(), self.win.winfo_y()
        self.win.geometry(f"{self.size[0]}x{self.size[1]}+{x}+{y}")
        self.win.update_idletasks()
        self._redraw()
        return self.scale

    def nudge_scale(self, delta):
        try:
            return self.set_scale(self.scale + float(delta))
        except (TypeError, ValueError):
            return self.scale

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
        """Ẩn panel và cập nhật ngữ cảnh bề mặt cho bộ định tuyến lệnh."""
        if self.win is not None and self.win.winfo_exists():
            self.win.withdraw()
        self._set_visible(False)

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
        self._set_visible(True)
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
        pad, inner = self._u(PAD), self._u(INNER)
        cx = pad + inner
        cy = pad + self._u(TOP_CUT + 4)
        cw = max(self._u(40), w - 2 * (pad + inner))
        ch = max(self._u(40), h - cy - pad - self._u(BOT_CUT + 4))
        self.canvas.create_window(cx, cy, window=self.inner, anchor="nw",
                                  width=cw, height=ch)
        self._view_h = ch

        self.inner.delete("all")
        self.inner.configure(scrollregion=(0, 0, cw, 0))
        self._content_h = self._content(cw, 0)
        self.inner.configure(scrollregion=(0, 0, cw, self._content_h),
                             yscrollincrement=self._u(WHEEL_STEP))
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
        top = self._u(PAD + TOP_CUT + 4)
        x = w - self._u(PAD + 5)
        self.canvas.create_line(x, top, x, top + view_h, fill=HUD_DIM,
                                width=self._u(2),
                                tags="scrollmark")
        first, last = self.inner.yview()
        self.canvas.create_line(x, top + view_h * first, x, top + view_h * last,
                                fill=HUD_COLOR, width=self._u(3), tags="scrollmark")

    def _frame(self, w, h):
        """Khung viền vát góc + nền đặc + các vạch trang trí."""
        pad = self._u(PAD)
        top_cut, bot_cut = self._u(TOP_CUT), self._u(BOT_CUT)
        x0, y0 = pad, pad
        x1, y1 = w - pad, h - pad

        body = [
            x0, y0,
            x1 - top_cut, y0,
            x1, y0 + top_cut,
            x1, y1 - bot_cut,
            x1 - bot_cut, y1,
            x0, y1,
        ]
        self.canvas.create_polygon(body, fill=HUD_BG, outline="")

        # Viền chính, cố ý ĐỨT QUÃNG ở cạnh trên và cạnh dưới cho đúng kiểu HUD.
        gap = min(self._u(120), max(self._u(40), int(w * 0.22)))
        self.canvas.create_line(x0, y0 + self._u(22), x0, y0, x0 + gap, y0,
                                fill=HUD_COLOR, width=self._u(2))
        self.canvas.create_line(x0 + gap + self._u(40), y0, x1 - top_cut, y0,
                                x1, y0 + top_cut, x1, y1 - bot_cut,
                                x1 - bot_cut, y1, x0 + self._u(70), y1,
                                fill=HUD_COLOR, width=self._u(2))
        self.canvas.create_line(x0 + self._u(40), y1, x0, y1,
                                x0, y1 - self._u(46), fill=HUD_COLOR,
                                width=self._u(2))

        # Vạch dày + hàng chấm: chi tiết trang trí, không mang thông tin.
        self.canvas.create_line(x0 + self._u(8), y0 - self._u(6),
                                x0 + gap - self._u(12), y0 - self._u(6),
                                fill=HUD_COLOR, width=self._u(3))
        self.canvas.create_line(x0 + self._u(60), y1 + self._u(6),
                                x0 + self._u(130), y1 + self._u(6),
                                fill=HUD_COLOR, width=self._u(4))
        for i in range(5):
            top = y0 + self._u(52 + i * 13)
            self.canvas.create_rectangle(x0 - self._u(9), top,
                                         x0 - self._u(4), top + self._u(5),
                                         fill=HUD_COLOR, outline="")

        self.canvas.create_text(x0 + self._u(12), y0 + self._u(9),
                                text="[ %s ]" % self.title.upper(), anchor="w",
                                fill=HUD_COLOR, font=self._font(FONT_BOLD))
        self.canvas.create_text(x1 - self._u(10), y1 + self._u(6), text="ESC: ĐÓNG",
                                anchor="e", fill=HUD_DIM, font=self._font(FONT_SMALL))

    def _content(self, cw, y):
        """Vẽ lần lượt các khối lên canvas TRONG, trả về chiều cao nội dung."""
        x = self._u(8)
        wrap = max(self._u(80), cw - self._u(16))
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
            elif kind == "bar_chart":
                y = self._bar_chart(x, y, wrap, block[1])
            elif kind == "sparkline":
                y = self._sparkline(x, y, wrap, block[1])
            elif kind == "badge":
                y = self._badge(x, y, wrap, block[1],
                                block[2] if len(block) > 2 else "info")
            elif kind == "toggle":
                y = self._toggle(x, y, wrap, *block[1:])
        return y + self._u(8)

    def _toggle(self, x, y, wrap, label, enabled, value, detail):
        top = y
        button_w = self._u(56)
        bottom = self._text(x, y, wrap - button_w - self._u(12), label, font=FONT_BOLD)
        bottom = self._text(x, bottom + self._u(3), wrap - button_w - self._u(12), detail,
                            fill=HUD_DIM, font=FONT_SMALL)
        tag = "toggle%d" % id(value)
        bx = x + wrap - button_w
        color = HUD_COLOR if enabled else HUD_DIM
        self.inner.create_rectangle(bx, top, bx + button_w, top + self._u(25),
                                    fill=HUD_BG, outline=color, tags=tag)
        self.inner.create_text(bx + button_w // 2, top + self._u(12),
                               text="BẬT" if enabled else "TẮT", fill=color,
                               font=self._font(FONT_BOLD), tags=tag)
        self.inner.tag_bind(tag, "<Button-1>", lambda _e, v=value: self._picked(v))
        return max(bottom, top + self._u(25)) + self._u(12)

    def _text(self, x, y, wrap, text, fill=HUD_TEXT, font=FONT):
        item = self.inner.create_text(x, y, text=text, anchor="nw", fill=fill,
                                      font=self._font(font), width=wrap)
        return self.inner.bbox(item)[3]

    def _header(self, x, y, wrap, text):
        y = self._text(x, y + self._u(4), wrap, text, fill=HUD_COLOR, font=FONT_TITLE)
        self.inner.create_line(x, y + self._u(3), x + wrap, y + self._u(3),
                               fill=HUD_DIM, width=self._u(1))
        return y + self._u(10)

    def _field(self, x, y, wrap, label, value):
        self.inner.create_text(x, y, text=label + ":", anchor="nw", fill=HUD_DIM,
                               font=self._font(FONT_SMALL))
        offset = self._u(62)
        return self._text(x + offset, y, wrap - offset, value,
                          fill=HUD_COLOR, font=FONT_BOLD) + self._u(4)

    def _body(self, x, y, wrap, text):
        return self._text(x, y + self._u(2), wrap, text) + self._u(6)

    def _card(self, x, y, wrap, data, value):
        """Một thẻ bấm được. Vẽ nội dung trước, rồi mới vẽ viền ôm đúng chiều cao thật."""
        tag = "card%d" % id(data)
        top = y + self._u(2)
        inner_x = x + self._u(8)
        inner_wrap = wrap - self._u(16)
        cy = top + self._u(7)

        title = (data.get("title") or "").strip()
        if title:
            cy = self._text(inner_x, cy, inner_wrap, title, fill=HUD_COLOR, font=FONT_BOLD)
        if data.get("meta"):
            cy = self._text(inner_x, cy + self._u(2), inner_wrap,
                            " · ".join(data["meta"]),
                            fill=HUD_DIM, font=FONT_SMALL)
        cy = self._photos(inner_x, cy, data.get("photos") or [])
        for line in data.get("lines") or []:
            quoted = line.startswith("“")
            cy = self._text(inner_x, cy + self._u(2), inner_wrap, line,
                            fill=HUD_QUOTE if quoted else HUD_TEXT, font=FONT)
        bottom = cy + self._u(7)

        self.inner.create_rectangle(x, top, x + wrap, bottom, outline=HUD_DIM,
                                    width=self._u(1))
        if value is not None:
            # Vùng bấm PHỦ cả thẻ nhưng trong suốt, để không che chữ đã vẽ.
            hit = self.inner.create_rectangle(x, top, x + wrap, bottom,
                                              outline="", fill="", tags=tag)
            self.inner.tag_bind(tag, "<Button-1>", lambda _e, v=value: self._picked(v))
            self.inner.tag_raise(hit)
        return bottom + self._u(CARD_GAP)

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
            self.inner.create_image(left, y + self._u(4), image=image, anchor="nw")
            left += image.width() + self._u(5)
            tallest = max(tallest, image.height())
        return y + tallest + self._u(6) if tallest else y

    def _load_photo(self, src):
        """Đường dẫn/bytes -> PhotoImage đã thu nhỏ. Lỗi -> None, KHÔNG làm vỡ panel."""
        try:
            import io

            from PIL import Image, ImageTk
            image = Image.open(io.BytesIO(src) if isinstance(src, bytes) else src)
            image.thumbnail((self._u(PHOTO_BOX[0]), self._u(PHOTO_BOX[1])))
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def _buttons(self, x, y, cw, items):
        """Hàng nút xếp từ PHẢI sang trái — nút chính (kiểu 'go') nằm ngoài cùng phải."""
        right = cw - self._u(8)
        top = y + self._u(6)
        height = self._u(26)
        for index, (label, value, kind) in enumerate(reversed(items)):
            colour = HUD_COLOR if kind == "go" else HUD_DIM
            width = max(self._u(64), self._u(11 * len(label) + 22))
            # Action có thể là dict có khoảng trắng; Tk tag thì không. Tag chỉ cần duy
            # nhất trong lượt render, không cần mang chính payload nghiệp vụ.
            tag = f"btn{id(items)}_{index}"
            self.inner.create_rectangle(right - width, top, right, top + height,
                                        outline=colour, width=self._u(1), tags=tag)
            self.inner.create_text(right - width / 2, top + height / 2, text=label,
                                   fill=colour, font=self._font(FONT_BOLD), tags=tag)
            self.inner.tag_bind(tag, "<Button-1>", lambda _e, v=value: self._picked(v))
            right -= width + self._u(8)
        return top + height + self._u(6)

    def _bar_chart(self, x, y, wrap, rows):
        """Thanh ngang gọn, luôn kèm nhãn số để không phụ thuộc riêng vào màu."""
        for row in rows or []:
            label = str(row.get("label") or "")
            shown = str(row.get("display_value") or "")
            value = max(0.0, float(row.get("value") or 0))
            maximum = max(value, float(row.get("max_value") or 0), 1.0)
            label_item = self.inner.create_text(
                x, y + self._u(2), text=label, anchor="nw", fill=HUD_TEXT,
                font=self._font(FONT), width=max(self._u(60), wrap - self._u(72)))
            self.inner.create_text(x + wrap, y + self._u(2), text=shown, anchor="ne",
                                   fill=HUD_COLOR, font=self._font(FONT_BOLD))
            bar_top = max(y + self._u(18), self.inner.bbox(label_item)[3] + self._u(3))
            self.inner.create_rectangle(x, bar_top, x + wrap, bar_top + self._u(6),
                                        outline=HUD_DIM, width=self._u(1))
            filled = wrap * min(1.0, value / maximum)
            if filled > 0:
                self.inner.create_rectangle(x, bar_top, x + filled,
                                            bar_top + self._u(6),
                                            fill=HUD_COLOR, outline="")
            y = bar_top + self._u(16)
        return y + self._u(2)

    def _sparkline(self, x, y, wrap, points):
        points = list(points or [])
        if not points:
            return self._body(x, y, wrap, "Chưa có dữ liệu xu hướng.")
        top, height = y + self._u(6), self._u(54)
        self.inner.create_rectangle(x, top, x + wrap, top + height,
                                    outline=HUD_DIM, width=self._u(1))
        values = [max(0.0, float(p.get("value") or 0)) for p in points]
        maximum = max(values) or 1.0
        step = wrap / max(1, len(points) - 1)
        previous = None
        for index, (point, value) in enumerate(zip(points, values)):
            px = x + index * step
            py = top + height - self._u(5) - (height - self._u(10)) * value / maximum
            current = (px, py) if point.get("has_data") else None
            if previous is not None and current is not None:
                self.inner.create_line(previous[0], previous[1], current[0], current[1],
                                       fill=HUD_COLOR, width=self._u(2))
            if current is not None:
                radius = self._u(2)
                self.inner.create_oval(px - radius, py - radius,
                                       px + radius, py + radius,
                                       fill=HUD_COLOR, outline="")
            previous = current
        first = str(points[0].get("label") or "")
        last = str(points[-1].get("label") or "")
        self.inner.create_text(x, top + height + self._u(3), text=first, anchor="nw",
                               fill=HUD_DIM, font=self._font(FONT_SMALL))
        if len(points) > 1:
            self.inner.create_text(x + wrap, top + height + self._u(3),
                                   text=last, anchor="ne", fill=HUD_DIM,
                                   font=self._font(FONT_SMALL))
        return top + height + self._u(20)

    def _badge(self, x, y, wrap, text, kind="info"):
        colour = HUD_QUOTE if kind == "warn" else HUD_DIM
        item = self.inner.create_text(x + self._u(7), y + self._u(5),
                                      text=str(text), anchor="nw", fill=HUD_TEXT,
                                      font=self._font(FONT_SMALL),
                                      width=max(self._u(60), wrap - self._u(14)))
        box = self.inner.bbox(item)
        bottom = box[3] + self._u(5)
        self.inner.create_rectangle(x, y, x + wrap, bottom, outline=colour,
                                    width=self._u(1))
        self.inner.tag_raise(item)
        return bottom + self._u(6)

    def _picked(self, value):
        if self.on_pick is not None:
            self.on_pick(value)
