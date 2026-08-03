"""ProactiveMonitor — vòng NỀN chủ động: bản tin sáng (1 lần/ngày) + cảnh báo pin yếu.

Trợ lý TỰ khởi xướng thay vì chỉ phản ứng. Tách logic THUẦN (`check_proactive`: quyết định
theo mốc thời gian + trạng thái pin) khỏi thread/psutil để test tất định. Fire qua callback
`on_brief()` / `on_battery(pct)` — service không biết TTS (app.py nối vào), giống scheduler.
"""

import threading
from datetime import datetime

from utils.logger import get_logger

logger = get_logger(__name__)


def check_proactive(now, brief_time, last_brief_date, battery_pct, plugged,
                    battery_threshold, battery_warned):
    """Quyết định (THUẦN) nên fire gì. Trả (events, (last_brief_date_mới, battery_warned_mới)).

    events: danh sách con trong {'brief','battery'}.
    - brief: khi qua mốc giờ bản tin hôm nay và CHƯA đọc bản tin hôm nay.
    - battery: pin <= ngưỡng, ĐANG dùng pin, chưa cảnh báo (dedup tới khi cắm sạc lại).
    """
    events = []
    today = now.date()
    hh, mm = brief_time
    brief_moment = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if last_brief_date != today and now >= brief_moment:
        events.append("brief")
        last_brief_date = today

    if plugged:
        battery_warned = False                      # cắm sạc -> cho phép cảnh báo lại lần sau
    elif battery_pct is not None and battery_pct <= battery_threshold and not battery_warned:
        events.append("battery")
        battery_warned = True

    return events, (last_brief_date, battery_warned)


def _read_battery():
    """(phần trăm|None, đang_sạc). None nếu máy không có pin/không đọc được."""
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return None, True                       # không pin -> coi như luôn 'cắm điện'
        return b.percent, bool(b.power_plugged)
    except Exception as e:
        logger.debug("Không đọc được pin: %s", e)
        return None, True


class ProactiveMonitor:
    def __init__(self, on_brief, on_battery, brief_time=(7, 0),
                 battery_threshold=20, poll_interval=60):
        self.on_brief = on_brief
        self.on_battery = on_battery
        self.brief_time = brief_time
        self.battery_threshold = battery_threshold
        self.poll_interval = poll_interval
        # Khởi tạo: nếu đã QUA giờ bản tin lúc bật app -> coi như "đã đọc hôm nay" để KHÔNG
        # đọc bản tin trễ ngay lúc khởi động; còn trước giờ -> để None cho nó đọc đúng giờ.
        now = datetime.now()
        moment = now.replace(hour=brief_time[0], minute=brief_time[1], second=0, microsecond=0)
        self._last_brief_date = now.date() if now >= moment else None
        self._battery_warned = False
        self._stop = threading.Event()
        self._thread = None

    def _tick(self):
        pct, plugged = _read_battery()
        events, (self._last_brief_date, self._battery_warned) = check_proactive(
            datetime.now(), self.brief_time, self._last_brief_date, pct, plugged,
            self.battery_threshold, self._battery_warned)
        for e in events:
            try:
                if e == "brief":
                    self.on_brief()
                elif e == "battery":
                    self.on_battery(pct)
            except Exception as ex:                 # callback lỗi không được làm chết vòng nền
                logger.error("Lỗi khi chủ động '%s': %s", e, ex)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.wait(self.poll_interval):
            try:
                self._tick()
            except Exception as e:
                logger.error("Lỗi vòng chủ động: %s", e)
