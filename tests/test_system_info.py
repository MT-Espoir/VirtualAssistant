"""
Test actions.system.system_info — không cần cài psutil thật: tiêm một psutil giả vào
sys.modules trước khi import, và giả shutil.disk_usage. Nhờ vậy chạy được ở mọi
máy và kiểm tra logic định dạng chuỗi + định tuyến theo `what`.
"""

import sys
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
    sys.modules["psutil"] = fake
    return fake


_install_fake_psutil()
from actions.system import system_info  # noqa: E402  (import sau khi tiêm psutil giả)

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


def test_summary_single_section():
    out = system_info.get_system_summary("cpu")
    assert "CPU" in out and "RAM" not in out


def test_summary_unknown():
    out = system_info.get_system_summary("khong_biet")
    assert "Không hiểu" in out


def test_system_info_tool_calls_correct_path():
    """Hồi quy bug: tool gọi actions.system_info (KHÔNG phải actions.system.system_info).
    Dùng stub CHỈ có system_info nên nếu gọi sai đường sẽ ném AttributeError."""
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from agent.tools import build_default_registry

    class ActionsStub:
        def system_info(self, what="all"):
            return f"info:{what}"

    reg = build_default_registry(ActionsStub())
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
