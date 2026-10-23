"""`gws_calendar_today` phải lấy trọn ngày theo giờ máy, không phải từ lúc gọi tới hết ngày UTC.

Server MCP cần `fastmcp` + thư viện Google; môi trường không có thì bỏ qua cả file.
"""

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "mcp_servers"))

gp = pytest.importorskip("google_personal",
                         reason="cần fastmcp + google-api-python-client (dùng ml_env)")


def test_today_range_covers_whole_local_day_late_in_evening():
    """F05: hỏi lúc 23h vẫn thấy sự kiện buổi sáng, và không lấn sang sáng mai."""
    late = datetime(2030, 3, 5, 23, 0).astimezone()
    start, end = gp._today_range(late)
    assert start.replace(tzinfo=None) == datetime(2030, 3, 5)
    assert end.replace(tzinfo=None) == datetime(2030, 3, 6)
    assert start <= datetime(2030, 3, 5, 7, 30).astimezone() < end
    assert not start <= datetime(2030, 3, 6, 6, 0).astimezone() < end


def test_calendar_today_sends_local_day_bounds(monkeypatch):
    sent = {}

    class Events:
        def list(self, **kwargs):
            sent.update(kwargs)
            return self

        def execute(self):
            return {"items": []}

    class Calendar:
        def events(self):
            return Events()

    monkeypatch.setattr(gp, "_calendar", lambda _email: Calendar())
    tool = getattr(gp.gws_calendar_today, "fn", gp.gws_calendar_today)
    tool()
    start, end = datetime.fromisoformat(sent["timeMin"]), datetime.fromisoformat(sent["timeMax"])
    assert start.utcoffset() is not None and start.replace(tzinfo=None).time() == datetime.min.time()
    assert end.replace(tzinfo=None) == start.replace(tzinfo=None) + timedelta(days=1)
