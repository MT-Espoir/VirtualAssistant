"""Liệt kê + chuyển focus cửa sổ ứng dụng đang mở trên Windows (qua pywin32).

Khác với `app_control.open_application` (MỞ MỚI một ứng dụng): module này thao tác
trên các cửa sổ ĐANG CHẠY — liệt kê chúng, và đưa một cửa sổ ra trước (focus) theo tên.

Phần LOGIC thuần (lọc/khớp tên cửa sổ) tách khỏi lời gọi win32 để test được và để
suy biến an toàn khi thiếu pywin32 (vd môi trường không phải Windows).
"""

from utils.logger import get_logger
from utils.text_norm import strip_accents

logger = get_logger(__name__)

try:
    import win32con
    import win32gui
except ImportError:                     # không phải Windows / thiếu pywin32
    win32con = None
    win32gui = None

# Cửa sổ nền/hệ thống nên bỏ qua khi liệt kê (không phải app người dùng).
_IGNORE_TITLES = {"Program Manager", "Default IME", "MSCTFIME UI", "Windows Input Experience"}


def _enum_windows():
    """List (hwnd, title) các cửa sổ top-level ĐANG HIỆN, có tiêu đề.

    Bỏ cửa sổ ẩn, tool-window (không lên taskbar) và vài cửa sổ shell nền.
    """
    if win32gui is None:
        return []
    result = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title or title in _IGNORE_TITLES:
            return
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if ex_style & win32con.WS_EX_TOOLWINDOW:   # cửa sổ công cụ (không lên taskbar)
            return
        result.append((hwnd, title))

    win32gui.EnumWindows(_cb, None)
    return result


def _match_window(windows, name):
    """Chọn cửa sổ khớp 'name' tốt nhất (bỏ dấu, không phân biệt hoa thường).

    Ưu tiên: khớp CHÍNH XÁC tiêu đề > bắt đầu bằng > chứa chuỗi con.
    `windows` là list (hwnd, title). Trả (hwnd, title) hoặc None.
    """
    key = strip_accents(str(name).strip().lower())
    if not key:
        return None
    start = contains = None
    for hwnd, title in windows:
        norm_title = strip_accents(title.lower())
        if norm_title == key:
            return hwnd, title                     # khớp chính xác -> chốt luôn
        if start is None and norm_title.startswith(key):
            start = (hwnd, title)
        if contains is None and key in norm_title:
            contains = (hwnd, title)
    return start or contains


def list_windows():
    """Câu tiếng Việt liệt kê tiêu đề các cửa sổ đang mở."""
    if win32gui is None:
        return "Chức năng liệt kê cửa sổ chỉ chạy trên Windows."
    windows = _enum_windows()
    if not windows:
        return "Không thấy cửa sổ nào đang mở."
    lines = "\n".join(f"- {title}" for _, title in windows)
    return f"Đang mở {len(windows)} cửa sổ:\n{lines}"


def _bring_to_front(hwnd):
    """Đưa cửa sổ ra trước — khôi phục nếu đang thu nhỏ; vượt hạn chế của
    SetForegroundWindow bằng mẹo giả một nhịp phím ALT để mở khoá."""
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        # Windows chặn SetForegroundWindow khi tiến trình không có "input gần đây"
        # -> giả một nhịp ALT để mở khoá rồi thử lại.
        try:
            import win32api
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception as e:
            logger.warning("Không đưa cửa sổ ra trước được: %s", e)
            return False


def switch_to_window(name):
    """Chuyển focus sang cửa sổ có tiêu đề khớp 'name'."""
    if win32gui is None:
        return "Chức năng chuyển cửa sổ chỉ chạy trên Windows."
    if not name or not str(name).strip():
        return "Cần cho biết tên cửa sổ cần chuyển sang."
    match = _match_window(_enum_windows(), name)
    if match is None:
        return f"Không thấy cửa sổ nào đang mở tên giống '{name}'."
    hwnd, title = match
    if _bring_to_front(hwnd):
        return f"Đã chuyển sang cửa sổ {title}."
    return f"Tìm thấy cửa sổ {title} nhưng không đưa ra trước được."
