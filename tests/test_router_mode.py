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


# --- bề mặt tool: router | indexed | all ------------------------------------------

def _che_do(provider, tool_surface, router_mode):
    """Gọi `surface_mode` với một cấu hình cụ thể rồi TRẢ LẠI nguyên trạng."""
    from utils.config import config
    cu = (config.LLM_PROVIDER, config.TOOL_SURFACE, config.ROUTER_MODE)
    config.LLM_PROVIDER, config.TOOL_SURFACE, config.ROUTER_MODE = (
        provider, tool_surface, router_mode)
    try:
        return config.surface_mode()
    finally:
        config.LLM_PROVIDER, config.TOOL_SURFACE, config.ROUTER_MODE = cu


def test_auto_giu_AllTools_theo_so_do():
    """Eval thật 2026-09-12: `IndexedTools` trượt tiêu chí 2 và 3 (tool-acc 100%->96%,
    độ trễ +15%). Ở N=52 tool thì `AllTools` vẫn chọn đúng 54/54 — bài toán mà
    `IndexedTools` sinh ra để giải chưa xảy ra. Xem `docs/indexed_tools_spec.md` §7f."""
    assert _che_do("gemini", "auto", "auto") == "all"
    assert _che_do("claude", "auto", "auto") == "all"


def test_van_bat_duoc_bang_mot_bien_moi_truong():
    """Tắt mặc định nhưng KHÔNG chôn: `IndexedTools` là thứ sẽ cần khi N lớn hơn, và lúc
    đó không ai muốn phải dựng lại nó."""
    assert _che_do("gemini", "indexed", "auto") == "indexed"


def test_auto_KHONG_bat_indexed_cho_model_local():
    """Mở nhóm giữa lượt nối tool vào cuối -> tiền tố đổi giữa hai vòng của CÙNG một lượt.
    Ollama tái dùng KV cache theo tiền tố: mất 16-20 giây, nhiều hơn mọi thứ tiết kiệm
    được. Đây là lý do `auto` không bao giờ tự bật indexed cho model local."""
    assert _che_do("ollama", "auto", "auto") == "router"
    assert _che_do("ollama", "auto", "off") == "all"


def test_dat_tuong_minh_thang_dat_tu_dong():
    """`TOOL_SURFACE=indexed` là yêu cầu rõ ràng nên vượt cả `ROUTER_MODE=auto`..."""
    assert _che_do("ollama", "indexed", "auto") == "indexed"
    assert _che_do("ollama", "indexed", "on") == "indexed"
    # ...còn `ROUTER_MODE=on` (cũng tường minh) vẫn thắng `TOOL_SURFACE=auto`.
    assert _che_do("gemini", "auto", "on") == "router"


def test_ep_all_thi_khong_bao_gio_indexed():
    assert _che_do("gemini", "all", "auto") == "all"
    assert _che_do("gemini", "all", "off") == "all"
    assert _che_do("ollama", "all", "off") == "all"


def test_chi_tra_ve_ba_gia_tri_hop_le():
    hop_le = {"router", "indexed", "all"}
    for p in ("ollama", "gemini", "claude", "la_hoac"):
        for t in ("auto", "all", "indexed", "rác"):
            for r in ("auto", "on", "off", "rác"):
                assert _che_do(p, t, r) in hop_le
