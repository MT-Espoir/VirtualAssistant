"""Test logic THUẦN của ProactiveMonitor (bản tin sáng 1 lần/ngày + cảnh báo pin, dedup)."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.proactive import check_proactive


def test_brief_fires_after_time_once_per_day():
    now = datetime(2030, 1, 1, 7, 30)
    events, (last, _) = check_proactive(now, (7, 0), None, 80, True, 20, False)
    assert "brief" in events and last == now.date()
    events2, _ = check_proactive(now, (7, 0), last, 80, True, 20, False)   # đã brief hôm nay
    assert "brief" not in events2


def test_brief_not_before_time():
    now = datetime(2030, 1, 1, 6, 0)
    events, (last, _) = check_proactive(now, (7, 0), None, 80, True, 20, False)
    assert "brief" not in events and last is None


def test_battery_alert_when_low_on_battery():
    now = datetime(2030, 1, 1, 12, 0)
    events, (_, warned) = check_proactive(now, (7, 0), now.date(), 15, False, 20, False)
    assert "battery" in events and warned is True


def test_battery_dedup_and_reset_on_plug():
    now = datetime(2030, 1, 1, 12, 0)
    # đã cảnh báo, vẫn pin thấp -> KHÔNG lặp
    assert "battery" not in check_proactive(now, (7, 0), now.date(), 15, False, 20, True)[0]
    # cắm sạc -> reset cờ warned
    events, (_, warned) = check_proactive(now, (7, 0), now.date(), 15, True, 20, True)
    assert "battery" not in events and warned is False


def test_no_battery_alert_when_plugged_or_ok():
    now = datetime(2030, 1, 1, 12, 0)
    assert "battery" not in check_proactive(now, (7, 0), now.date(), 15, True, 20, False)[0]   # đang sạc
    assert "battery" not in check_proactive(now, (7, 0), now.date(), 80, False, 20, False)[0]  # pin cao


def test_no_battery_when_pct_none():
    now = datetime(2030, 1, 1, 12, 0)
    assert "battery" not in check_proactive(now, (7, 0), now.date(), None, False, 20, False)[0]
