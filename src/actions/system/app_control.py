"""Mở/đóng ứng dụng — có ánh xạ tên thân thiện (kể cả tiếng Việt) sang file thực thi."""

import os
import re
import subprocess

from utils.data_loader import DataLoader
from utils.logger import get_logger

logger = get_logger(__name__)

_data = DataLoader()

# Chỉ cho phép tên thực thi "lành" (chữ/số/dấu chấm/gạch/khoảng trắng). Chặn ký tự shell
# (& | ; $ > < ` ...) để không thể tiêm lệnh. Dùng chung cho mở/đóng app.
_SAFE_EXE_RE = re.compile(r"^[\w.\-+ ]{1,60}$", re.UNICODE)


def _is_safe_exe(exe):
    return bool(exe) and bool(_SAFE_EXE_RE.match(exe))


def resolve_app_command(name):
    """Ánh xạ tên thân thiện -> lệnh thực thi dựa trên applications.json.

    'google chrome' / 'trình duyệt google' -> 'chrome'; 'văn bản' -> 'winword'.
    Không khớp thì trả về chính tên (để hệ điều hành tự thử).
    """
    if not name:
        return name
    key = name.strip().lower()
    aliases = _data.get_app_keywords()          # canonical -> [aliases]
    executables = _data.get_app_executables()   # canonical -> exe

    canonical = None
    for cano, alias_list in aliases.items():
        if key == cano or key in [a.lower() for a in alias_list]:
            canonical = cano
            break
    if canonical is None:  # khớp một phần (câu chứa alias)
        for cano, alias_list in aliases.items():
            if any(a.lower() in key for a in [cano] + alias_list):
                canonical = cano
                break
    if canonical is None:
        return key
    return executables.get(canonical, canonical)


def open_application(app_name):
    exe = resolve_app_command(app_name)
    if not _is_safe_exe(exe):
        logger.warning("Từ chối mở app tên không hợp lệ: %r", app_name)
        return f"Tên ứng dụng không hợp lệ: {app_name}."
    try:
        if os.name == 'nt':
            os.startfile(exe)
        elif os.uname().sysname == 'Darwin':
            subprocess.Popen(['open', '-a', exe])
        else:
            subprocess.Popen([exe])
        return f"Đã mở {app_name}."
    except OSError as e:
        logger.error("Không mở được %s (exe=%s): %s", app_name, exe, e)
        return f"Không mở được {app_name}: {e}"


def close_application(app_name):
    exe = resolve_app_command(app_name)
    if not _is_safe_exe(exe):
        logger.warning("Từ chối đóng app tên không hợp lệ: %r", app_name)
        return f"Tên ứng dụng không hợp lệ: {app_name}."
    try:
        if os.name == 'nt':
            # Truyền dạng ARGV (không qua shell) -> không thể tiêm lệnh; không /f để đóng
            # nhẹ nhàng, tránh mất dữ liệu chưa lưu.
            subprocess.run(['taskkill', '/im', f'{exe}.exe'], check=False)
        else:
            subprocess.call(['pkill', exe])
        return f"Đã đóng {app_name}."
    except OSError as e:
        logger.error("Không đóng được %s: %s", app_name, e)
        return f"Không đóng được {app_name}: {e}"
