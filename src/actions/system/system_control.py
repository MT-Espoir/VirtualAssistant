import os


def _co_initialize():
    """Khởi tạo COM cho thread hiện tại (pycaw/WMI cần khi chạy ở thread nền).

    KHÔNG gọi CoUninitialize: vòng agent chạy suốt phiên nên giữ COM sống; uninit
    trong khi COM object còn tham chiếu sẽ gây lỗi 'releasing IUnknown'. Gọi lặp
    lại vô hại (idempotent trên cùng thread).
    """
    if os.name != 'nt':
        return
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass


def control_volume(level=None, change=None):
    """Điều chỉnh âm lượng hệ thống (Windows).

    Args:
        level: Mức âm lượng tuyệt đối (0-100).
        change: Thay đổi tương đối (vd 10 hoặc -15).
    """
    if os.name != 'nt':
        return "Chỉ hỗ trợ điều khiển âm lượng trên Windows."
    _co_initialize()
    try:
        # pycaw mới (>=2025): GetSpeakers() trả AudioDevice có sẵn .EndpointVolume
        # (không cần .Activate/cast như bản cũ).
        from pycaw.pycaw import AudioUtilities
        endpoint = AudioUtilities.GetSpeakers().EndpointVolume

        if level is not None:
            lv = max(0, min(100, int(round(level))))
            endpoint.SetMasterVolumeLevelScalar(lv / 100.0, None)
            return f"Đã đặt âm lượng {lv}%."
        if change is not None:
            current = endpoint.GetMasterVolumeLevelScalar() * 100
            lv = max(0, min(100, int(round(current + change))))
            endpoint.SetMasterVolumeLevelScalar(lv / 100.0, None)
            return f"Đã chỉnh âm lượng về {lv}%."

        current = int(round(endpoint.GetMasterVolumeLevelScalar() * 100))
        return f"Âm lượng hiện tại {current}%."
    except Exception as e:
        return f"Không điều khiển được âm lượng: {e}"


def control_brightness(level=None, change=None):
    """Điều chỉnh độ sáng màn hình (Windows)."""
    if os.name != 'nt':
        return "Chỉ hỗ trợ điều khiển độ sáng trên Windows."
    _co_initialize()
    try:
        import screen_brightness_control as sbc

        if level is not None:
            lv = max(0, min(100, int(round(level))))
            sbc.set_brightness(lv)
            return f"Đã đặt độ sáng {lv}%."
        if change is not None:
            current = sbc.get_brightness()[0]
            lv = max(0, min(100, int(round(current + change))))
            sbc.set_brightness(lv)
            return f"Đã chỉnh độ sáng về {lv}%."

        current = sbc.get_brightness()[0]
        return f"Độ sáng hiện tại {current}%."
    except Exception as e:
        return f"Không điều khiển được độ sáng: {e}"

# Đã gỡ hoàn toàn tính năng tắt/khởi động lại máy (system_shutdown/system_restart)
# và các helper close_all_applications/get_running_applications: quá rủi ro khi STT
# nghe nhầm (từng làm máy bị cưỡng chế reset). Cố ý không cung cấp cho agent.