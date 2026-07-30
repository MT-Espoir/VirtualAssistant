"""
Sửa lỗi nhận dạng giọng nói phổ biến — logic THUẦN.
"""

import json
import os

from utils.logger import get_logger
from utils.text_norm import norm as _norm

logger = get_logger(__name__)

# Chỉ ánh xạ MỘT mục được xác nhận thực tế ('hip hop' -> 'github'); phần còn lại là
# các nhầm lẫn thường gặp. Không khớp thì vô hại (chỉ đơn giản không thay gì). Thêm
# mục mới vào components/data/stt_corrections.json khi bạn phát hiện lỗi mới.
_DEFAULT_CORRECTIONS = {
    "hip hop": "github",
    "hít hóp": "github",
    "gít hụp": "github",
    "diu túp": "youtube",
    "diu tup": "youtube",
    "phây búc": "facebook",
    "phây bút": "facebook",
    "crôm": "chrome",
    "gu gồ": "google",
}

_CORRECTIONS_FILE = os.path.join(
    os.path.dirname(__file__), "..", "components", "data", "stt_corrections.json")


def load_corrections(path=_CORRECTIONS_FILE):
    """Bảng sửa mặc định gộp với file JSON (nếu có). File ghi đè mặc định trùng khoá."""
    corrections = dict(_DEFAULT_CORRECTIONS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            corrections.update({str(k): str(v) for k, v in data.items()})
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        logger.warning("Không đọc được bảng sửa STT (%s): %s", path, e)
    return corrections


def apply_corrections(text, corrections):
    """Thay các cụm nghe nhầm trong `text` bằng từ đúng.

    So khớp theo cửa sổ token (bỏ dấu, thường hoá); ưu tiên cụm DÀI trước để cụm
    nhiều từ được xử lý trước cụm một từ. Giữ nguyên các token không liên quan.
    """
    if not text or not corrections:
        return text

    # (các token chuẩn hoá của cụm khoá, từ thay thế), sắp theo số token giảm dần.
    rules = []
    for wrong, right in corrections.items():
        wrong_tokens = [_norm(t) for t in wrong.split() if _norm(t)]
        if wrong_tokens:
            rules.append((wrong_tokens, right))
    rules.sort(key=lambda r: len(r[0]), reverse=True)

    orig_tokens = text.split()
    norm_tokens = [_norm(t) for t in orig_tokens]

    out = []
    i = 0
    while i < len(orig_tokens):
        replaced = False
        for wrong_tokens, right in rules:
            n = len(wrong_tokens)
            if norm_tokens[i:i + n] == wrong_tokens:
                out.append(right)
                i += n
                replaced = True
                break
        if not replaced:
            out.append(orig_tokens[i])
            i += 1
    return " ".join(out)


# Bảng nạp sẵn một lần để dùng chung (nơi gọi có thể truyền bảng riêng nếu cần).
DEFAULT = load_corrections()


def correct(text):
    """Tiện ích: áp bảng sửa mặc định lên `text`."""
    return apply_corrections(text, DEFAULT)
