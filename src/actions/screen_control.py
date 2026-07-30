"""
Đọc/điều khiển màn hình — CHỤP, TÌM CHỮ (OCR), CUỘN. Chạy HOÀN TOÀN LOCAL/OFFLINE.

Bảo mật (xem docs/ARCHITECTURE.md):
  - Tính năng nhạy cảm: chỉ bật khi SCREEN_CONTROL_ENABLED=true VÀ LLM là local
    (ép ở tầng app.py) — nội dung màn hình không rời máy.
  - Không có lời gọi mạng nào ở đây: chụp bằng PIL.ImageGrab, OCR bằng Tesseract
    (binary local), cuộn bằng ctypes. Ảnh lưu vào thư mục local.
  - Phạm vi HẸP: chỉ đọc + cuộn. KHÔNG click, KHÔNG gõ phím.

Phần tìm chữ (search_text) là hàm THUẦN, test được không cần màn hình.
"""

import os
from datetime import datetime

from utils.logger import get_logger
from utils.text_norm import norm as _norm

logger = get_logger(__name__)

WHEEL_DELTA = 120        # 1 "nấc" cuộn chuột trên Windows
MAX_SCROLL_NOTCHES = 20


# --------------------------------------------------------------------------- #
# Tìm chữ trong text OCR — THUẦN (test được)
# --------------------------------------------------------------------------- #
def search_text(ocr_text, query):
    """Trả về các DÒNG trong `ocr_text` có chứa `query` (không phân biệt hoa/dấu)."""
    q = _norm(query)
    if not q or not ocr_text:
        return []
    out = []
    for line in ocr_text.splitlines():
        line = line.strip()
        if line and q in _norm(line):
            out.append(line)
    return out


def summarize_find(matches, query, limit=5):
    """Chuyển danh sách dòng khớp thành câu tiếng Việt cho agent."""
    if not matches:
        return f"Không thấy '{query}' trên màn hình."
    shown = " | ".join(matches[:limit])
    more = f" (và {len(matches) - limit} dòng nữa)" if len(matches) > limit else ""
    return f"Tìm thấy '{query}' trên màn hình ({len(matches)} dòng): {shown}{more}"


# --------------------------------------------------------------------------- #
# Định vị tài nguyên
# --------------------------------------------------------------------------- #
def _default_capture_dir():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "captures")


def _find_tesseract():
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if os.path.exists(p):
            return p
    return None      # để pytesseract tự tìm trên PATH


# --------------------------------------------------------------------------- #
# Bộ điều khiển màn hình (giữ cấu hình; các thao tác thật)
# --------------------------------------------------------------------------- #
class ScreenController:
    def __init__(self, save_dir=None, tesseract_cmd=None, lang="vie+eng"):
        self.save_dir = save_dir or _default_capture_dir()
        self.tesseract_cmd = tesseract_cmd or _find_tesseract()
        self.lang = lang

    # --- CHỤP ---
    def capture(self):
        try:
            from PIL import ImageGrab
            os.makedirs(self.save_dir, exist_ok=True)
            img = ImageGrab.grab()
            name = datetime.now().strftime("screen_%Y%m%d_%H%M%S.png")
            path = os.path.join(self.save_dir, name)
            img.save(path)
            logger.info("📸 Đã chụp màn hình -> %s", path)
            return f"Đã chụp màn hình ({img.size[0]}x{img.size[1]}), lưu tại: {path}"
        except Exception as e:
            logger.error("Chụp màn hình lỗi: %s", e)
            return f"Không chụp được màn hình: {e}"

    # --- TÌM CHỮ (OCR) ---
    def find(self, query):
        if not query or not str(query).strip():
            return "Cần cho biết từ/cụm từ cần tìm trên màn hình."
        text = self._ocr_screen()
        if text is None:
            return "Không đọc được chữ trên màn hình (OCR lỗi hoặc thiếu Tesseract)."
        return summarize_find(search_text(text, query), query)

    def _ocr_screen(self):
        try:
            from PIL import ImageGrab
            import pytesseract
            if self.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
            return pytesseract.image_to_string(ImageGrab.grab(), lang=self.lang)
        except Exception as e:
            logger.error("OCR màn hình lỗi: %s", e)
            return None

    # --- CUỘN ---
    def scroll(self, direction="down", amount=3):
        """Cuộn tại cửa sổ ĐANG HOẠT ĐỘNG (foreground) — vd Chrome/YouTube bạn đang xem.

        Bánh xe chuột của Windows chỉ ăn vào cửa sổ dưới con trỏ; khi ra lệnh bằng
        giọng nói con trỏ không nằm trên trang web -> phải tạm đưa con trỏ vào giữa
        cửa sổ foreground rồi cuộn, sau đó trả con trỏ về chỗ cũ.
        """
        if os.name != "nt":
            return "Cuộn màn hình chỉ hỗ trợ trên Windows."
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND       # tránh cắt HWND 64-bit
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

            try:
                notches = max(1, min(MAX_SCROLL_NOTCHES, int(amount)))
            except (TypeError, ValueError):
                notches = 3
            up = str(direction).strip().lower() in ("up", "lên", "len", "tren", "trên")
            delta = WHEEL_DELTA if up else -WHEEL_DELTA

            # Đưa con trỏ vào giữa cửa sổ foreground để cuộn ĐÚNG cửa sổ đang xem.
            moved, orig = False, wintypes.POINT()
            try:
                hwnd = user32.GetForegroundWindow()
                rect = wintypes.RECT()
                if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    user32.GetCursorPos(ctypes.byref(orig))
                    user32.SetCursorPos((rect.left + rect.right) // 2,
                                        (rect.top + rect.bottom) // 2)
                    moved = True
            except Exception:
                moved = False

            for _ in range(notches):
                user32.mouse_event(0x0800, 0, 0, delta, 0)   # MOUSEEVENTF_WHEEL

            if moved:
                try:
                    user32.SetCursorPos(orig.x, orig.y)      # trả con trỏ về chỗ cũ
                except Exception:
                    pass

            logger.info("🖱 Cuộn %s %d nấc", "lên" if up else "xuống", notches)
            return f"Đã cuộn {'lên' if up else 'xuống'} {notches} nấc."
        except Exception as e:
            logger.error("Cuộn màn hình lỗi: %s", e)
            return f"Không cuộn được màn hình: {e}"
