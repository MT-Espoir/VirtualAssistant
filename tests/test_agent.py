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

from agent.agent import Agent, _clean_text
from llm.client import AssistantTurn, Message, ToolCall
from agent.tools import build_default_registry


# --------------------------- _clean_text (dọn rác model 3B) --------------------------- #

def test_clean_strips_cjk():
    assert _clean_text("Đã đặt âm lượng 35%.现在是168") == "Đã đặt âm lượng 35%.168"
    assert _clean_text("Xin chào 你好 bạn") == "Xin chào  bạn".replace("  ", " ")


def test_clean_keeps_vietnamese():
    s = "Đã mở Chrome cho bạn nhé!"
    assert _clean_text(s) == s


def test_clean_removes_duplicate_lines():
    dup = "Tôi đã tìm kiếm.\n1. Video A\nTôi đã tìm kiếm.\n1. Video A"
    assert _clean_text(dup) == "Tôi đã tìm kiếm.\n1. Video A"


def test_clean_none_safe():
    assert _clean_text(None) == "" and _clean_text("") == ""


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


def test_action_tool_then_model_composes_reply():
    # Sau khi chạy tool hành động, model LUÔN có lượt soạn lời (không tự đoán "đã xong"
    # hộ model) -> câu trả lời do model soạn, tốn 2 lượt LLM.
    actions = make_actions()
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "chrome"})]),
        AssistantTurn(text="Đã mở Chrome cho bạn."),
    ])
    agent = Agent(llm, build_default_registry(actions))
    reply = agent.run("mở chrome")
    actions.open_application.assert_called_once_with("chrome")
    assert reply.text == "Đã mở Chrome cho bạn." and llm.calls == 2


def test_multiple_tools_in_one_turn_then_compose():
    # Model phát nhiều tool trong MỘT lượt: chạy đủ, rồi lượt sau soạn lời kết.
    actions = make_actions()
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[
            ToolCall("t1", "open_app", {"app_name": "chrome"}),
            ToolCall("t2", "set_volume", {"change": 20})]),
        AssistantTurn(text="Đã mở Chrome và tăng âm lượng."),
    ])
    agent = Agent(llm, build_default_registry(actions))
    reply = agent.run("mở chrome và tăng âm lượng 20%")
    actions.open_application.assert_called_once_with("chrome")
    actions.control_volume.assert_called_once_with(level=None, change=20)
    assert reply.text == "Đã mở Chrome và tăng âm lượng." and llm.calls == 2


def test_multi_step_request_chains_tools():
    # Yêu cầu nhiều bước, model phát MỖI LƯỢT MỘT tool: agent lặp cho model gọi đủ
    # các bước (không dừng sau bước đầu) rồi soạn lời kết ở lượt cuối.
    actions = make_actions()
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "chrome"})]),
        AssistantTurn(tool_calls=[ToolCall("t2", "set_volume", {"change": 20})]),
        AssistantTurn(text="Đã mở Chrome và tăng âm lượng.\n#emotion: happy"),
    ])
    agent = Agent(llm, build_default_registry(actions))
    reply = agent.run("mở chrome sau đó tăng âm lượng")
    actions.open_application.assert_called_once_with("chrome")
    actions.control_volume.assert_called_once_with(level=None, change=20)
    assert llm.calls == 3 and reply.emotion == "happy"


def test_tool_returning_raw_data_gets_summarized():
    # Tool trả dữ liệu thô (wikipedia) -> model có lượt diễn đạt lại thành câu trả lời.
    actions = make_actions()
    actions.wikipedia_lookup.return_value = "Nội dung dài về AI..."
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "wikipedia_lookup", {"topic": "AI"})]),
        AssistantTurn(text="Tóm tắt: AI là..."),
    ])
    agent = Agent(llm, build_default_registry(actions))
    reply = agent.run("AI là gì")
    assert reply.text == "Tóm tắt: AI là..." and llm.calls == 2


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
    # Model cứ gọi tool mãi (không bao giờ dừng) -> chạm giới hạn vòng lặp.
    always_tool = [AssistantTurn(tool_calls=[ToolCall(f"t{i}", "wikipedia_lookup", {"topic": "x"})])
                   for i in range(10)]
    agent = make_agent(always_tool, max_iterations=3)
    assert "chưa hoàn tất" in agent.run("cứ tra mãi").text


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


def test_emotion_cry_tag():
    reply = make_agent([AssistantTurn(text="Dạ em xin lỗi ạ.\n#emotion: cry")]).run("x")
    assert reply.emotion == "cry" and reply.text == "Dạ em xin lỗi ạ."


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
