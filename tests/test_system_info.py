"""
Test actions.system.system_info — không cần cài psutil thật: tiêm một psutil giả vào
sys.modules trước khi import, và giả shutil.disk_usage. Nhờ vậy chạy được ở mọi
máy và kiểm tra logic định dạng chuỗi + định tuyến theo `what`.
"""

from conftest import registry_with

import sys
import socket
import types
from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

GB = 1024 ** 3


def _install_fake_psutil():
    fake = types.ModuleType("psutil")
    fake.virtual_memory = lambda: types.SimpleNamespace(
        total=16 * GB, used=8 * GB, available=8 * GB, percent=50.0)
    fake.cpu_percent = lambda interval=0.0: 25.0
    fake.cpu_count = lambda logical=True: 8
    fake.sensors_battery = lambda: types.SimpleNamespace(percent=80.0, power_plugged=True)
    # Các module khác cũng dùng cùng binding `system_info.psutil` trong lúc pytest
    # collection. Mock nền phải đủ API đọc trạng thái Windows Update để không làm
    # sai lệch cổng fail-closed của tool nguồn.
    fake.process_iter = lambda attrs=None: []
    fake.net_if_stats = lambda: {
        "Wi-Fi": types.SimpleNamespace(isup=True),
        "Loopback": types.SimpleNamespace(isup=True),
        "Ethernet": types.SimpleNamespace(isup=False),
    }
    fake.net_if_addrs = lambda: {
        "Wi-Fi": [types.SimpleNamespace(family=socket.AF_INET, address="192.168.1.25")],
        "Loopback": [types.SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")],
        "Ethernet": [types.SimpleNamespace(family=socket.AF_INET, address="10.0.0.5")],
    }
    fake.net_connections = lambda kind="tcp": [
        types.SimpleNamespace(status="ESTABLISHED"),
        types.SimpleNamespace(status="LISTEN"),
        types.SimpleNamespace(status="ESTABLISHED"),
    ]
    sys.modules["psutil"] = fake
    return fake


_FAKE_PSUTIL = _install_fake_psutil()
from actions.system import system_info  # noqa: E402  (import sau khi tiêm psutil giả)
# Module có thể đã được test khác import trong giai đoạn collection. Khi đó thay
# `sys.modules` không đổi binding cũ; gán tường minh để test không phụ thuộc thứ tự file.
system_info.psutil = _FAKE_PSUTIL

# Giả disk_usage để không phụ thuộc ổ đĩa thật
system_info.shutil = MagicMock()
system_info.shutil.disk_usage.return_value = (500 * GB, 300 * GB, 200 * GB)


def test_memory_info():
    out = system_info.get_memory_info()
    assert "RAM" in out and "50%" in out and "8.0 GB" in out


def test_disk_info():
    out = system_info.get_disk_info()
    assert "Ổ đĩa" in out and "60%" in out  # 300/500


def test_cpu_info():
    out = system_info.get_cpu_info()
    assert "CPU" in out and "25%" in out and "8 luồng" in out


def test_battery_info():
    out = system_info.get_battery_info()
    assert "Pin" in out and "80%" in out and "đang sạc" in out


def test_battery_no_battery():
    system_info.psutil.sensors_battery = lambda: None
    out = system_info.get_battery_info()
    assert "không có pin" in out
    # khôi phục cho các test khác
    system_info.psutil.sensors_battery = lambda: types.SimpleNamespace(
        percent=80.0, power_plugged=True)


def test_summary_all_has_every_section():
    out = system_info.get_system_summary("all")
    assert "RAM" in out and "Ổ đĩa" in out and "CPU" in out and "Pin" in out
    assert "Mạng" not in out  # mạng có thể chứa SSID: chỉ đọc khi người dùng hỏi rõ


def test_summary_single_section():
    out = system_info.get_system_summary("cpu")
    assert "CPU" in out and "RAM" not in out


def test_network_info_chi_lay_interface_dang_hoat_dong(monkeypatch):
    monkeypatch.setattr(system_info, "_wifi_ssid", lambda: "Nha cua toi")
    out = system_info.get_system_summary("network")
    assert 'Wi-Fi "Nha cua toi"' in out
    assert "192.168.1.25 (Wi-Fi)" in out
    assert "127.0.0.1" not in out and "10.0.0.5" not in out
    assert "2 kết nối TCP" in out


def test_parse_wifi_ssid_khong_nham_bssid_va_bo_ky_tu_dieu_khien():
    raw = "    BSSID : aa:bb:cc\n    SSID : Nha\x00 cua toi\n"
    assert system_info._parse_wifi_ssid(raw) == "Nha  cua toi"


def test_network_info_that_bai_tung_phan_van_tra_duoc(monkeypatch):
    monkeypatch.setattr(system_info, "_wifi_ssid", lambda: "")
    monkeypatch.setattr(system_info, "_active_ipv4", lambda: [])
    monkeypatch.setattr(system_info.psutil, "net_connections",
                        MagicMock(side_effect=PermissionError("denied")))
    assert system_info.get_network_info() == "Mạng: không đọc được thông tin mạng đang hoạt động."


def test_summary_unknown():
    out = system_info.get_system_summary("khong_biet")
    assert "Không hiểu" in out


# --------------------- thời gian pin còn lại (docs/system_admin_spec.md §5.1) --------- #

def test_secsleft_sentinel_khong_bao_gio_doc_thanh_so_am():
    """Hồi quy cho đúng cái bẫy: `secsleft` là SENTINEL ÂM, không phải giây. Đọc thẳng thì
    thành "còn âm hai giây"."""
    for gia_tri in (-1, -2, -99):
        out = system_info.format_battery_left(gia_tri)
        assert "âm" not in out and "-" not in out


def test_dang_sac_thi_khong_uoc_luong():
    assert system_info.format_battery_left(7412, plugged=True) == ""
    assert system_info.format_battery_left(-2) == ""          # UNLIMITED = đang sạc
    assert system_info.format_battery_left(None) == ""


def test_chua_du_du_lieu_thi_noi_that():
    """`-1` là trạng thái HAY GẶP ngay sau khi rút sạc — đúng lúc người ta hỏi nhất."""
    assert "chưa ước lượng được" in system_info.format_battery_left(-1)


def test_lam_tron_theo_cach_nguoi_ta_noi():
    assert system_info.format_battery_left(30) == "còn dưới một phút"
    assert system_info.format_battery_left(7 * 60) == "còn khoảng 7 phút"
    assert system_info.format_battery_left(12 * 60) == "còn khoảng 10 phút"
    assert system_info.format_battery_left(59 * 60) == "còn khoảng 1 tiếng"
    assert system_info.format_battery_left(7412) == "còn khoảng 2 tiếng"      # 2h03
    assert system_info.format_battery_left(150 * 60) == "còn khoảng 2 tiếng 30 phút"
    assert system_info.format_battery_left(175 * 60) == "còn khoảng 3 tiếng"  # 2h55 -> 3h


def test_so_vo_ly_bi_chan():
    assert system_info.format_battery_left(99 * 3600) == "còn hơn một ngày"


def test_battery_info_gop_thoi_gian_con_lai():
    system_info.psutil.sensors_battery = lambda: types.SimpleNamespace(
        percent=45.0, power_plugged=False, secsleft=7412)
    out = system_info.get_battery_info()
    assert "45%" in out and "dùng pin" in out and "2 tiếng" in out
    system_info.psutil.sensors_battery = lambda: types.SimpleNamespace(
        percent=80.0, power_plugged=True)


def test_battery_info_thieu_secsleft_van_chay():
    """psutil trên vài nền tảng không có trường này — không được nổ."""
    system_info.psutil.sensors_battery = lambda: types.SimpleNamespace(
        percent=55.0, power_plugged=False)
    assert "55%" in system_info.get_battery_info()
    system_info.psutil.sensors_battery = lambda: types.SimpleNamespace(
        percent=80.0, power_plugged=True)


def test_system_info_tool_calls_correct_path():
    """Hồi quy bug: tool gọi actions.system_info (KHÔNG phải actions.system.system_info).
    Dùng stub CHỈ có system_info nên nếu gọi sai đường sẽ ném AttributeError."""
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from conftest import registry_with

    class ActionsStub:
        def system_info(self, what="all"):
            return f"info:{what}"

    reg = registry_with(actions=ActionsStub())
    assert reg.run("system_info", {"what": "cpu"}) == "info:cpu"


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print("PASS", _name)
            except Exception as _e:  # noqa: BLE001
                failures += 1
                print("FAIL", _name, "->", repr(_e))
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    raise SystemExit(1 if failures else 0)
