"""
Tool quản trị Tầng 1: `power` + `list_processes`.

Hai tool này TỪNG BỊ GỠ KHỎI AGENT sau khi STT nghe nhầm làm máy bị cưỡng chế reset
(`docs/system_admin_spec.md` §4b). Nên phần lớn test ở đây không kiểm "chạy có đúng không"
mà kiểm "hỏng có chặn được không" — và ca quan trọng nhất là ca đã hỏng thật:

    nghe nhầm ra lệnh tắt máy  ->  máy KHÔNG tắt ngay, luôn có cửa sổ để huỷ.
"""

from conftest import registry_with

import sys
import types
from unittest.mock import MagicMock

import pytest

from agent.tools import ActionRefused, NeedsConfirmation


class ActionsStub:
    """Facade giả: ghi lại lời gọi thay vì tắt máy thật."""

    def __init__(self):
        self.goi = []

    def control_power(self, action=None, delay_minutes=None):
        self.goi.append((action, delay_minutes))
        return f"giả lập {action}"

    def list_processes(self, sort_by="memory", limit=3):
        self.goi.append((sort_by, limit))
        return "Ngốn RAM nhất: chrome.exe 1.2 GB."


def _reg():
    acts = ActionsStub()
    return registry_with(actions=acts), acts


# ------------------- ca đã làm hỏng máy: nghe nhầm ra lệnh tắt máy ------------------- #

def test_tat_may_khong_bao_gio_chay_ngay():
    """Ca §4b. Kể cả khi mọi cổng đã qua, lệnh vẫn phải là lệnh HẸN GIỜ — cửa sổ huỷ là
    thứ bản cũ không có, và là lý do duy nhất để nối lại tool này."""
    from actions.system import system_control

    chay = []
    system_control._chay_shutdown = lambda *a: chay.append(a) or types.SimpleNamespace(
        returncode=0)
    system_control.os = types.SimpleNamespace(name='nt')
    try:
        out = system_control.control_power("shutdown")
        assert chay == [("/s", "/t", "60")]          # /t = có hẹn giờ
        assert "huỷ" in out                          # và nói cho người dùng biết đường thoát
    finally:
        system_control.os = __import__("os")


def test_khong_bao_gio_dung_co_ep():
    """`/f` giết thẳng ứng dụng, mất hết việc chưa lưu. Không bao giờ, kể cả khi được hỏi."""
    from actions.system import system_control

    chay = []
    system_control._chay_shutdown = lambda *a: chay.append(a) or types.SimpleNamespace(
        returncode=0)
    system_control.os = types.SimpleNamespace(name='nt')
    try:
        for act in ("shutdown", "restart"):
            for delay in (None, 0, -5, 30, "hai"):
                system_control.control_power(act, delay)
        assert not any("/f" in c for lenh in chay for c in lenh)
    finally:
        system_control.os = __import__("os")


def test_hen_gio_khong_bao_gio_ngan_hon_toi_thieu():
    """Cửa sổ huỷ 0 giây là cửa sổ chỉ có trên giấy."""
    from actions.system import system_control

    chay = []
    system_control._chay_shutdown = lambda *a: chay.append(a) or types.SimpleNamespace(
        returncode=0)
    system_control.os = types.SimpleNamespace(name='nt')
    try:
        for delay in (None, 0, -99, "rác"):
            system_control.control_power("shutdown", delay)
        giay = [int(c[2]) for c in chay]
        assert all(g >= system_control.PHUT_CHO_TOI_THIEU * 60 for g in giay)
    finally:
        system_control.os = __import__("os")


def test_shutdown_that_bai_khong_bao_da_hen():
    """Không có cửa sổ huỷ nếu Windows từ chối lệnh; câu trả lời không được nói đã hẹn."""
    from actions.system import system_control

    goc_chay = system_control._chay_shutdown
    system_control._chay_shutdown = lambda *a: types.SimpleNamespace(returncode=5)
    system_control.os = types.SimpleNamespace(name='nt')
    try:
        out = system_control.control_power("shutdown")
        assert "Không hẹn được" in out
        assert "Sẽ tắt máy" not in out
    finally:
        system_control.os = __import__("os")
        system_control._chay_shutdown = goc_chay


def test_signout_khong_ton_tai():
    """`shutdown /l` KHÔNG nhận `/t` -> không có cửa sổ huỷ, mà vẫn đóng sạch ứng dụng.
    Không đạt điều kiện nên cố ý không có trong bộ lệnh."""
    reg, _ = _reg()
    assert "signout" not in reg.get("power").input_schema["properties"]["action"]["enum"]


# ------------------------------ cổng duyệt theo tham số ----------------------------- #

def test_tat_may_phai_xac_nhan_con_khoa_man_hinh_thi_khong():
    """Chính cái bẫy §3: cờ tĩnh thì hoặc tắt máy không hỏi, hoặc khoá màn hình cũng hỏi."""
    reg, acts = _reg()
    with pytest.raises(NeedsConfirmation):
        reg.run("power", {"action": "shutdown"})
    assert acts.goi == []                              # chưa chạy gì cả

    assert reg.run("power", {"action": "lock"})        # khoá màn hình: không hỏi
    assert acts.goi == [("lock", None)]


def test_huy_la_duong_thoat_nen_khong_duoc_hoi():
    reg, acts = _reg()
    assert reg.run("power", {"action": "cancel"})
    assert acts.goi == [("cancel", None)]


def test_khoi_dong_lai_cung_phai_xac_nhan():
    reg, _ = _reg()
    with pytest.raises(NeedsConfirmation):
        reg.run("power", {"action": "restart"})


# ------------------------ cấm cứng: người dùng đồng ý vẫn không ---------------------- #

def test_cam_tat_may_khi_windows_dang_cai_cap_nhat():
    """§7 lớp 3. `confirmed=True` = người dùng đã nói "có" — vẫn không mở được."""
    from features.system import tools as system_tools

    goc = sys.modules["actions.system.system_info"].dang_cai_windows_update
    sys.modules["actions.system.system_info"].dang_cai_windows_update = \
        lambda: "tiworker.exe"
    try:
        reg, acts = _reg()
        with pytest.raises(ActionRefused) as e:
            reg.run("power", {"action": "shutdown"}, confirmed=True)
        assert "cập nhật" in e.value.ly_do
        assert acts.goi == []
        # khoá màn hình thì vẫn được: lệnh cấm xét THAM SỐ, không cấm cả tool
        assert reg.run("power", {"action": "lock"}, confirmed=True)
        assert system_tools.cam_power("lock") is None
    finally:
        sys.modules["actions.system.system_info"].dang_cai_windows_update = goc


def test_cam_hong_thi_cam(monkeypatch):
    """Lệnh cấm nổ -> từ chối. Cờ an toàn hỏng mà đoán "chắc không sao" là hỏng thật."""
    from agent.tools import Tool, ToolRegistry

    def no(**_):
        raise RuntimeError("psutil chết")

    reg = ToolRegistry()
    reg.register(Tool(name="viec", description="d", input_schema={"type": "object"},
                      handler=lambda **_: "xong", cam=no))
    with pytest.raises(ActionRefused):
        reg.run("viec", {}, confirmed=True)


def test_cam_khong_lam_phien_tool_thuong():
    """Tool không khai `cam` thì không đổi hành vi chút nào."""
    reg, _ = _reg()
    assert reg.tu_choi("system_info", {"what": "cpu"}) is None


# ------------------------------ hai trục rủi ro còn lại ----------------------------- #

def test_ca_hai_tool_deu_bi_chan_o_luot_nhiem():
    """Trang web mớm "tắt máy đi" -> từ chối thẳng, KHÔNG biến thành câu hỏi cho người dùng.
    `list_processes` chỉ đọc nhưng cũng chặn: nó là bước do thám trước lệnh tắt."""
    reg, acts = _reg()
    for ten, args in (("power", {"action": "shutdown"}),
                      ("list_processes", {})):
        with pytest.raises(ActionRefused):
            reg.run(ten, args, nhiem=True)
    assert acts.goi == []


def test_khong_tool_nao_chay_duoc_tren_duong_tu_dong():
    reg, acts = _reg()
    for ten, args in (("power", {"action": "lock"}), ("list_processes", {})):
        with pytest.raises(ActionRefused):
            reg.run(ten, args, tu_dong=True)
    assert acts.goi == []


# --------------------------------- list_processes ----------------------------------- #

def _fake_psutil(procs, luong=8):
    fake = types.ModuleType("psutil")
    fake.process_iter = lambda attrs=None: procs
    fake.cpu_count = lambda logical=True: luong
    sys.modules["psutil"] = fake
    return fake


def _proc(name, rss=0, cpu=0.0):
    p = MagicMock()
    p.info = {"name": name, "memory_info": types.SimpleNamespace(rss=rss)}
    p.cpu_percent = lambda: cpu
    return p


def test_gop_theo_ten_ung_dung():
    """Chrome chạy 20 tiến trình cùng tên — người ta hỏi ỨNG DỤNG nào ngốn, không hỏi PID."""
    from actions.system import system_info

    goc = system_info.psutil
    system_info.psutil = _fake_psutil([
        _proc("chrome.exe", rss=400 * 1024 ** 2),
        _proc("chrome.exe", rss=400 * 1024 ** 2),
        _proc("chrome.exe", rss=400 * 1024 ** 2),
        _proc("Code.exe", rss=900 * 1024 ** 2),
    ])
    try:
        out = system_info.list_processes("memory", 2)
        assert out.index("chrome.exe") < out.index("Code.exe")   # 1.2 GB gộp > 900 MB
        assert "1.2 GB" in out and "900 MB" in out
        assert out.count("chrome.exe") == 1
    finally:
        system_info.psutil = goc


def test_limit_bi_chan_tren_de_con_doc_len_duoc():
    """§8: kết quả phải đọc lên được. Model xin 500 dòng thì vẫn chỉ trả vài dòng."""
    from actions.system import system_info

    goc = system_info.psutil
    system_info.psutil = _fake_psutil([_proc(f"p{i}.exe", rss=i * 1024 ** 2)
                                       for i in range(50)])
    try:
        out = system_info.list_processes("memory", 500)
        assert out.count(";") + 1 <= system_info._MAX_TIEN_TRINH
    finally:
        system_info.psutil = goc


def test_bo_qua_tien_trinh_ranh():
    """`System Idle Process` chiếm đúng phần CPU KHÔNG ai dùng — nó luôn đứng đầu bảng và
    luôn là câu trả lời sai cho "cái gì làm máy chậm". Bắt được ở lần chạy thật đầu tiên."""
    from actions.system import system_info

    goc = system_info.psutil
    system_info.psutil = _fake_psutil([_proc("System Idle Process", cpu=800.0),
                                       _proc("chrome.exe", cpu=40.0)])
    try:
        out = system_info.list_processes("cpu", 3)
        assert "Idle" not in out and "chrome.exe" in out
    finally:
        system_info.psutil = goc


def test_cpu_chia_theo_so_luong():
    """`Process.cpu_percent` tính theo MỘT lõi nên cộng lại vượt 100%. Chia ra mới khớp
    con số Task Manager hiện — con số người dùng đối chiếu được bằng mắt."""
    from actions.system import system_info

    goc = system_info.psutil
    system_info.psutil = _fake_psutil([_proc("chrome.exe", cpu=800.0)])
    try:
        assert "chrome.exe 100%" in system_info.list_processes("cpu", 1)
    finally:
        system_info.psutil = goc


def test_khong_co_tien_trinh_nao_thi_noi_that():
    from actions.system import system_info

    goc = system_info.psutil
    system_info.psutil = _fake_psutil([])
    try:
        assert "Không đọc được" in system_info.list_processes()
    finally:
        system_info.psutil = goc


def test_phat_hien_windows_update():
    from actions.system import system_info

    goc = system_info.psutil
    system_info.psutil = _fake_psutil([_proc("TiWorker.exe")])
    try:
        assert system_info.dang_cai_windows_update() == "tiworker.exe"
    finally:
        system_info.psutil = goc


def test_khong_co_update_thi_none():
    from actions.system import system_info

    goc = system_info.psutil
    system_info.psutil = _fake_psutil([_proc("chrome.exe")])
    try:
        assert system_info.dang_cai_windows_update() is None
    finally:
        system_info.psutil = goc


def test_khong_doc_duoc_update_thi_cam_tat_may():
    """Lỗi psutil không được nhập nhằng thành 'không có update' rồi mở cổng tắt máy."""
    from actions.system import system_info

    goc = system_info.psutil
    system_info.psutil = types.SimpleNamespace(
        process_iter=lambda attrs=None: (_ for _ in ()).throw(OSError("access denied")))
    try:
        reg, acts = _reg()
        with pytest.raises(ActionRefused) as e:
            reg.run("power", {"action": "shutdown"}, confirmed=True)
        assert "không kiểm được" in e.value.ly_do
        assert acts.goi == []
    finally:
        system_info.psutil = goc


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
