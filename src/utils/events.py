"""
Kênh sự kiện giữa "bộ não" (agent, chạy nền) và giao diện avatar (Tkinter, chạy
trên main thread). Agent phát trạng thái/cảm xúc; avatar đọc và cập nhật khuôn mặt.

Dùng queue thread-safe: agent gọi bus.emit(...) từ thread nền, avatar poll queue
qua Tk .after(). Tách UI khỏi core — core không import Tkinter.
"""

import queue
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AssistantEvent:
    state: Optional[str] = None      # idle | listening | thinking | speaking
    emotion: Optional[str] = None    # neutral | happy | sad
    text: Optional[str] = None       # câu trả lời / trạng thái để hiện
    ui: Optional[dict] = None        # lệnh giao diện avatar (scale_delta / opacity_delta...)
    places: Optional[dict] = None    # {rows, need} -> panel kết quả địa điểm
    draft: Optional[dict] = None     # {to, subject, body} -> panel nháp email; {} = đóng panel


class AssistantBus:
    def __init__(self):
        self._q = queue.Queue()

    def emit(self, state=None, emotion=None, text=None):
        self._q.put(AssistantEvent(state=state, emotion=emotion, text=text))

    def emit_ui(self, **ui):
        """Gửi lệnh điều chỉnh giao diện avatar (đổi kích thước / độ mờ) tới main thread."""
        self._q.put(AssistantEvent(ui=ui))

    def emit_places(self, rows, need=None):
        """Gửi danh sách địa điểm cho panel kết quả.

        Đi qua ĐÚNG kênh này thay vì gọi thẳng Tk: tool chạy ở thread nền, mà widget Tk
        chỉ được đụng từ main thread. Danh sách rỗng = ẩn panel.
        """
        self._q.put(AssistantEvent(places={"rows": list(rows or []), "need": need}))

    def emit_draft(self, draft):
        """Gửi bản nháp email cho panel xem-trước. `None`/rỗng = ĐÓNG panel.

        Cùng lý do với emit_places: agent chạy ở thread nền, widget Tk chỉ được đụng từ
        main thread. Dict rỗng thay vì None trong event để `_poll` phân biệt được
        'không có tin gì về nháp' với 'đóng panel đi'.
        """
        self._q.put(AssistantEvent(draft=dict(draft) if draft else {}))

    def drain(self):
        """Lấy hết event đang chờ (không chặn)."""
        events = []
        while True:
            try:
                events.append(self._q.get_nowait())
            except queue.Empty:
                break
        return events
