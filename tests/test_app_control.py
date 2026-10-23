"""Test bảo mật mở/đóng app: chặn shell injection, chạy taskkill dạng argv (không shell)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from actions.system import app_control as ac


class _Done:
    def __init__(self, returncode):
        self.returncode = returncode


def test_is_safe_exe_accepts_normal_names():
    for name in ("chrome", "msedge", "winword", "notepad++", "my app"):
        assert ac._is_safe_exe(name), name


def test_is_safe_exe_rejects_shell_metachars():
    for bad in ("a & calc", "x; rm -rf", "y | net", "z`whoami`", "$(x)", "", "a" * 61):
        assert not ac._is_safe_exe(bad), bad


def test_close_rejects_injection_name_without_running_anything(monkeypatch):
    called = {"run": 0, "call": 0}
    monkeypatch.setattr(ac.subprocess, "run", lambda *a, **k: called.__setitem__("run", 1))
    monkeypatch.setattr(ac.subprocess, "call", lambda *a, **k: called.__setitem__("call", 1))
    # Tên KHÔNG khớp alias -> resolve trả chuỗi thô có ký tự shell -> phải bị từ chối
    msg = ac.close_application("hackx & shutdown /s")
    assert "không hợp lệ" in msg.lower()
    assert called == {"run": 0, "call": 0}       # tuyệt đối không gọi taskkill/pkill


def test_close_uses_argv_list_not_shell_string(monkeypatch):
    captured = {}
    monkeypatch.setattr(ac.os, "name", "nt")
    monkeypatch.setattr(ac.subprocess, "run", lambda args, **k: captured.update(args=args) or _Done(0))
    msg = ac.close_application("chrome")
    assert captured["args"] == ["taskkill", "/im", "chrome.exe"]   # LIST argv, không phải chuỗi shell
    assert "Đã đóng" in msg


def test_known_alias_with_trailing_junk_normalizes_safely(monkeypatch):
    # "chrome & shutdown" chứa alias 'chrome' -> resolve chuẩn hoá về 'chrome' (an toàn)
    captured = {}
    monkeypatch.setattr(ac.os, "name", "nt")
    monkeypatch.setattr(ac.subprocess, "run", lambda args, **k: captured.update(args=args) or _Done(0))
    ac.close_application("chrome & shutdown")
    assert captured["args"] == ["taskkill", "/im", "chrome.exe"]


def test_close_reports_failure_when_taskkill_fails(monkeypatch):
    """F06: taskkill trả 128 (không có tiến trình) thì không được nói 'Đã đóng'."""
    import pytest
    monkeypatch.setattr(ac.os, "name", "nt")
    monkeypatch.setattr(ac.subprocess, "run", lambda args, **k: _Done(128))
    with pytest.raises(RuntimeError, match="mã lỗi 128"):
        ac.close_application("notepad")


def test_open_failure_raises_instead_of_returning_text(monkeypatch):
    """F06: chuỗi lỗi trả về bình thường bị Agent coi là tool thành công."""
    import pytest

    def missing(_exe):
        raise FileNotFoundError("missing")
    monkeypatch.setattr(ac.os, "name", "nt")
    monkeypatch.setattr(ac.os, "startfile", missing, raising=False)
    with pytest.raises(RuntimeError, match="Không mở được"):
        ac.open_application("notepad")
