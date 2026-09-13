"""
Ba tool Tầng 1 còn lại: `kill_process`, `keep_awake`, `audio_device`.

`docs/system_admin_spec.md` §4, §7 lớp 3, §8. Trọng tâm giống `test_power_tools.py`: phần
lớn test ở đây kiểm "hỏng có chặn được không", không kiểm "chạy có đúng không".
"""

from conftest import registry_with

import sys
import types
from unittest.mock import MagicMock

import pytest

from agent.tools import ActionRefused, NeedsConfirmation


class ActionsStub:
    def __init__(self):
        self.goi = []

    def kill_process(self, name_or_pid=None):
        self.goi.append(("kill", name_or_pid))
        return "giả lập kill"

    def keep_awake(self, on=True, minutes=None):
        self.goi.append(("awake", on, minutes))
        return "giả lập awake"

    def audio_device(self, action="list", name=None):
        self.goi.append(("audio", action, name))
        return "giả lập audio"


def _reg():
    acts = ActionsStub()
    return registry_with(actions=acts), acts


# --------------------- cấm cứng: tiến trình lõi của Windows ------------------------- #

def test_cam_giet_tien_trinh_loi_du_nguoi_dung_dong_y():
    """§7 lớp 3. Kết thúc `csrss`/`lsass`/... là BSOD ngay (`CRITICAL_PROCESS_DIED`) —
    đây là ca hỏng thật, nên `confirmed=True` cũng không mở được."""
    reg, acts = _reg()
    for ten in ("csrss.exe", "lsass.exe", "wininit.exe", "services.exe", "smss.exe"):
        with pytest.raises(ActionRefused) as e:
            reg.run("kill_process", {"name_or_pid": ten}, confirmed=True)
        assert "sập xanh" in e.value.ly_do
    assert acts.goi == []


def test_cam_khong_vong_qua_duoc_bang_cach_bo_duoi_exe():
    reg, _ = _reg()
    with pytest.raises(ActionRefused):
        reg.run("kill_process", {"name_or_pid": "csrss"}, confirmed=True)
    with pytest.raises(ActionRefused):
        reg.run("kill_process", {"name_or_pid": "  CSRSS.EXE  "}, confirmed=True)


def test_cam_khong_vong_qua_duoc_bang_cach_noi_pid():
    """Lệnh cấm so theo TÊN; người dùng (hoặc trang web mớm lời) có thể nói PID. Không quy
    pid về tên thì cấm bị vòng qua chỉ bằng cách đọc một con số."""
    from actions.system import system_control

    goc = sys.modules.get("psutil")
    gia = types.ModuleType("psutil")
    gia.Process = lambda pid: types.SimpleNamespace(name=lambda: "lsass.exe")
    sys.modules["psutil"] = gia
    try:
        assert system_control.ten_tien_trinh("742") == "lsass.exe"
        reg, acts = _reg()
        with pytest.raises(ActionRefused):
            reg.run("kill_process", {"name_or_pid": "742"}, confirmed=True)
        assert acts.goi == []
    finally:
        if goc is not None:
            sys.modules["psutil"] = goc
        else:
            del sys.modules["psutil"]


def test_tien_trinh_thuong_van_giet_duoc_nhung_phai_xac_nhan():
    reg, acts = _reg()
    with pytest.raises(NeedsConfirmation):
        reg.run("kill_process", {"name_or_pid": "chrome.exe"})
    assert acts.goi == []
    assert reg.run("kill_process", {"name_or_pid": "chrome.exe"}, confirmed=True)
    assert acts.goi == [("kill", "chrome.exe")]


def test_kill_bi_chan_o_luot_nhiem_va_duong_tu_dong():
    """Trang web mớm "tắt tiến trình X" -> từ chối thẳng. Và máy không bao giờ tự làm."""
    reg, acts = _reg()
    with pytest.raises(ActionRefused):
        reg.run("kill_process", {"name_or_pid": "chrome.exe"}, nhiem=True)
    with pytest.raises(ActionRefused):
        reg.run("kill_process", {"name_or_pid": "chrome.exe"}, tu_dong=True)
    assert acts.goi == []


def test_danh_sach_cam_dung_y_spec():
    """Ghim danh sách lại: §7 dặn phải liệt kê ĐÚNG cái gì thay vì cấm mơ hồ theo cảm giác
    nguy hiểm — cấm rộng thì chặn nhầm, cấm hẹp thì bỏ sót."""
    from actions.system.system_control import TIEN_TRINH_CAM
    assert set(TIEN_TRINH_CAM) == {"csrss.exe", "wininit.exe", "services.exe",
                                   "lsass.exe", "smss.exe"}


# ------------------------------- keep_awake ----------------------------------------- #

def test_keep_awake_khong_can_xac_nhan():
    """Hoàn tác bằng một câu ("thôi giữ"), nên bắt xác nhận chỉ làm phiền."""
    reg, acts = _reg()
    assert reg.run("keep_awake", {"on": True, "minutes": 30})
    assert acts.goi == [("awake", True, 30)]


def test_giu_thuc_chay_tren_MOT_thread_rieng():
    """`SetThreadExecutionState` gắn cờ vào THREAD gọi nó. Đặt ở thread này rồi gỡ ở thread
    khác là không gỡ được gì — và cái sai đó im lặng tuyệt đối. Nên việc giữ lẫn việc tự
    thôi phải nằm trên cùng một thread."""
    from actions.system import system_control

    dat = []
    gia_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(kernel32=types.SimpleNamespace(
            SetThreadExecutionState=lambda co: dat.append(co) or 1)))
    goc_os, goc_ct = system_control.os, sys.modules.get("ctypes")
    system_control.os = types.SimpleNamespace(name="nt")
    sys.modules["ctypes"] = gia_ctypes
    try:
        import threading
        stop = threading.Event()
        t = threading.Thread(target=system_control._vong_giu_thuc, args=(stop, None))
        t.start()
        stop.set()
        t.join(2)
        # đúng hai lần gọi, CÙNG một thread: bật cờ rồi gỡ cờ
        assert len(dat) == 2
        assert dat[0] == (system_control.ES_CONTINUOUS
                          | system_control.ES_SYSTEM_REQUIRED
                          | system_control.ES_DISPLAY_REQUIRED)
        assert dat[1] == system_control.ES_CONTINUOUS
    finally:
        system_control.os = goc_os
        if goc_ct is not None:
            sys.modules["ctypes"] = goc_ct


def test_bat_lai_thi_dung_luot_giu_cu_truoc():
    """Hai thread cùng giữ thì cái sau không gỡ được cờ của cái trước -> máy không bao giờ
    ngủ lại. Phải luôn dừng lượt cũ trước khi mở lượt mới."""
    from actions.system import system_control

    goc_os = system_control.os
    goc_vong = system_control._vong_giu_thuc
    system_control.os = types.SimpleNamespace(name="nt")
    trang_thai_cu = dict(system_control._giu_thuc)
    try:
        goi = []
        def fake_vong(stop, giay, ready=None, errors=None):
            goi.append(giay)
            if ready is not None:
                ready.set()
            stop.wait(5)

        system_control._vong_giu_thuc = fake_vong
        system_control.keep_awake(True, 10)
        stop1 = system_control._giu_thuc["stop"]
        system_control.keep_awake(True, 20)
        assert stop1.is_set()                       # lượt cũ đã bị bảo dừng
        assert system_control._giu_thuc["stop"] is not stop1
        system_control.keep_awake(False)
        assert system_control._giu_thuc["stop"] is None
    finally:
        system_control.os = goc_os
        system_control._vong_giu_thuc = goc_vong
        system_control._giu_thuc.update(trang_thai_cu)


def test_windows_tu_choi_giu_thuc_thi_khong_bao_thanh_cong():
    from actions.system import system_control

    fake_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(kernel32=types.SimpleNamespace(
            SetThreadExecutionState=lambda _co: 0)))
    goc_os, goc_ct = system_control.os, sys.modules.get("ctypes")
    trang_thai_cu = dict(system_control._giu_thuc)
    system_control.os = types.SimpleNamespace(name="nt")
    sys.modules["ctypes"] = fake_ctypes
    system_control._giu_thuc.update(stop=None, thread=None, errors=None)
    try:
        out = system_control.keep_awake(True, 10)
        assert "Không bật được" in out
        assert system_control._giu_thuc["stop"] is None
    finally:
        system_control.os = goc_os
        system_control._giu_thuc.update(trang_thai_cu)
        if goc_ct is not None:
            sys.modules["ctypes"] = goc_ct
        else:
            sys.modules.pop("ctypes", None)


def test_windows_khong_go_duoc_giu_thuc_thi_khong_bao_binh_thuong():
    from actions.system import system_control

    calls = []

    def set_state(flag):
        calls.append(flag)
        return 1 if len(calls) == 1 else 0

    fake_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(kernel32=types.SimpleNamespace(
            SetThreadExecutionState=set_state)))
    goc_os, goc_ct = system_control.os, sys.modules.get("ctypes")
    trang_thai_cu = dict(system_control._giu_thuc)
    system_control.os = types.SimpleNamespace(name="nt")
    sys.modules["ctypes"] = fake_ctypes
    system_control._giu_thuc.update(stop=None, thread=None, errors=None)
    try:
        assert "Đã giữ" in system_control.keep_awake(True, 10)
        out = system_control.keep_awake(False)
        assert "không xác nhận" in out.lower()
    finally:
        system_control.os = goc_os
        system_control._giu_thuc.update(trang_thai_cu)
        if goc_ct is not None:
            sys.modules["ctypes"] = goc_ct
        else:
            sys.modules.pop("ctypes", None)


# ------------------------------- audio_device --------------------------------------- #

def _tb(ten, state, flow):
    d = MagicMock()
    d.FriendlyName = ten
    d.state = state
    d.id = "id-" + ten
    return d, flow


def test_chi_liet_ke_thiet_bi_DANG_HOAT_DONG_va_dau_RA():
    """§8: máy này có 32 thiết bị mà chỉ 2 cái Active. Danh sách 32 dòng toàn tai nghe đã
    tháo thì vô dụng ở cả giọng nói lẫn panel."""
    from actions.system import system_control

    ACTIVE, TAT = 1, 4
    cap = [_tb("Loa Realtek", ACTIVE, "eRender"),
           _tb("Tai nghe đã tháo", TAT, "eRender"),
           _tb("Microphone Array", ACTIVE, "eCapture")]
    flow = {d.id: f for d, f in cap}

    gia_pycaw = types.ModuleType("pycaw.pycaw")
    gia_pycaw.AudioUtilities = types.SimpleNamespace(
        GetAllDevices=lambda: [d for d, _ in cap],
        GetEndpointDataFlow=lambda i: flow[i],
        SetDefaultDevice=lambda i: None)
    gia_const = types.ModuleType("pycaw.constants")
    gia_const.AudioDeviceState = types.SimpleNamespace(Active=ACTIVE)
    goc = {k: sys.modules.get(k) for k in ("pycaw.pycaw", "pycaw.constants")}
    sys.modules["pycaw.pycaw"], sys.modules["pycaw.constants"] = gia_pycaw, gia_const
    goc_os = system_control.os
    system_control.os = types.SimpleNamespace(name="nt")
    try:
        out = system_control.audio_device("list")
        assert "Loa Realtek" in out
        assert "đã tháo" not in out          # không Active
        assert "Microphone" not in out       # đầu vào, không phải đầu ra
    finally:
        system_control.os = goc_os
        for k, v in goc.items():
            if v is not None:
                sys.modules[k] = v
            else:
                sys.modules.pop(k, None)


def test_audio_device_khong_can_xac_nhan_nhung_bi_chan_o_luot_nhiem():
    reg, acts = _reg()
    assert reg.run("audio_device", {"action": "list"})
    with pytest.raises(ActionRefused):
        reg.run("audio_device", {"action": "switch", "name": "loa"}, nhiem=True)
    assert acts.goi == [("audio", "list", None)]


def test_keep_awake_cung_bi_chan_o_luot_nhiem():
    reg, acts = _reg()
    with pytest.raises(ActionRefused):
        reg.run("keep_awake", {"on": True}, nhiem=True)
    assert acts.goi == []


# ------------------------------ bộ Tầng 1 đã đủ ------------------------------------- #

def test_du_nam_tool_tang_1():
    reg, _ = _reg()
    for ten in ("list_processes", "power", "kill_process", "keep_awake", "audio_device"):
        assert reg.has(ten), f"thiếu tool Tầng 1: {ten}"


def test_moi_tool_quan_tri_deu_mang_co_admin():
    """Quên `admin` = tool đó mở đường cho trang web mớm lệnh đụng vào máy."""
    reg, _ = _reg()
    for ten in ("list_processes", "power", "kill_process", "keep_awake", "audio_device"):
        assert reg.get(ten).admin, f"{ten} thiếu cờ admin"


def test_khong_tool_quan_tri_nao_duoc_chay_tu_dong():
    reg, _ = _reg()
    for ten in ("list_processes", "power", "kill_process", "keep_awake", "audio_device"):
        assert not reg.get(ten).tu_dong, f"{ten} KHÔNG được phép chạy tự động"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
