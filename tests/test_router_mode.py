"""Test ROUTER_MODE — quyết định bật/tắt router theo chế độ + sức của provider.

Ràng buộc quan trọng nhất: model LOCAL phải
LUÔN giữ router. Đã có bằng chứng ngược: qwen 7B bỏ router thì gần như không gọi tool nữa.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utils.config import Config                        # noqa: E402


def _cfg(mode, provider):
    c = Config()
    c.ROUTER_MODE = mode
    c.LLM_PROVIDER = provider
    return c


# --------------------------- auto: bật cho mọi provider --------------------------- #

def test_auto_bat_router_cho_moi_provider():
    """Đổi 2026-08-26: `auto` bật router cho CẢ provider mạnh.

    Lý do cũ để tắt (đo 2026-08-08: bỏ router giảm 35% số call mà vẫn 100% đúng tool) chỉ
    nhìn SỐ CALL. Sau refactor feature-module, thứ quyết định là payload MỖI call: router
    TẮT gửi trọn bộ tool nên chi phí tăng tuyến tính theo số tính năng (đo 2026-08-26:
    57.568 vs 10.529 ký tự/lượt, và thêm 10 feature là ~97.865 vs ~12.428).
    Xem `docs/router_local_classifier_spec.md`.
    """
    for provider in ("gemini", "claude", "ollama", "mot-provider-la", ""):
        assert _cfg("auto", provider).use_router() is True, provider


def test_auto_keeps_router_for_local_model():
    """R1: bỏ router với model local đã THỬ và HỎNG -> không được tự tắt."""
    assert _cfg("auto", "ollama").use_router() is True


# --------------------------- on / off: ép cứng --------------------------- #

def test_on_forces_router_even_for_strong_provider():
    assert _cfg("on", "gemini").use_router() is True


def test_off_forces_no_router_even_for_local():
    assert _cfg("off", "ollama").use_router() is False


def test_unknown_mode_falls_back_to_auto():
    """Gõ sai chế độ -> xử như 'auto', không được vỡ."""
    assert _cfg("bat-dai", "ollama").use_router() is True
    assert _cfg("bat-dai", "gemini").use_router() is True


def test_off_van_la_duong_lui_duy_nhat():
    """`off` phải còn dùng được: đây là đường lui tức thì nếu eval cho kết quả xấu."""
    for provider in ("gemini", "claude", "ollama"):
        assert _cfg("off", provider).use_router() is False, provider


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
