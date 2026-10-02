"""Inventory and lifecycle of user-facing controls. No Tk or LLM dependencies."""

import math
import threading

from utils.config import config
from utils.control_settings import controls


# All existing boolean feature flags, including independent SALM language lanes.
# Startup-only options are explicit; saving never pretends their service restarted.
FLAG_GROUPS = {
    "Dịch vụ": {
        "BROWSER_BRIDGE_ENABLED": "Điều khiển trình duyệt Chrome",
        "SCREEN_CONTROL_ENABLED": "Đọc và điều khiển màn hình (LLM local)",
        "MCP_ENABLED": "Kết nối lịch và email qua MCP",
        "PROACTIVE_ENABLED": "Bản tin sáng và cảnh báo pin",
        "DATA_DATABASE_ENABLED": "Kho dữ liệu SQLite",
        "RESEARCH_CACHE_ENABLED": "Bộ nhớ đệm nghiên cứu",
        "DEBUG_PANEL_ENABLED": "Bảng chẩn đoán",
    },
    "Hoạt động và chăm sóc": {
        "SALM_ENABLED": "Theo dõi hoạt động máy tính",
        "SALM_WASAPI_MEDIA_FALLBACK": "Nhận biết media qua âm thanh ứng dụng",
        "SALM_POLICY_SHADOW_ENABLED": "Theo dõi chính sách nhắc nghỉ",
        "SALM_SILENT_CARE_ENABLED": "Nhắc nghỉ bằng avatar",
        "SALM_GENTLE_CHECKIN_ENABLED": "Nhắc nghỉ bằng giọng nói",
        "SALM_CARE_LLM_INTENT_ENABLED": "Hiểu câu trả lời nhắc nghỉ bằng AI",
        "SALM_CARE_LLM_LANGUAGE_ENABLED": "Soạn lời nhắc nghỉ bằng AI",
        "SALM_CARE_STYLE_LEARNING_ENABLED": "Học phong cách nhắc nghỉ",
        "SALM_USER_DND_ENABLED": "Cho phép chế độ không làm phiền nhắc nghỉ",
        "SALM_LATE_NIGHT_ENABLED": "Nhắc khi làm việc khuya",
        "SALM_LATE_NIGHT_LLM_LANGUAGE_ENABLED": "Soạn lời nhắc khuya bằng AI",
        "STARTUP_GREETING_ENABLED": "Lời chào khi khởi động",
        "SALM_WELCOME_BACK_ENABLED": "Lời chào khi quay lại",
        "SALM_LIFECYCLE_GREETING_LLM_ENABLED": "Soạn lời chào bằng AI",
    },
    "Giọng nói và trí nhớ": {
        "REQUIRE_WAKE_WORD": "Yêu cầu gọi tên trước khi ra lệnh",
        "BARGE_IN": "Ngắt lời trợ lý khi đang nói",
        "FAST_COMMANDS": "Thực hiện nhanh lệnh trực tiếp",
        "SKIP_RESPOND_FOR_SPEAKABLE": "Đọc trực tiếp kết quả công cụ",
        "TTS_ROBOT": "Hiệu ứng giọng robot",
        "LTM_AUTO_EXTRACT": "Củng cố trí nhớ từ hội thoại",
        "LTM_AUTO_FACTS": "Lưu sự thật tự suy ra từ hội thoại",
        "HABITS_ENABLED": "Học thói quen",
        "PERSONA_ENABLED": "Tính cách và tâm trạng avatar",
        "PERSONA_AUTO_TUNE": "Tự điều chỉnh tính cách",
    },
    "Webcam": {
        "CAMERA_ENABLED": "Webcam và phát hiện người trong phòng",
        "CAMERA_FACE_ENABLED": "Gợi ý khớp khuôn mặt chủ máy",
        "CAMERA_GESTURE_ENABLED": "Cử chỉ tay điều khiển giao diện",
        "CAMERA_HEAD_CONFIRMATION_ENABLED": "Gật / lắc đầu xác nhận",
        "CAMERA_RETURN_ENABLED": "Chào khi webcam thấy người quay lại",
        "CAMERA_EMOTION_ENABLED": "Nhận diện biểu cảm (thử nghiệm)",
    },
    "Thiết bị trong phòng": {
        "IOT_ENABLED": "Đọc và điều khiển thiết bị IoT",
        "IOT_COMMANDS_ENABLED": "Cho phép gửi lệnh máy lạnh",
        "IOT_AUTOMATION_ENABLED": "Tự bật máy lạnh theo nhiệt độ",
        "IOT_VOICE_ALERTS_ENABLED": "Thông báo nhiệt độ bằng giọng nói",
    },
}

FEATURE_LABELS = {
    "system": "Ứng dụng, âm thanh và quản trị máy",
    "web": "Tra cứu web và mở nội dung",
    "weather": "Thời tiết",
    "schedule": "Lịch nhắc và lịch hành động",
    "browser": "Công cụ điều khiển trình duyệt",
    "screen": "Công cụ đọc và điều khiển màn hình",
    "profile": "Công cụ hồ sơ, trí nhớ và thói quen",
    "task": "Công việc và routine",
    "pim": "Danh bạ, lịch cá nhân và email",
    "place": "Tìm và nghiên cứu địa điểm",
    "activity": "Thống kê hoạt động",
    "iot": "Công cụ môi trường và máy lạnh",
    "camera": "Công cụ webcam",
}

LIVE = {"DEBUG_PANEL_ENABLED", "CAMERA_ENABLED", "CAMERA_FACE_ENABLED", "CAMERA_GESTURE_ENABLED",
        "CAMERA_HEAD_CONFIRMATION_ENABLED", "CAMERA_EMOTION_ENABLED",
        "IOT_ENABLED", "IOT_COMMANDS_ENABLED", "IOT_AUTOMATION_ENABLED",
        "IOT_VOICE_ALERTS_ENABLED", "FAST_COMMANDS"}


def validate_threshold(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 16 <= value <= 50:
        raise ValueError("Ngưỡng nhiệt độ phải từ 16 đến 50 °C")
    return float(value)


class SystemControls:
    def __init__(self, report, camera=None, store=controls, apply_live=None, iot=None):
        from features.catalog import FEATURES
        from features.iot.settings import settings
        self.store, self.camera, self.apply_live = store, camera, apply_live
        self.features = FEATURES
        self.available = {f.name for f in report.loaded}
        self.skipped = dict(report.skipped)
        self.defaults = {key: bool(getattr(config, key, False))
                         for group in FLAG_GROUPS.values() for key in group}
        self.defaults.update(IOT_COMMANDS_ENABLED=settings.commands_enabled,
                             IOT_AUTOMATION_ENABLED=settings.automation_enabled)
        self.boot = {key: store.get(key, value) for key, value in self.defaults.items()}
        self._session_debug = self.defaults["DEBUG_PANEL_ENABLED"]
        self.defaults["IOT_AUTO_ON_TEMPERATURE_C"] = settings.auto_on_temperature_c
        self.iot = iot
        self._gateway = None
        self._gateway_error = None
        self._gateway_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self.iot is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._poll_gateway, name="control-status", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=4)

    def _poll_gateway(self):
        while not self._stop.is_set():
            try:
                snapshot = self.iot.status()
                error = None
            except Exception as exc:
                snapshot, error = None, str(exc)
            with self._gateway_lock:
                self._gateway, self._gateway_error = snapshot, error
            self._stop.wait(2)

    def snapshot(self):
        rows = []
        values = self.store.values()
        for section, flags in FLAG_GROUPS.items():
            for key, label in flags.items():
                enabled = (self._session_debug if key == "DEBUG_PANEL_ENABLED" else
                           values.get(key, self.defaults[key]))
                pending = key not in LIVE and enabled != self.boot[key]
                rows.append({"key": key, "label": label, "section": section,
                             "enabled": bool(enabled), "pending": pending,
                             "mode": ("Chỉ phiên này" if key == "DEBUG_PANEL_ENABLED" else
                                      "Áp dụng ngay" if key in LIVE else
                                      "Áp dụng khi khởi động lại")})
        for feature in self.features:
            rows.append({"key": "feature." + feature.name,
                         "label": FEATURE_LABELS.get(feature.name, feature.name),
                         "section": "Nhóm công cụ", "enabled": values.get("feature." + feature.name, True),
                         "pending": False, "mode": "Áp dụng ngay",
                         "unavailable": self.skipped.get(feature.name)})
        camera = self.camera.status() if self.camera is not None else None
        camera_diagnostics = {}
        if camera:
            for name in ("gesture", "emotion"):
                reader = getattr(self.camera, name + "_status", None)
                if reader:
                    camera_diagnostics[name] = reader()
            # Show what the device is doing, even after a voice privacy command.
            for row in rows:
                if row["key"] == "CAMERA_ENABLED":
                    row["enabled"] = not camera["paused"] and camera["state"] not in ("stopped", "unavailable", "error")
                elif row["key"] == "CAMERA_FACE_ENABLED":
                    row["enabled"] = camera["face_auth"]["enabled"]
                elif row["key"] == "CAMERA_HEAD_CONFIRMATION_ENABLED":
                    row["enabled"] = camera.get("head_confirmation_enabled", row["enabled"])
                elif row["key"] == "CAMERA_GESTURE_ENABLED" and "gesture" in camera_diagnostics:
                    row["enabled"] = camera_diagnostics["gesture"]["enabled"]
                elif row["key"] == "CAMERA_EMOTION_ENABLED" and "emotion" in camera_diagnostics:
                    row["enabled"] = camera_diagnostics["emotion"]["enabled"]
        with self._gateway_lock:
            gateway, gateway_error = self._gateway, self._gateway_error
        return {"rows": rows, "threshold": values.get("IOT_AUTO_ON_TEMPERATURE_C", self.defaults["IOT_AUTO_ON_TEMPERATURE_C"]),
                "restart_required": any(row["pending"] for row in rows), "camera": camera,
                "camera_diagnostics": camera_diagnostics,
                "gateway": gateway, "gateway_error": gateway_error}

    def set(self, key, enabled):
        known = key in {k for flags in FLAG_GROUPS.values() for k in flags} or key in {"feature." + f.name for f in self.features}
        if not known or type(enabled) is not bool:
            raise ValueError("Công tắc không hợp lệ")
        if key == "DEBUG_PANEL_ENABLED":
            if self.apply_live:
                self.apply_live(key, enabled)
            self._session_debug = enabled
            config.DEBUG_PANEL_ENABLED = enabled
            return self.snapshot()
        live = key in LIVE or key.startswith("feature.")
        previous = self.store.get(key, self.defaults.get(key, True))
        if live and self.apply_live:
            self.apply_live(key, enabled)
        try:
            self.store.update({key: enabled})
        except Exception:
            if live and self.apply_live:
                self.apply_live(key, previous)
            raise
        if key in LIVE and hasattr(config, key):
            setattr(config, key, enabled)
        return self.snapshot()

    def set_threshold(self, value):
        self.store.update({"IOT_AUTO_ON_TEMPERATURE_C": validate_threshold(value)})
        return self.snapshot()

    def face_action(self, action):
        if self.camera is None:
            raise RuntimeError("Webcam chưa sẵn sàng")
        if action == "enroll":
            self.camera.begin_enrollment()
            self.store.update({"CAMERA_FACE_ENABLED": True})
        elif action == "cancel_enroll":
            self.camera.cancel_enrollment()
        elif action == "delete_face":
            self.camera.delete_template()
            self.store.update({"CAMERA_FACE_ENABLED": False})
        elif action == "calibrate":
            self.camera.calibrate_proximity()
        else:
            raise ValueError("Thao tác webcam không hợp lệ")
        return self.snapshot()
