"""
Unit test cho Agent (vòng lặp tool-calling, bộ nhớ, cảm xúc).

Agent được tiêm LLM giả (FakeLLMClient) chạy theo kịch bản + actions mock — không
cần API key, mạng, hay SDK. run() trả AgentReply(text, emotion).
"""

import os
import tempfile
from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

from core.agent import Agent
from core.llm_client import AssistantTurn, Message, ToolCall
from core.tools import build_default_registry


class FakeLLMClient:
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


def make_agent(script, actions=None, **kwargs):
    actions = actions or make_actions()
    return Agent(FakeLLMClient(script), build_default_registry(actions), **kwargs)


# --------------------------- Vòng lặp cơ bản --------------------------- #

def test_no_tool_returns_text():
    agent = make_agent([AssistantTurn(text="Xin chào!")])
    assert agent.run("chào bạn").text == "Xin chào!"


def test_single_tool_then_answer():
    actions = make_actions()
    agent = make_agent([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "chrome"})]),
        AssistantTurn(text="Đã mở Chrome cho bạn."),
    ], actions=actions)
    reply = agent.run("mở chrome")
    actions.open_application.assert_called_once_with("chrome")
    assert reply.text == "Đã mở Chrome cho bạn."


def test_multiple_tools_in_one_turn():
    actions = make_actions()
    agent = make_agent([
        AssistantTurn(tool_calls=[
            ToolCall("t1", "open_app", {"app_name": "chrome"}),
            ToolCall("t2", "set_volume", {"change": 20}),
        ]),
        AssistantTurn(text="Xong cả hai việc."),
    ], actions=actions)
    reply = agent.run("mở chrome và tăng âm lượng 20%")
    actions.open_application.assert_called_once_with("chrome")
    actions.control_volume.assert_called_once_with(level=None, change=20)
    assert reply.text == "Xong cả hai việc."


def test_unknown_tool_reported_not_crash():
    agent = make_agent([
        AssistantTurn(tool_calls=[ToolCall("t1", "khong_ton_tai", {})]),
        AssistantTurn(text="Tôi không làm được việc đó."),
    ])
    assert agent.run("làm gì đó lạ").text == "Tôi không làm được việc đó."


def test_tool_error_fed_back():
    actions = make_actions()
    actions.open_application.side_effect = RuntimeError("app not found")
    agent = make_agent([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "xyz"})]),
        AssistantTurn(text="Không mở được ứng dụng đó."),
    ], actions=actions)
    assert agent.run("mở xyz").text == "Không mở được ứng dụng đó."


def test_stops_at_max_iterations():
    always_tool = [AssistantTurn(tool_calls=[ToolCall(f"t{i}", "set_volume", {"change": 1})])
                   for i in range(10)]
    agent = make_agent(always_tool, max_iterations=3)
    assert "chưa hoàn tất" in agent.run("cứ tăng âm lượng mãi").text


# --------------------------- Cảm xúc do LLM --------------------------- #

def test_parses_emotion_tag_and_strips():
    agent = make_agent([AssistantTurn(text="Đã mở Chrome.\n#emotion: happy")])
    reply = agent.run("mở chrome")
    assert reply.emotion == "happy"
    assert reply.text == "Đã mở Chrome." and "#emotion" not in reply.text


def test_emotion_none_without_tag():
    reply = make_agent([AssistantTurn(text="Xin chào!")]).run("chào")
    assert reply.emotion is None


def test_emotion_sad_tag():
    reply = make_agent([AssistantTurn(text="Xin lỗi.\n#emotion: sad")]).run("x")
    assert reply.emotion == "sad" and reply.text == "Xin lỗi."


# --------------------------- Bộ nhớ hội thoại --------------------------- #

def test_remembers_previous_turns():
    llm = FakeLLMClient([AssistantTurn(text="Chào Anh."), AssistantTurn(text="Bạn tên Anh.")])
    agent = Agent(llm, build_default_registry(make_actions()))
    agent.run("tôi tên Anh")
    agent.run("tôi tên gì?")
    texts = [m.text for m in llm.last_messages]
    assert "tôi tên Anh" in texts and "Chào Anh." in texts and "tôi tên gì?" in texts


def test_history_trimmed_to_cap():
    script = [AssistantTurn(text=f"trả lời {i}") for i in range(10)]
    agent = make_agent(script, max_history_turns=2)
    for i in range(5):
        agent.run(f"câu {i}")
    # cap = 2 lượt * 2 = 4 message
    assert len(agent.history) == 4


def test_memory_file_roundtrip():
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    try:
        a1 = Agent(FakeLLMClient([AssistantTurn(text="ok1")]),
                   build_default_registry(make_actions()), memory_path=path)
        a1.run("câu ghi nhớ")
        a2 = Agent(FakeLLMClient([AssistantTurn(text="ok2")]),
                   build_default_registry(make_actions()), memory_path=path)
        assert any(m.text == "câu ghi nhớ" for m in a2.history)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_clear_memory():
    agent = make_agent([AssistantTurn(text="ok")])
    agent.run("gì đó")
    agent.clear_memory()
    assert agent.history == []


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
