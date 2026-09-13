import os
import threading

from utils.logger import get_logger

logger = get_logger(__name__)


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


def read_brightness():
    """Độ sáng hiện tại (0-100) hoặc None nếu không đọc được.

    Trả SỐ chứ không phải câu, khác `control_brightness()` ngay dưới: đường tự động cần so
    sánh để quyết định có hạ sáng không (`services/proactive.py`), và bóc số ra từ một câu
    tiếng Việt là thứ sẽ hỏng lặng lẽ khi câu đó đổi chữ.
    """
    if os.name != 'nt':
        return None
    _co_initialize()
    try:
        import screen_brightness_control as sbc
        return int(sbc.get_brightness()[0])
    except Exception as e:
        logger.debug("Không đọc được độ sáng: %s", e)
        return None


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

# --------------------------------- nguồn máy ---------------------------------------- #
#
# LỊCH SỬ, đọc trước khi sửa: tính năng tắt/khởi động lại máy từng tồn tại
# (`system_shutdown`/`system_restart`), ĐÃ LÀM HỎNG THẬT — STT nghe nhầm và máy bị cưỡng
# chế reset — nên bị gỡ sạch khỏi agent. Nay nối lại, và điều duy nhất biện minh cho việc
# đó là hình dạng của hàm dưới đây đã khác hẳn bản cũ:
#
#   1. `shutdown`/`restart` LUÔN đi qua `/t` (hẹn giờ), không bao giờ chạy ngay. Cửa sổ huỷ
#      là thứ bản cũ không có — nghe nhầm lúc đó là mất máy tức thì, còn giờ là một câu
#      "huỷ đi". Đây chính là mẹo §5.3 dùng cho đường tự động: biến hành động khó hoàn tác
#      thành hành động hoàn tác được, thay vì cố ngăn nó xảy ra.
#   2. TUYỆT ĐỐI không có `/f`. Thiếu nó thì Windows còn cho ứng dụng cơ hội lưu file.
#   3. `signout` bị bỏ khỏi bộ lệnh: `shutdown /l` KHÔNG nhận `/t`, tức là không có cửa sổ
#      huỷ, mà nó vẫn đóng sạch ứng dụng. Không đạt điều kiện (1) nên không có mặt.
#
# Hai lớp nữa nằm ngoài file này: cờ `admin` (từ chối khi lượt đã đọc nội dung web) và
# `Tool.cam` (cấm cứng lúc Windows đang cài cập nhật). Xem `docs/system_admin_spec.md`
# §4b, §7.


# Tối thiểu một phút: đủ để nghe câu "sẽ tắt máy sau một phút" rồi kịp bảo huỷ. Ngắn hơn
# thì cửa sổ huỷ chỉ có trên giấy.
PHUT_CHO_TOI_THIEU = 1

_LENH_SHUTDOWN = {"shutdown": "/s", "restart": "/r"}


def _chay_shutdown(*args):
    """Gọi `shutdown.exe` không cho hiện cửa sổ console (app này chạy có avatar GUI)."""
    import subprocess
    co = {"creationflags": 0x08000000} if os.name == 'nt' else {}   # CREATE_NO_WINDOW
    return subprocess.run(["shutdown", *args], capture_output=True, **co)


def control_power(action=None, delay_minutes=None):
    """Điều khiển nguồn máy: lock | sleep | restart | shutdown | cancel."""
    if os.name != 'nt':
        return "Chỉ hỗ trợ điều khiển nguồn trên Windows."
    act = (action or "").strip().lower()
    try:
        if act == "lock":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return "Đã khoá màn hình."
        if act == "sleep":
            import ctypes
            ctypes.windll.powrprof.SetSuspendState(0, 0, 0)
            return "Đã cho máy ngủ."
        if act == "cancel":
            if _chay_shutdown("/a").returncode == 0:
                return "Đã huỷ lệnh tắt máy."
            return "Không có lệnh tắt máy nào đang hẹn."
        if act in _LENH_SHUTDOWN:
            try:
                phut = max(PHUT_CHO_TOI_THIEU, int(delay_minutes))
            except (TypeError, ValueError):
                phut = PHUT_CHO_TOI_THIEU
            ket_qua = _chay_shutdown(_LENH_SHUTDOWN[act], "/t", str(phut * 60))
            viec = "tắt máy" if act == "shutdown" else "khởi động lại"
            if getattr(ket_qua, "returncode", 1) != 0:
                logger.warning("shutdown.exe không hẹn được %s (mã %s)", act,
                               getattr(ket_qua, "returncode", "?"))
                return f"Không hẹn được lệnh {viec}; Windows đã từ chối yêu cầu."
            return f"Sẽ {viec} sau {phut} phút. Đổi ý thì bảo tôi huỷ."
        return f"Không hiểu lệnh nguồn '{action}'."
    except Exception as e:
        return f"Không điều khiển được nguồn máy: {e}"


# ------------------------------ chống ngủ (keep awake) ------------------------------- #
#
# `SetThreadExecutionState` gắn cờ vào THREAD gọi nó, không vào tiến trình. Đặt cờ ở thread
# này rồi gỡ ở thread khác là KHÔNG GỠ ĐƯỢC GÌ CẢ — và cái sai đó im lặng tuyệt đối: hàm
# vẫn trả về thành công, máy vẫn không ngủ, không log nào. Nên cả việc giữ lẫn việc hẹn giờ
# tự thôi đều phải nằm trên MỘT thread riêng sống suốt thời gian giữ.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_giu_thuc = {"thread": None, "stop": None, "errors": None}
_giu_thuc_lock = threading.Lock()


def _vong_giu_thuc(stop, giay, ready=None, errors=None):
    import ctypes
    k32 = ctypes.windll.kernel32
    try:
        ket_qua = k32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        if not ket_qua:
            raise OSError("SetThreadExecutionState trả về 0")
    except Exception as e:
        if errors is None:
            raise
        errors.append(e)
        return
    finally:
        if ready is not None:
            ready.set()
    try:
        stop.wait(giay)          # giay=None -> chờ tới khi có người bảo thôi
    finally:
        if not k32.SetThreadExecutionState(ES_CONTINUOUS):
            error = OSError("Windows không xác nhận đã gỡ trạng thái giữ máy thức")
            if errors is not None:
                errors.append(error)
            logger.warning("%s", error)


def keep_awake(on=True, minutes=None):
    """Giữ máy không ngủ / thôi giữ. `minutes` = tự thôi sau ngần ấy phút."""
    if os.name != 'nt':
        return "Chỉ hỗ trợ chống ngủ trên Windows."
    with _giu_thuc_lock:
        cu = _giu_thuc.get("stop")
        thread_cu = _giu_thuc.get("thread")
        loi_cu = _giu_thuc.get("errors")
        if cu is not None:
            cu.set()             # luôn dừng lượt giữ cũ trước, tránh chồng hai thread
            if thread_cu is not None:
                thread_cu.join(timeout=1)
                if thread_cu.is_alive():
                    return "Chưa dừng được lượt giữ máy thức trước, nên tôi không mở lượt mới."
            _giu_thuc.update(stop=None, thread=None, errors=None)
            if loi_cu:
                return "Windows không xác nhận đã thôi giữ máy thức."
        if not on:
            return "Đã thôi giữ máy thức, máy ngủ bình thường trở lại."
        try:
            giay = max(1, int(minutes)) * 60 if minutes else None
        except (TypeError, ValueError):
            giay = None
        stop = threading.Event()
        ready = threading.Event()
        errors = []
        t = threading.Thread(target=_vong_giu_thuc,
                             args=(stop, giay, ready, errors), daemon=True)
        t.start()
        if not ready.wait(2):
            stop.set()
            return "Windows không phản hồi khi bật chế độ giữ máy thức."
        if errors:
            logger.warning("Không bật được chế độ giữ máy thức: %s", errors[0])
            return "Không bật được chế độ giữ máy thức trên Windows."
        _giu_thuc.update(stop=stop, thread=t, errors=errors)
        return ("Đã giữ máy thức trong %d phút." % (giay // 60) if giay
                else "Đã giữ máy thức tới khi bạn bảo thôi.")


# ------------------------------- thiết bị âm thanh ----------------------------------- #

def _thiet_bi_ra():
    """Thiết bị ĐẦU RA đang hoạt động. Máy này có 32 thiết bị mà chỉ 2 cái Active — lọc là
    bắt buộc, danh sách 32 dòng toàn tai nghe đã tháo thì vô dụng ở cả giọng lẫn panel."""
    from pycaw.constants import AudioDeviceState
    from pycaw.pycaw import AudioUtilities
    ra = []
    for d in AudioUtilities.GetAllDevices():
        try:
            if d.state != AudioDeviceState.Active:
                continue
            if AudioUtilities.GetEndpointDataFlow(d.id) != "eRender":
                continue
            ra.append(d)
        except Exception:          # một thiết bị đọc lỗi không được làm hỏng cả danh sách
            continue
    return ra


def audio_device_report(action="list", name=None):
    """Trả ``(câu tóm tắt, toàn bộ thiết bị)`` và thực hiện đổi nếu được yêu cầu.

    Danh sách có cấu trúc dành cho HUD; câu đầu giữ ngắn để đọc bằng giọng. Hai phần dùng
    chung một lần liệt kê COM để không chậm gấp đôi và không lệch nhau khi thiết bị đổi.
    """
    if os.name != 'nt':
        return "Chỉ hỗ trợ đổi thiết bị âm thanh trên Windows.", []
    _co_initialize()
    try:
        import warnings
        from pycaw.pycaw import AudioUtilities
        with warnings.catch_warnings():
            # pycaw cảnh báo COMError khi đọc thuộc tính của thiết bị đã tháo — bình thường
            # với 30 thiết bị NotPresent, và ta lọc chúng đi ngay sau đó.
            warnings.simplefilter("ignore")
            ds = _thiet_bi_ra()
            if not ds:
                return "Không thấy thiết bị phát âm thanh nào đang hoạt động.", []
            rows = [{"name": d.FriendlyName, "selected": False} for d in ds]
            if (action or "list").strip().lower() != "switch":
                return "Thiết bị phát: " + "; ".join(d.FriendlyName for d in ds) + ".", rows

            from utils.text_norm import norm
            can = norm(name or "")
            if not can:
                return "Bạn muốn chuyển sang thiết bị nào?", rows
            khop = [d for d in ds if can in norm(d.FriendlyName)]
            if not khop:
                return (("Không thấy thiết bị nào tên giống '%s'. Đang có: %s."
                         % (name, "; ".join(d.FriendlyName for d in ds))), rows)
            AudioUtilities.SetDefaultDevice(khop[0].id)
            for row, device in zip(rows, ds):
                row["selected"] = device.id == khop[0].id
            return "Đã chuyển âm thanh sang %s." % khop[0].FriendlyName, rows
    except Exception as e:
        return f"Không đổi được thiết bị âm thanh: {e}", []


def audio_device(action="list", name=None):
    """Thiết bị phát âm thanh: `list` để xem, `switch` để đổi cái mặc định."""
    return audio_device_report(action=action, name=name)[0]


# --------------------------------- kết thúc tiến trình -------------------------------- #
#
# Tiến trình hệ thống LÕI: kết thúc bất kỳ cái nào trong đây gây BSOD ngay
# (`CRITICAL_PROCESS_DIED`). Đây là danh sách cấm CỨNG — người dùng đồng ý cũng không chạy,
# và nó được xét ở `ToolRegistry.tu_choi()` qua `Tool.cam`, không phải trong hàm này.
# Giữ ĐÚNG danh sách của `docs/system_admin_spec.md` §7 lớp 3: cấm mơ hồ theo cảm giác nguy
# hiểm thì vừa chặn nhầm vừa bỏ sót.
TIEN_TRINH_CAM = ("csrss.exe", "wininit.exe", "services.exe", "lsass.exe", "smss.exe")


def ten_tien_trinh(name_or_pid):
    """Tên tiến trình suy từ tên HOẶC pid, viết thường. None nếu không tra được.

    Lệnh cấm cần TÊN, mà người dùng có thể đưa pid — không quy về một dạng thì cấm theo tên
    sẽ bị vòng qua chỉ bằng cách nói số.
    """
    import psutil
    s = str(name_or_pid or "").strip()
    if not s:
        return None
    if s.isdigit():
        try:
            return psutil.Process(int(s)).name().lower()
        except Exception:
            return None
    return s.lower() if s.lower().endswith(".exe") else s.lower() + ".exe"


def kill_process(name_or_pid=None):
    """Kết thúc tiến trình theo tên hoặc pid. Cùng tên thì kết thúc HẾT."""
    import psutil
    s = str(name_or_pid or "").strip()
    if not s:
        return "Bạn muốn tắt tiến trình nào?"
    if s.isdigit():
        try:
            p = psutil.Process(int(s))
            ten = p.name()
            p.terminate()
            return f"Đã tắt {ten} (pid {s})."
        except psutil.NoSuchProcess:
            return f"Không có tiến trình nào mang pid {s}."
        except psutil.AccessDenied:
            return f"Không đủ quyền tắt tiến trình pid {s}."
        except Exception as e:
            return f"Không tắt được tiến trình pid {s}: {e}"

    can = ten_tien_trinh(s)
    xong, tu_choi = 0, 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info.get("name") or "").lower() != can:
                continue
            p.terminate()
            xong += 1
        except psutil.AccessDenied:
            tu_choi += 1
        except Exception:
            continue
    if xong:
        # Chrome chạy hai chục tiến trình cùng tên: nói số để người dùng biết đã tắt cả cụm
        # chứ không phải một cái lẻ.
        return f"Đã tắt {xong} tiến trình {can}." if xong > 1 else f"Đã tắt {can}."
    if tu_choi:
        return f"Không đủ quyền tắt {can}."
    return f"Không thấy tiến trình nào tên {can} đang chạy."
