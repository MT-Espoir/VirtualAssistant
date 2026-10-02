"""Main HUD control panel; camera enrollment is integrated here."""

import time
from tkinter import messagebox, simpledialog


def control_blocks(snapshot, section="Thiết bị trong phòng"):
    sections = list(dict.fromkeys(row["section"] for row in snapshot["rows"]))
    labels = {"Hoạt động và chăm sóc": "Chăm sóc", "Giọng nói và trí nhớ": "Giọng & nhớ",
              "Thiết bị trong phòng": "IoT", "Nhóm công cụ": "Công cụ"}
    blocks = [("body", "Lựa chọn được lưu tự động, trừ chế độ debug chỉ áp dụng cho phiên này. Dùng các mục bên dưới để chuyển nhóm chức năng.")]
    for start in range(0, len(sections), 2):
        blocks.append(("buttons", [(labels.get(name, name), {"section": name}, "go" if name == section else "off")
                                    for name in sections[start:start + 2]]))
    if snapshot["restart_required"]:
        blocks.extend((("badge", "Có thay đổi đang chờ khởi động lại", "warn"),
                       ("buttons", [("KHỞI ĐỘNG LẠI TRỢ LÝ", {"action": "restart"}, "go")])) )
    blocks.append(("header", section))
    for row in snapshot["rows"]:
        if row["section"] != section:
            continue
        detail = "Đang chờ khởi động lại" if row["pending"] else row["mode"]
        if row.get("unavailable"):
            detail = "Chưa sẵn sàng: " + row["unavailable"] + ". Bật dịch vụ liên quan rồi khởi động lại."
        blocks.append(("toggle", row["label"], row["enabled"],
                       {"key": row["key"], "enabled": not row["enabled"]}, detail))
    if section == "Thiết bị trong phòng":
        gateway = snapshot.get("gateway")
        if snapshot.get("gateway_error"):
            blocks.append(("badge", "Chưa kết nối được gateway. Lựa chọn đã lưu sẽ áp dụng khi gateway chạy.", "warn"))
        elif gateway and not gateway.get("policy"):
            blocks.append(("badge", "Gateway cần khởi động lại để nạp phiên bản hỗ trợ bảng điều khiển.", "warn"))
        elif gateway:
            blocks.append(("field", "MQTT", "Đã kết nối" if gateway["broker_connected"] else "Mất kết nối"))
        blocks.extend((("field", "Ngưỡng", f"{snapshot['threshold']:g} °C"),
                       ("body", "Tự bật khi các mẫu gửi mỗi 5 phút đều trên ngưỡng trong 20 phút và webcam thấy người trong phòng. Chạy một giờ; thời gian chờ hai giờ, tắt bằng lời chặn tự bật sáu giờ."),
                       ("buttons", [("ĐỔI NGƯỠNG NHIỆT ĐỘ", {"action": "threshold"}, "go")])))
        if gateway and gateway.get("policy"):
            blocks.append(("field", "Tự bật", "Đang bật" if gateway["policy"]["automation_enabled"] else "Đang tắt"))
            for room in gateway.get("rooms", []):
                state = room.get("automation", {})
                from datetime import datetime
                for key, label in (("cooldown_until", "Chờ đến"), ("run_until", "Tắt lúc"),
                                   ("manual_lockout_until", "Khóa đến")):
                    if state.get(key):
                        until = datetime.fromisoformat(state[key]).astimezone()
                        if until > datetime.now().astimezone():
                            blocks.append(("field", label, until.strftime("%H:%M %d/%m")))
    camera = snapshot.get("camera")
    if section == "Webcam" and camera:
        face = camera["face_auth"]
        blocks.extend((("field", "Webcam", camera["state"]),
                       ("field", "Người", "Có người" if camera["present"] else "Chưa thấy người"),
                       ("field", "Gợi ý", face["state"]),
                       ("field", "Template", "Đã đăng ký" if face["enrolled"] else "Chưa đăng ký")))
        if face.get("suggestion"):
            blocks.append(("field", "Khớp", {"matched": "Khớp mẫu đã đăng ký",
                                                 "not_matched": "Chưa khớp mẫu",
                                                 "unknown": "Chưa xác định"}.get(face["suggestion"], "Chưa xác định")))
        if face["state"] == "enrolling":
            blocks.extend((("field", "Mẫu", f"{face['samples']}/5"),
                           ("body", "Nhìn thẳng webcam, đủ sáng, chỉ một khuôn mặt trong khung."),
                           ("buttons", [("HỦY ĐĂNG KÝ", {"action": "cancel_enroll"}, "off")])))
        else:
            blocks.append(("buttons", [("ĐĂNG KÝ KHUÔN MẶT", {"action": "enroll"}, "go")]))
        if face["enrolled"]:
            blocks.append(("buttons", [("XÓA TEMPLATE", {"action": "delete_face"}, "off")]))
        blocks.append(("buttons", [("HIỆU CHỈNH VỊ TRÍ NGỒI", {"action": "calibrate"}, "off")]))
        if face.get("error"):
            blocks.append(("body", face["error"]))
        for name, detail in snapshot.get("camera_diagnostics", {}).items():
            label = "Cử chỉ tay" if name == "gesture" else "Biểu cảm"
            if detail.get("error"):
                blocks.append(("body", label + ": " + str(detail["error"])))
        blocks.append(("body", "Gợi ý khớp khuôn mặt chỉ là tiện ích, không thay đổi quyền truy cập."))
    return blocks


class ControlPanelHost:
    def _show_control(self, action="show"):
        panel = self._panels.get("control")
        if action == "hide":
            if panel:
                panel.hide()
            return
        if self.system_controls is None:
            return
        self._control_signature = None
        self._control_refresh(force=True)

    def _control_refresh(self, force=False):
        if self.system_controls is None:
            return
        panel = self._panels.get("control")
        if not force and (panel is None or not panel._visible or
                          time.monotonic() - self._control_checked_at < 1):
            return
        self._control_checked_at = time.monotonic()
        try:
            snapshot = self.system_controls.snapshot()
            blocks = control_blocks(snapshot, self._control_section)
            if not force and blocks == self._control_signature:
                return
            self._control_signature = blocks
            panel = self._panel("control", "BẢNG ĐIỀU KHIỂN", self._control_pick)
            position = panel.inner.yview()[0] if panel.inner is not None else 0
            panel.show(blocks)
            if panel.inner is not None:
                panel.inner.yview_moveto(position)
        except Exception as exc:
            if force:
                messagebox.showerror("Bảng điều khiển", str(exc), parent=self.root)

    def _control_pick(self, request):
        if not isinstance(request, dict):
            return
        try:
            if "section" in request:
                self._control_section = request["section"]
                panel = self._panels.get("control")
                if panel and panel.inner:
                    panel.inner.yview_moveto(0)
            elif "key" in request:
                self.system_controls.set(request["key"], request["enabled"])
            else:
                action = request.get("action")
                if action == "restart":
                    if self.on_restart:
                        self.on_restart()
                    return
                if action == "threshold":
                    value = simpledialog.askstring(
                        "Ngưỡng tự bật máy lạnh", "Nhiệt độ từ 16 đến 50 °C:",
                        initialvalue=str(self.system_controls.snapshot()["threshold"]), parent=self.root)
                    if value is not None:
                        self.system_controls.set_threshold(float(value.replace(",", ".")))
                elif action == "enroll":
                    if messagebox.askyesno("Đăng ký khuôn mặt",
                                           "Lưu 5 mẫu đặc trưng được mã hóa trên máy này, không lưu ảnh. Tiếp tục?", parent=self.root):
                        self.system_controls.face_action(action)
                elif action == "delete_face":
                    if messagebox.askyesno("Xóa template", "Xóa mẫu khuôn mặt đã đăng ký?", parent=self.root):
                        self.system_controls.face_action(action)
                else:
                    self.system_controls.face_action(action)
        except Exception as exc:
            messagebox.showerror("Bảng điều khiển", str(exc), parent=self.root)
        self._control_refresh(force=True)
