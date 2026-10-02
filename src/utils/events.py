"""
Kênh sự kiện giữa "bộ não" (agent, chạy nền) và giao diện avatar (Tkinter, chạy
trên main thread). Agent phát trạng thái/cảm xúc; avatar đọc và cập nhật khuôn mặt.

Dùng queue thread-safe: agent gọi bus.emit(...) từ thread nền, avatar poll queue
qua Tk .after(). Tách UI khỏi core — core không import Tkinter.
"""

import queue
import threading
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from utils.debug import safe_debug_value


@dataclass
class AssistantEvent:
    state: Optional[str] = None      # idle | listening | thinking | speaking
    emotion: Optional[str] = None    # neutral | happy | sad
    text: Optional[str] = None       # câu trả lời / trạng thái để hiện
    ui: Optional[dict] = None        # lệnh UI có target: avatar mặc định | hud
    places: Optional[dict] = None    # {rows, need} -> panel kết quả địa điểm
    draft: Optional[dict] = None     # {to, subject, body} -> panel nháp email; {} = đóng panel
    mail: Optional[dict] = None      # {tu, tieu_de, ngay, than} -> panel THƯ ĐẾN; {} = đóng
    mails: Optional[dict] = None     # {rows, q} -> panel DANH SÁCH thư; rows rỗng = đóng
    system: Optional[dict] = None    # {kind, rows, ...} -> panel quản trị; rows rỗng = đóng
    care: Optional[dict] = None      # {action: pulse|cancel, token} -> silent avatar cue
    care_style: Optional[dict] = None  # preference SALM-2 -> panel xem/reset
    activity: Optional[dict] = None  # aggregate read-only -> Activity Insights panel
    control: Optional[dict] = None   # main HUD system controls, separate from debug


class AssistantBus:
    def __init__(self):
        self._q = queue.Queue()
        # Tách khỏi queue chức năng: bật debug không được làm đổi thứ tự/số lượng event
        # mà avatar, test hoặc consumer nghiệp vụ vốn đang nhận.
        self._debug_q = deque()
        self._debug_lock = threading.Lock()
        self._debug_capacity = 1024
        self._debug_dropped = 0
        self._debug_active = threading.Event()
        self._debug_active.set()
        self._state_listeners = []
        self._listeners_lock = threading.Lock()
        # Ngữ cảnh bề mặt UI được dùng bởi fast-path để hiểu câu rút gọn kiểu
        # "phóng to nó lên". Không lưu hội thoại ở đây, chỉ lưu đích thao tác gần nhất.
        self._ui_context_lock = threading.Lock()
        self._ui_target = "avatar"

    def set_ui_target(self, target):
        """Cập nhật bề mặt đang được nói tới; an toàn khi gọi từ worker hoặc Tk thread."""
        if target not in {"avatar", "hud"}:
            return
        with self._ui_context_lock:
            self._ui_target = target

    def current_ui_target(self):
        with self._ui_context_lock:
            return self._ui_target

    def emit(self, state=None, emotion=None, text=None, proactive=False):
        self._q.put(AssistantEvent(state=state, emotion=emotion, text=text))
        if state is not None and not proactive:
            with self._listeners_lock:
                listeners = tuple(self._state_listeners)
            for callback in listeners:
                try:
                    callback(state)
                except Exception:
                    # Producer UI không được chết chỉ vì một observer phụ trợ.
                    pass

    def subscribe_state(self, callback):
        """Theo dõi trạng thái của luồng trực tiếp để gate chặn output chủ động.

        Event do chính dispatcher chủ động tạo truyền ``proactive=True`` nên không tự
        coi giọng/cue của mình là một luồng cạnh tranh và tự huỷ giữa chừng.
        """
        with self._listeners_lock:
            self._state_listeners.append(callback)

    def emit_care(self, action, token):
        self._q.put(AssistantEvent(care={"action": action, "token": token}))

    def emit_care_style(self, snapshot):
        """Gửi bản sao preference SALM; producer nền không chia sẻ dict với Tk."""
        if snapshot:
            self.set_ui_target("hud")
        self._q.put(AssistantEvent(care_style=dict(snapshot or {})))

    def emit_activity(self, snapshot):
        """Gửi aggregate SALM sang UI, không chia sẻ cấu trúc lồng nhau giữa threads."""
        if snapshot:
            self.set_ui_target("hud")
        self._q.put(AssistantEvent(activity=deepcopy(snapshot or {})))

    def emit_control(self, action):
        if action not in ("show", "hide"):
            raise ValueError("invalid control panel action")
        if action == "show":
            self.set_ui_target("hud")
        self._q.put(AssistantEvent(control={"action": action}))

    def set_debug_enabled(self, enabled):
        """Stop formatting and retaining diagnostics outside a debug session."""
        if enabled:
            self._debug_active.set()
        else:
            self._debug_active.clear()
            with self._debug_lock:
                self._debug_q.clear()
                self._debug_dropped = 0

    def emit_debug(self, category, message, data=None, level="INFO"):
        """Phát một event debug an toàn từ bất kỳ thread nào.

        Payload được sao chép, che khóa nhạy cảm và cắt độ dài ngay tại biên producer;
        UI không bao giờ giữ tham chiếu tới dict còn đang bị thread khác thay đổi.
        """
        if not self._debug_active.is_set():
            return
        event = {
            "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "category": str(category or "system").strip().lower(),
            "level": str(level or "INFO").strip().upper(),
            "message": safe_debug_value(str(message or "")),
            "data": safe_debug_value(data or {}),
            "thread": threading.current_thread().name,
        }
        with self._debug_lock:
            if len(self._debug_q) >= self._debug_capacity:
                # Keep errors and state changes when samples flood the panel.
                discard = next((index for index, old in enumerate(self._debug_q)
                                if not self._debug_important(old)), None)
                if discard is None:
                    if not self._debug_important(event):
                        self._debug_dropped += 1
                        return
                    self._debug_q.popleft()
                else:
                    del self._debug_q[discard]
                self._debug_dropped += 1
            self._debug_q.append(event)

    @staticmethod
    def _debug_important(event):
        if event["level"] in {"ERROR", "WARNING"}:
            return True
        message = event["message"].lower()
        return any(word in message for word in (
            "connected", "disconnected", "enabled", "disabled", "paused",
            "resumed", "stopped", "unavailable", "failed", "sẵn sàng",
            "đã dừng", "bật", "tắt", "lỗi"))

    def emit_ui(self, **ui):
        """Gửi lệnh UI tới main thread; thiếu ``target`` giữ tương thích với avatar."""
        self.set_ui_target(ui.get("target") or "avatar")
        self._q.put(AssistantEvent(ui=ui))

    def emit_hud_scale(self, scale=None, scale_delta=None, source=None):
        """API nguồn-độc-lập cho zoom HUD liên tục.

        Voice có thể gửi bước tương đối lớn; camera/gesture có thể gửi nhiều delta nhỏ.
        Cả hai đi đúng một contract và biên scale được kẹp ở phía UI.
        """
        payload = {"target": "hud"}
        if scale is not None:
            payload["scale"] = scale
        if scale_delta is not None:
            payload["scale_delta"] = scale_delta
        if source:
            payload["source"] = str(source)
        if len(payload) > 1:
            self.set_ui_target("hud")
            self._q.put(AssistantEvent(ui=payload))

    def emit_places(self, rows, need=None):
        """Gửi danh sách địa điểm cho panel kết quả.

        Đi qua ĐÚNG kênh này thay vì gọi thẳng Tk: tool chạy ở thread nền, mà widget Tk
        chỉ được đụng từ main thread. Danh sách rỗng = ẩn panel.
        """
        rows = list(rows or [])
        if rows:
            self.set_ui_target("hud")
        self._q.put(AssistantEvent(places={"rows": rows, "need": need}))

    def emit_draft(self, draft):
        """Gửi bản nháp email cho panel xem-trước. `None`/rỗng = ĐÓNG panel.

        Cùng lý do với emit_places: agent chạy ở thread nền, widget Tk chỉ được đụng từ
        main thread. Dict rỗng thay vì None trong event để `_poll` phân biệt được
        'không có tin gì về nháp' với 'đóng panel đi'.
        """
        if draft:
            self.set_ui_target("hud")
        self._q.put(AssistantEvent(draft=dict(draft) if draft else {}))

    def emit_mail(self, mail):
        """Gửi một lá thư ĐẾN cho panel xem. `None`/rỗng = ĐÓNG panel.

        Đây là đường DUY NHẤT nội dung thư tới được mắt người dùng mà KHÔNG đi qua ngữ
        cảnh LLM. Với nội dung do người ngoài soạn, khác biệt đó có giá trị thật:
        `untrusted.boc()` chỉ là giảm thiểu, còn không-đưa-vào là triệt tiêu.
        """
        if mail:
            self.set_ui_target("hud")
        self._q.put(AssistantEvent(mail=dict(mail) if mail else {}))

    def emit_mail_list(self, rows, q=None):
        """Gửi DANH SÁCH thư tìm được cho panel. Danh sách rỗng = ẩn panel.

        Cùng panel với `emit_mail`: bấm một dòng thì chi tiết thư THAY CHỖ danh sách,
        đúng lối danh-sách-rồi-chi-tiết quen thuộc, không phải hai cửa sổ chồng nhau.
        """
        rows = list(rows or [])
        if rows:
            self.set_ui_target("hud")
        self._q.put(AssistantEvent(mails={"rows": rows, "q": q}))

    def emit_system(self, kind, rows, **context):
        """Gửi snapshot quản trị máy cho HUD; danh sách rỗng = ẩn panel.

        Sao chép từng dòng vì producer chạy ở thread nền còn Tk đọc sau trên main thread;
        giữ chung dict sẽ tạo race nếu action tiếp tục đánh dấu/chỉnh dữ liệu sau khi emit.
        """
        payload = dict(context, kind=kind,
                       rows=[dict(row) for row in (rows or [])])
        if payload["rows"]:
            self.set_ui_target("hud")
        self._q.put(AssistantEvent(system=payload))

    def drain(self):
        """Lấy hết event đang chờ (không chặn)."""
        events = []
        while True:
            try:
                events.append(self._q.get_nowait())
            except queue.Empty:
                break
        return events

    def drain_debug(self):
        """Lấy hết event panel debug đang chờ, độc lập event chức năng."""
        with self._debug_lock:
            events = list(self._debug_q)
            self._debug_q.clear()
            dropped = self._debug_dropped
            self._debug_dropped = 0
        if dropped:
            events.append({
                "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "category": "system", "level": "WARNING",
                "message": "Debug diagnostics dropped while UI was busy",
                "data": {"count": dropped}, "thread": threading.current_thread().name,
            })
        return events
