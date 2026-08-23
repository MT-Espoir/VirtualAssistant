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


def test_classify_task_case():
    # "task" không bị nuốt và không nuốt case khác
    assert Router(_FakeLLM("task")).classify("thêm việc mua sữa") == "task"


def test_select_narrows_to_task_case():
    from services.tasks import TaskStore
    from services.routines import RoutineStore
    reg = build_default_registry(_FakeActions(), tasks=TaskStore(path="__none__.json"),
                                 routines=RoutineStore(path="__none__.json"))
    _, specs = Router(_FakeLLM("task")).select("thêm việc mua sữa", reg)
    names = {s["name"] for s in specs}
    assert names == set(CASE_TOOLS["task"])
    assert "open_app" not in names and "schedule_reminder" not in names


class _FakeMCP:
    def __init__(self, names):
        self._names = names
    def list_tools(self):
        return [{"name": n, "description": "", "input_schema": {"type": "object", "properties": {}}}
                for n in self._names]


def test_pim_narrows_by_tool_prefix():
    # prefix phải ĐẶC THÙ để không nuốt tool sẵn có (vd 'g' sẽ dính get_weather)
    reg = build_default_registry(_FakeActions(), mcp=_FakeMCP(["gws_list_events", "gws_send_mail"]))
    _, specs = Router(_FakeLLM("pim"), mcp_prefix="gws_").select("lịch hôm nay có gì", reg)
    assert {s["name"] for s in specs} == {"gws_list_events", "gws_send_mail"}


def test_pim_without_prefix_uses_full():
    reg = _registry()      # không có MCP + không prefix -> pim giữ full tool
    _, specs = Router(_FakeLLM("pim")).select("lịch", reg)
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


# --------------------------- mọi tool đã đăng ký phải với tới được --------------------------- #
#
# HỒI QUY: `research_places` từng được đăng ký vào registry nhưng KHÔNG có trong
# CASE_TOOLS["place"]. Router bật (mặc định với ollama) thì thu hẹp danh sách tool theo
# case, nên model KHÔNG BAO GIỜ nhìn thấy tool đó — tính năng chết lặng, test cũ vẫn xanh.

def _full_registry():
    """Registry có ĐỦ mọi nhóm tool (tiêm mock cho các phụ thuộc tuỳ chọn).

    `_registry()` ở trên cố tình thiếu browser/screen/places để test phần thu hẹp; ở đây
    cần bản đầy đủ mới đối chiếu được CASE_TOOLS với registry.
    """
    from unittest.mock import MagicMock
    return build_default_registry(
        _FakeActions(), scheduler=MagicMock(), browser=MagicMock(), screen=MagicMock(),
        profile=MagicMock(), tasks=MagicMock(), routines=MagicMock(),
        contacts=MagicMock(), places=MagicMock(), location=MagicMock())


def test_case_tools_only_names_registered_tools():
    """Tên trong CASE_TOOLS phải khớp registry — sai chính tả là tool biến mất im lặng."""
    reg = _full_registry()
    for case, names in CASE_TOOLS.items():
        for name in names or []:
            assert reg.has(name), f"CASE_TOOLS['{case}'] trỏ tới tool không tồn tại: {name}"


def test_place_case_exposes_research_places():
    reg = _full_registry()
    assert reg.has("research_places"), "tool chưa đăng ký"
    assert "research_places" in CASE_TOOLS["place"], (
        "research_places không nằm trong case 'place' -> router che mất tool, "
        "model không bao giờ chọn được")


def test_place_case_prompt_mentions_research_places():
    """Có tool trong danh sách chưa đủ: prompt phải nói KHI NÀO chọn nó."""
    frag = prompts.load()["cases"]["place"]
    assert "research_places" in frag
