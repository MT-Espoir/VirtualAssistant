"""Test ROUTER_MODE — quyết định bật/tắt router theo chế độ + sức của provider.

Ràng buộc quan trọng nhất: model LOCAL phải
LUÔN giữ router. Đã có bằng chứng ngược: qwen 7B bỏ router thì gần như không gọi tool nữa.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.config import Config, STRONG_PROVIDERS       # noqa: E402


def _cfg(mode, provider):
    c = Config()
    c.ROUTER_MODE = mode
    c.LLM_PROVIDER = provider
    return c


# --------------------------- auto: theo sức provider --------------------------- #

def test_auto_disables_router_for_strong_providers():
    for provider in STRONG_PROVIDERS:
        assert _cfg("auto", provider).use_router() is False, provider


def test_auto_keeps_router_for_local_model():
    """R1: bỏ router với model local đã THỬ và HỎNG -> không được tự tắt."""
    assert _cfg("auto", "ollama").use_router() is True


def test_auto_keeps_router_for_unknown_provider():
    """Provider lạ -> mặc định AN TOÀN là giữ router (đừng đoán là nó mạnh)."""
    assert _cfg("auto", "mot-provider-la").use_router() is True


def test_auto_handles_empty_provider():
    assert _cfg("auto", "").use_router() is True


# --------------------------- on / off: ép cứng --------------------------- #

def test_on_forces_router_even_for_strong_provider():
    assert _cfg("on", "gemini").use_router() is True


def test_off_forces_no_router_even_for_local():
    assert _cfg("off", "ollama").use_router() is False


def test_unknown_mode_falls_back_to_auto():
    """Gõ sai chế độ -> xử như 'auto', không được vỡ."""
    assert _cfg("bat-dai", "ollama").use_router() is True
    assert _cfg("bat-dai", "gemini").use_router() is False


# --------------------------- đọc từ biến môi trường --------------------------- #
# Config đọc env MỘT LẦN lúc import -> muốn thử giá trị khác phải nạp lại module.
# Luôn nạp lại lần nữa ở cuối để trả module về trạng thái ban đầu cho các test khác.

def _mode_for_env(monkeypatch, value):
    import importlib
    import utils.config as cfg_mod

    if value is None:
        monkeypatch.delenv("ROUTER_MODE", raising=False)
    else:
        monkeypatch.setenv("ROUTER_MODE", value)
    try:
        return importlib.reload(cfg_mod).Config.ROUTER_MODE
    finally:
        monkeypatch.undo()
        importlib.reload(cfg_mod)


def test_mode_is_case_and_space_insensitive(monkeypatch):
    assert _mode_for_env(monkeypatch, "  ON  ") == "on"


def test_mode_defaults_to_auto(monkeypatch):
    assert _mode_for_env(monkeypatch, None) == "auto"
