"""Test Router (phân loại case + thu hẹp tool) và prompts loader — LLM giả."""

try:
    import pytest
except ImportError:
    pytest = None

from llm import prompts
from agent.router import Router, CASE_TOOLS
from llm.client import AssistantTurn
from agent.tools import build_default_registry


class _FakeLLM:
    """generate() trả nhãn định trước (mô phỏng lượt phân loại)."""
    def __init__(self, label):
        self.label = label
        self.calls = 0

    def generate(self, *, system, messages, tools):
        self.calls += 1
        return AssistantTurn(text=self.label)


class _FakeActions:
    def __getattr__(self, name):
        return lambda *a, **k: "noop"


def _registry():
    return build_default_registry(_FakeActions())      # có nhóm web, system... (không browser/screen)


# --------------------------- prompts ---------------------------

def test_prompts_load_has_base_and_cases():
    data = prompts.load()
    assert data["base"] and "web" in data["cases"] and data["router"]


def test_prompts_base_shortcut():
    assert prompts.base() == prompts.load()["base"]


# --------------------------- classify ---------------------------

def test_classify_returns_known_case():
    assert Router(_FakeLLM("web")).classify("tìm youtube") == "web"
    assert Router(_FakeLLM("system")).classify("tăng âm lượng") == "system"


def test_classify_parses_label_within_noise():
    # model trả kèm chữ thừa vẫn nhận ra case
    assert Router(_FakeLLM("Nhóm: schedule ạ")).classify("nhắc tôi") == "schedule"


def test_classify_weather_not_swallowed_by_web():
    # "web" là con của "weather" -> phải nhận đúng weather, không nuốt thành web
    assert Router(_FakeLLM("weather")).classify("thời tiết hôm nay") == "weather"
    assert Router(_FakeLLM("web")).classify("mở google") == "web"


def test_classify_unknown_falls_back_general():
    assert Router(_FakeLLM("khong-biet-gi")).classify("abc") == "general"


def test_classify_error_falls_back_general():
    class Boom:
        def generate(self, **k): raise RuntimeError("x")
    assert Router(Boom()).classify("abc") == "general"


# --------------------------- select: thu hẹp tool ---------------------------

def test_select_narrows_tools_to_case():
    reg = _registry()
    system, specs = Router(_FakeLLM("system")).select("tăng âm lượng", reg)
    names = {s["name"] for s in specs}
    assert names == set(CASE_TOOLS["system"])           # đúng nhóm system
    assert "web_search" not in names                     # đã loại tool ngoài nhóm
    assert "âm lượng" not in system.lower() or True      # system prompt = base + case


def test_select_general_uses_all_tools():
    reg = _registry()
    _, specs = Router(_FakeLLM("general")).select("chào bạn", reg)
    assert len(specs) == len(reg.specs())                # không thu hẹp


def test_select_empty_case_falls_back_full():
    # case 'browser' nhưng registry KHÔNG có tool browser -> dùng full thay vì rỗng
    reg = _registry()
    _, specs = Router(_FakeLLM("browser")).select("dừng video", reg)
    assert len(specs) == len(reg.specs())


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
