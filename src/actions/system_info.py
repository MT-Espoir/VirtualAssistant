"""
Truy vấn thông tin & tình trạng máy tính (RAM, ổ đĩa, CPU, pin) qua psutil.

Mỗi hàm trả về một chuỗi tiếng Việt gọn để agent đọc lại cho người dùng.
`get_system_summary(what)` là điểm vào chính, gộp theo yêu cầu.
"""

import os
import shutil

import psutil

from utils.logger import get_logger

logger = get_logger(__name__)


def _fmt_gb(num_bytes) -> str:
    return f"{num_bytes / (1024 ** 3):.1f} GB"


def get_memory_info() -> str:
    m = psutil.virtual_memory()
    return (f"RAM: đã dùng {_fmt_gb(m.used)}/{_fmt_gb(m.total)} "
            f"({m.percent:.0f}%), còn trống {_fmt_gb(m.available)}.")


def get_disk_info(path: str = None) -> str:
    if path is None:
        path = os.path.abspath(os.sep)  # gốc ổ hiện tại (C:\ trên Windows, / trên Unix)
    total, used, free = shutil.disk_usage(path)
    percent = used / total * 100 if total else 0
    return (f"Ổ đĩa: đã dùng {_fmt_gb(used)}/{_fmt_gb(total)} "
            f"({percent:.0f}%), còn trống {_fmt_gb(free)}.")


def get_cpu_info() -> str:
    percent = psutil.cpu_percent(interval=0.3)
    cores = psutil.cpu_count(logical=True)
    return f"CPU: đang dùng {percent:.0f}% trên {cores} luồng."


def get_battery_info() -> str:
    battery = getattr(psutil, "sensors_battery", lambda: None)()
    if battery is None:
        return "Pin: máy không có pin hoặc không đọc được."
    status = "đang sạc" if battery.power_plugged else "dùng pin"
    return f"Pin: {battery.percent:.0f}% ({status})."


_SECTIONS = {
    "memory": get_memory_info,
    "ram": get_memory_info,
    "disk": get_disk_info,
    "cpu": get_cpu_info,
    "battery": get_battery_info,
    "pin": get_battery_info,
}


def get_system_summary(what: str = "all") -> str:
    """Trả về thông tin hệ thống. what: all | memory | disk | cpu | battery."""
    what = (what or "all").lower()

    if what == "all":
        funcs = [get_memory_info, get_disk_info, get_cpu_info, get_battery_info]
    elif what in _SECTIONS:
        funcs = [_SECTIONS[what]]
    else:
        return f"Không hiểu yêu cầu thông tin '{what}'."

    parts = []
    for fn in funcs:
        try:
            parts.append(fn())
        except Exception as e:  # psutil có thể lỗi tùy nền tảng
            logger.error("Lỗi đọc thông tin hệ thống (%s): %s", fn.__name__, e)
            parts.append("(không đọc được một mục thông tin)")
    return " ".join(parts)
