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
        self.last_system = None

    def generate(self, *, system, messages, tools):
        self.last_messages = messages
        self.last_system = system
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


# --------------------------- Xác nhận hành động khó hoàn tác --------------------------- #

def test_destructive_tool_asks_before_running():
    actions = make_actions()
    actions.close_application.return_value = "Đã đóng Chrome."
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "close_app", {"app_name": "chrome"})]),
    ])
    agent = Agent(llm, build_default_registry(actions))
    reply = agent.run("đóng chrome")
    actions.close_application.assert_not_called()          # CHƯA đóng
    assert agent.pending is not None
    assert "chắc" in reply.text.lower() and "chrome" in reply.text.lower()
    assert llm.calls == 1


def test_confirmation_yes_executes_without_llm():
    actions = make_actions()
    actions.close_application.return_value = "Đã đóng Chrome."
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "close_app", {"app_name": "chrome"})]),
    ])
    agent = Agent(llm, build_default_registry(actions))
    agent.run("đóng chrome")
    reply = agent.run("có")
    actions.close_application.assert_called_once_with("chrome")
    assert reply.text == "Đã đóng Chrome." and agent.pending is None
    assert llm.calls == 1                                   # lượt xác nhận không gọi LLM


def test_confirmation_no_cancels():
    actions = make_actions()
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "close_app", {"app_name": "chrome"})]),
    ])
    agent = Agent(llm, build_default_registry(actions))
    agent.run("đóng chrome")
    reply = agent.run("thôi không cần")
    actions.close_application.assert_not_called()
    assert agent.pending is None and "không làm" in reply.text.lower()


def test_unrelated_reply_drops_pending_and_handles_new_request():
    # An toàn: câu KHÔNG phải xác nhận không được kích hoạt hành động đã hoãn
    actions = make_actions()
    actions.open_application.return_value = "Đã mở Notepad."
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "close_app", {"app_name": "chrome"})]),
        AssistantTurn(tool_calls=[ToolCall("t2", "open_app", {"app_name": "notepad"})]),
        AssistantTurn(text="Đã mở Notepad."),
    ])
    agent = Agent(llm, build_default_registry(actions))
    agent.run("đóng chrome")
    reply = agent.run("mở notepad")
    actions.close_application.assert_not_called()           # KHÔNG đóng nhầm
    actions.open_application.assert_called_once_with("notepad")
    assert agent.pending is None and reply.text == "Đã mở Notepad."


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


# --------------------------- Hồ sơ người dùng bơm vào prompt --------------------------- #

class _FakeProfile:
    def __init__(self, summary):
        self._summary = summary
    def summary(self, query=None):
        return self._summary


def test_profile_summary_injected_into_system():
    llm = FakeLLMClient([AssistantTurn(text="Chào Nam!")])
    agent = Agent(llm, build_default_registry(make_actions()),
                  profile=_FakeProfile("Tên người dùng: Nam."))
    agent.run("chào")
    assert "Tên người dùng: Nam." in llm.last_system


def test_empty_profile_not_injected():
    llm = FakeLLMClient([AssistantTurn(text="Chào!")])
    agent = Agent(llm, build_default_registry(make_actions()), profile=_FakeProfile(""))
    agent.run("chào")
    # Không có tóm tắt -> system không bị thêm tiền tố trống/xuống dòng
    assert llm.last_system and not llm.last_system.startswith("\n")


# --------------------------- Persona + tâm trạng --------------------------- #

def test_persona_and_mood_injected_into_system():
    from agent.persona import PersonaState, MoodState
    llm = FakeLLMClient([AssistantTurn(text="Chào bạn nhé!")])
    persona = PersonaState(provider="ollama", persist=False)
    mood = MoodState(baseline_valence=0.2)
    agent = Agent(llm, build_default_registry(make_actions()), persona=persona, mood=mood)
    agent.run("chào")
    assert "Văn phong" in llm.last_system and "Tâm trạng hiện tại" in llm.last_system


def test_mood_drives_reply_emotion_positive():
    from agent.persona import PersonaState, MoodState
    # Thẻ #emotion=happy (làm được việc) + câu user tích cực -> mood đẩy pose 'happy'
    llm = FakeLLMClient([AssistantTurn(text="Xong rồi!\n#emotion: happy")])
    persona = PersonaState(provider="ollama", persist=False)
    agent = Agent(llm, build_default_registry(make_actions()),
                  persona=persona, mood=MoodState(baseline_valence=0.2))
    reply = agent.run("tuyệt quá cảm ơn bạn")
    assert reply.emotion == "happy"


def test_persona_familiarity_grows_with_interaction():
    from agent.persona import PersonaState, MoodState
    persona = PersonaState(provider="ollama", persist=False)
    start = persona.familiarity()
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(5)]),
                  build_default_registry(make_actions()),
                  persona=persona, mood=MoodState())
    for i in range(3):
        agent.run(f"câu {i}")
    assert persona.familiarity() > start
    assert persona.data["rapport"]["interaction_count"] == 3


def test_no_mood_keeps_tag_emotion():
    # Không có mood -> giữ nguyên cảm xúc từ thẻ (không phá hành vi cũ)
    reply = make_agent([AssistantTurn(text="Đã mở.\n#emotion: happy")]).run("mở chrome")
    assert reply.emotion == "happy"


# --------------------------- Củng cố STM -> LTM (auto-extract) --------------------------- #

class _CapturingProfile:
    def __init__(self):
        self.facts = []
    def summary(self, query=None):
        return ""
    def add_auto_fact(self, fact):
        self.facts.append(fact)


def test_consolidation_extracts_facts_into_ltm():
    profile = _CapturingProfile()
    # Bộ trích giả: trả 1 sự thật, không cần LLM.
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"trả lời {i}") for i in range(10)]),
                  build_default_registry(make_actions()),
                  profile=profile, auto_extract=True, consolidate_every=1,
                  max_history_turns=1, extractor=lambda transcript: "Thích uống trà")
    agent.run("tôi hay uống trà buổi sáng")     # lượt 1: chưa đẩy ra
    agent.run("câu khác")                        # lượt 2: đẩy lượt 1 -> đủ ngưỡng -> củng cố
    assert "Thích uống trà" in profile.facts


def test_auto_tune_nudges_persona_traits():
    from agent.persona import PersonaState, MoodState
    persona = PersonaState(provider="ollama", persist=False)
    h0, f0 = persona._trait("humor"), persona._trait("formality")
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(10)]),
                  build_default_registry(make_actions()),
                  persona=persona, mood=MoodState(),
                  auto_tune=True, consolidate_every=1, max_history_turns=1,
                  persona_tuner=lambda transcript, traits: "humor: +\nformality: -")
    agent.run("a"); agent.run("b")                 # đẩy lượt -> củng cố -> nudge
    assert persona._trait("humor") > h0 and persona._trait("formality") < f0


def test_auto_tune_off_keeps_traits():
    from agent.persona import PersonaState, MoodState
    persona = PersonaState(provider="ollama", persist=False)
    h0 = persona._trait("humor")
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(10)]),
                  build_default_registry(make_actions()),
                  persona=persona, mood=MoodState(), auto_tune=False,
                  consolidate_every=1, max_history_turns=1,
                  persona_tuner=lambda transcript, traits: "humor: +")
    agent.run("a"); agent.run("b")
    assert persona._trait("humor") == h0           # tắt -> không đổi


def test_no_consolidation_when_auto_extract_off():
    profile = _CapturingProfile()
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(10)]),
                  build_default_registry(make_actions()),
                  profile=profile, auto_extract=False, consolidate_every=1,
                  max_history_turns=1, extractor=lambda t: "Không nên lưu")
    agent.run("a"); agent.run("b"); agent.run("c")
    assert profile.facts == []                   # tắt -> không trích gì


def test_consolidation_survives_extractor_error():
    profile = _CapturingProfile()

    def _boom(transcript):
        raise RuntimeError("model lỗi")
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(10)]),
                  build_default_registry(make_actions()),
                  profile=profile, auto_extract=True, consolidate_every=1,
                  max_history_turns=1, extractor=_boom)
    agent.run("a"); reply = agent.run("b")       # trích lỗi KHÔNG được làm vỡ luồng
    assert reply.text == "r1" and profile.facts == []


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


# --------------------------- Thứ tự khối trong system prompt (KV cache) --------------------------- #
#
# Bài học đo được 2026-08-22: `prompt_eval` chiếm ~83% chi phí một lượt LLM, và runtime tái dùng
# KV cache theo TIỀN TỐ CHUNG. Thứ gì đổi mỗi lượt mà nằm ở ĐẦU prompt sẽ phá cache của TOÀN BỘ
# prompt lẫn lịch sử hội thoại phía sau (đo được: 23,6s so với 3,4s).
#
# Các test dưới đây KHOÁ thứ tự đó lại. Nếu ai đó bơm thời gian/hồ sơ lên đầu lần nữa, test phải đỏ.

class _QueryProfile:
    """Hồ sơ có tóm tắt PHỤ THUỘC câu hỏi — tái hiện `UserProfile.summary(query=...)` thật."""
    def summary(self, query=None):
        return f"Ngữ cảnh cho '{query}'."


def _common_prefix_len(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def test_system_prompt_starts_with_stable_block():
    """BASE+CASE phải nằm NGAY ĐẦU — mọi khối biến động xếp sau."""
    agent = Agent(FakeLLMClient([]), build_default_registry(make_actions()),
                  profile=_QueryProfile())
    system = agent._compose_system("BASE_VA_CASE_ON_DINH", "mở chrome")
    assert system.startswith("BASE_VA_CASE_ON_DINH")


def test_system_prompt_prefix_stable_across_turns():
    """Đổi phút VÀ đổi câu hỏi -> tiền tố chung vẫn phải > 95% khối ổn định."""
    from unittest.mock import patch
    stable = "HUONG DAN CO DINH. " * 60          # ~1.100 ký tự, cỡ BASE+CASE thật
    agent = Agent(FakeLLMClient([]), build_default_registry(make_actions()),
                  profile=_QueryProfile())

    with patch("agent.agent.format_now", return_value="Bây giờ là 21:45 thứ Sáu."):
        a = agent._compose_system(stable, "tìm quán cà phê")
    with patch("agent.agent.format_now", return_value="Bây giờ là 21:46 thứ Sáu."):
        b = agent._compose_system(stable, "mở youtube")

    assert a != b, "hai lượt phải khác nhau (thời gian + hồ sơ đều đổi)"
    assert _common_prefix_len(a, b) >= len(stable) * 0.95, (
        "Tiền tố chung ngắn hơn khối ổn định -> KV cache bị phá mỗi lượt. "
        "Có ai đó vừa bơm nội dung biến động lên ĐẦU system prompt."
    )


def test_volatile_blocks_come_after_stable():
    """Thời gian và hồ sơ phải nằm SAU khối ổn định, không phải trước."""
    from unittest.mock import patch
    stable = "KHOI_ON_DINH"
    agent = Agent(FakeLLMClient([]), build_default_registry(make_actions()),
                  profile=_QueryProfile())
    with patch("agent.agent.format_now", return_value="MOC_THOI_GIAN"):
        system = agent._compose_system(stable, "xin chào")
    assert system.index(stable) < system.index("MOC_THOI_GIAN")
    assert system.index("MOC_THOI_GIAN") < system.index("Ngữ cảnh cho")
