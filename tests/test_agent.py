"""
Unit test cho Agent (vòng lặp tool-calling) và ToolRegistry.

Agent được tiêm một LLM giả (FakeLLMClient) chạy theo kịch bản định sẵn, nên
test không cần API key, không gọi mạng, không cần SDK anthropic. Actions cũng là
mock — không mở app thật.
"""

from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

from core.agent import Agent
from core.llm_client import AssistantTurn, Message, ToolCall
from core.tools import build_default_registry


class FakeLLMClient:
    """LLM giả: trả lần lượt các AssistantTurn trong `script`.

    Ghi lại `messages` của lần gọi cuối để test kiểm tra tool_results được
    đưa ngược lại LLM.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.last_messages = None

    def generate(self, *, system, messages, tools):
        self.last_messages = messages
        turn = self.script[self.calls]
        self.calls += 1
        return turn


def make_actions():
    actions = MagicMock()
    actions.open_application.return_value = "Đã mở Chrome"
    actions.control_volume.return_value = "Âm lượng +20%"
    return actions


# --------------------------- ToolRegistry --------------------------- #

def test_registry_has_expected_tools():
    reg = build_default_registry(make_actions())
    names = {spec["name"] for spec in reg.specs()}
    assert {"open_app", "set_volume", "shutdown", "play_youtube"} <= names


def test_registry_run_calls_action():
    actions = make_actions()
    reg = build_default_registry(actions)
    out = reg.run("open_app", {"app_name": "chrome"})
    actions.open_application.assert_called_once_with("chrome")
    assert out == "Đã mở Chrome"


def test_registry_specs_have_schema():
    reg = build_default_registry(make_actions())
    spec = next(s for s in reg.specs() if s["name"] == "open_app")
    assert spec["input_schema"]["type"] == "object"
    assert "app_name" in spec["input_schema"]["properties"]


# --------------------------- Agent loop --------------------------- #

def test_agent_no_tool_returns_text():
    actions = make_actions()
    llm = FakeLLMClient([AssistantTurn(text="Xin chào!")])
    agent = Agent(llm, build_default_registry(actions))
    assert agent.run("chào bạn") == "Xin chào!"


def test_agent_single_tool_then_answer():
    actions = make_actions()
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "chrome"})]),
        AssistantTurn(text="Đã mở Chrome cho bạn."),
    ])
    agent = Agent(llm, build_default_registry(actions))
    resp = agent.run("mở chrome")

    actions.open_application.assert_called_once_with("chrome")
    assert resp == "Đã mở Chrome cho bạn."
    # Kết quả tool được đưa ngược lại LLM ở lần gọi cuối
    fed_back = [m for m in llm.last_messages if m.tool_results]
    assert fed_back and fed_back[0].tool_results[0].content == "Đã mở Chrome"


def test_agent_multiple_tools_in_one_turn():
    actions = make_actions()
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[
            ToolCall("t1", "open_app", {"app_name": "chrome"}),
            ToolCall("t2", "set_volume", {"change": 20}),
        ]),
        AssistantTurn(text="Xong cả hai việc."),
    ])
    agent = Agent(llm, build_default_registry(actions))
    resp = agent.run("mở chrome và tăng âm lượng 20%")

    actions.open_application.assert_called_once_with("chrome")
    actions.control_volume.assert_called_once_with(level=None, change=20)
    assert resp == "Xong cả hai việc."


def test_agent_unknown_tool_is_reported_not_crash():
    actions = make_actions()
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "khong_ton_tai", {})]),
        AssistantTurn(text="Tôi không làm được việc đó."),
    ])
    agent = Agent(llm, build_default_registry(actions))
    resp = agent.run("làm gì đó lạ")
    assert resp == "Tôi không làm được việc đó."
    err = [m for m in llm.last_messages if m.tool_results][0].tool_results[0]
    assert err.is_error is True


def test_agent_tool_error_is_fed_back():
    actions = make_actions()
    actions.open_application.side_effect = RuntimeError("app not found")
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "xyz"})]),
        AssistantTurn(text="Không mở được ứng dụng đó."),
    ])
    agent = Agent(llm, build_default_registry(actions))
    resp = agent.run("mở xyz")
    assert resp == "Không mở được ứng dụng đó."
    err = [m for m in llm.last_messages if m.tool_results][0].tool_results[0]
    assert err.is_error is True and "app not found" in err.content


def test_agent_stops_at_max_iterations():
    actions = make_actions()
    # LLM luôn đòi gọi tool -> vòng lặp phải dừng theo max_iterations
    always_tool = [
        AssistantTurn(tool_calls=[ToolCall(f"t{i}", "set_volume", {"change": 1})])
        for i in range(10)
    ]
    llm = FakeLLMClient(always_tool)
    agent = Agent(llm, build_default_registry(actions), max_iterations=3)
    resp = agent.run("cứ tăng âm lượng mãi")
    assert "chưa hoàn tất" in resp
    assert llm.calls == 3


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
