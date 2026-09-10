"""
Unit test cho Agent (vòng lặp tool-calling, bộ nhớ, cảm xúc).

Agent được tiêm LLM giả (FakeLLMClient) chạy theo kịch bản + actions mock — không
cần API key, mạng, hay SDK. run() trả AgentReply(text, emotion).
"""

from conftest import registry_with

import os
import tempfile
from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

from agent.agent import Agent, _clean_text
from llm.client import AssistantTurn, Message, ToolCall



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


def test_clean_removes_blank_lines():
    """Dòng trống giữa câu trả lời = khoảng hở khi nhìn, quãng lặng khi nghe đọc."""
    out = _clean_text("Đã mở Chrome.\n\nBạn cần gì nữa không?")
    assert out == "Đã mở Chrome.\nBạn cần gì nữa không?"


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
    return Agent(FakeLLMClient(script), registry_with(actions=actions), **kwargs)


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
    agent = Agent(llm, registry_with(actions=actions))
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
    agent = Agent(llm, registry_with(actions=actions))
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
    agent = Agent(llm, registry_with(actions=actions))
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
    agent = Agent(llm, registry_with(actions=actions))
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
    agent = Agent(llm, registry_with(actions=actions))
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
    agent = Agent(llm, registry_with(actions=actions))
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
    agent = Agent(llm, registry_with(actions=actions))
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
    agent = Agent(llm, registry_with(actions=actions))
    agent.run("đóng chrome")
    reply = agent.run("mở notepad")
    actions.close_application.assert_not_called()           # KHÔNG đóng nhầm
    actions.open_application.assert_called_once_with("notepad")
    assert agent.pending is None and reply.text == "Đã mở Notepad."


# ------------------ Xem trước nội dung hành động chờ (panel nháp email) ------------------ #

def _mail_registry(sent):
    """Registry có một tool 'send_mail' destructive kèm preview kiểu email."""
    from agent.tools import Tool
    from actions.email_draft import email_draft, say_draft
    reg = registry_with(actions=make_actions())
    reg.register(Tool(
        name="send_mail",
        description="gửi mail",
        input_schema={"type": "object", "properties": {}},
        handler=lambda **kw: sent.append(kw) or "Đã gửi email tới sep@x.com.",
        destructive=True,
        confirm_message=lambda **a: say_draft(email_draft(a) or {}),
        preview=lambda **a: email_draft(a),
    ))
    return reg


_MAIL_ARGS = {"to": "sep@x.com", "subject": "Xin nghỉ phép", "body": "Kính gửi anh..."}


def test_pending_email_is_shown_not_read_aloud():
    shown, sent = [], []
    llm = FakeLLMClient([AssistantTurn(tool_calls=[ToolCall("t1", "send_mail", _MAIL_ARGS)])])
    agent = Agent(llm, _mail_registry(sent), on_pending=shown.append)
    reply = agent.run("gửi mail xin nghỉ phép cho sếp")

    assert sent == []                                   # CHƯA gửi
    assert shown == [_MAIL_ARGS]                        # nháp đã lên panel
    assert "màn hình" in reply.text.lower()             # giọng chỉ mời NHÌN
    assert "Kính gửi anh" not in reply.text             # KHÔNG đọc thân thư


def test_panel_send_button_runs_the_same_tool():
    shown, sent = [], []
    llm = FakeLLMClient([AssistantTurn(tool_calls=[ToolCall("t1", "send_mail", _MAIL_ARGS)])])
    agent = Agent(llm, _mail_registry(sent), on_pending=shown.append)
    agent.run("gửi mail cho sếp")
    result = agent.confirm_pending("yes")

    assert sent == [_MAIL_ARGS] and "Đã gửi" in result
    assert agent.pending is None
    assert shown[-1] is None                            # panel được dẹp sau khi xong
    assert llm.calls == 1                               # chốt bằng nút không tốn lượt LLM


def test_panel_cancel_button_does_not_send():
    shown, sent = [], []
    llm = FakeLLMClient([AssistantTurn(tool_calls=[ToolCall("t1", "send_mail", _MAIL_ARGS)])])
    agent = Agent(llm, _mail_registry(sent), on_pending=shown.append)
    agent.run("gửi mail cho sếp")
    result = agent.confirm_pending("no")

    assert sent == [] and agent.pending is None
    assert "bỏ qua" in result.lower() and shown[-1] is None


def test_non_destructive_tool_with_draft_is_still_gated():
    """HỒI QUY: 'viết mail ...' -> chỉ đọc, không hiện panel.

    Tool LƯU NHÁP không mang từ khoá GHI nào nên `destructive=False`. Trước bản vá, cổng
    duyệt chỉ nhìn `destructive` -> không chặn, không panel, thư nháp lưu thẳng. Giờ chỉ
    cần DỰNG ĐƯỢC bản xem trước là phải dừng lại cho người dùng nhìn.
    """
    from agent.tools import Tool
    from actions.email_draft import email_draft, say_draft
    saved = []
    reg = registry_with(actions=make_actions())
    reg.register(Tool(
        name="mail_draft", description="lưu nháp",
        input_schema={"type": "object", "properties": {}},
        handler=lambda **kw: saved.append(kw) or "Đã lưu nháp.",
        destructive=False,                       # <- heuristic tên xếp là 'chỉ đọc'
        confirm_message=lambda **a: say_draft(email_draft(a), action="draft"),
        preview=lambda **a: email_draft(a),
    ))
    shown = []
    args = {"to": "", "subject": "Xin hướng dẫn đồ án tốt nghiệp",
            "body": "Kính gửi thầy, em xin phép..."}
    llm = FakeLLMClient([AssistantTurn(tool_calls=[ToolCall("t1", "mail_draft", args)])])
    agent = Agent(llm, reg, on_pending=shown.append)
    reply = agent.run("viết mail xin hướng dẫn đồ án tốt nghiệp")

    assert saved == []                            # dừng lại, chưa lưu
    assert shown == [args]                        # panel ĐÃ hiện dù tool không destructive
    assert "lưu nháp" in reply.text.lower()       # nói đúng việc: lưu nháp, không phải gửi
    assert "màn hình" in reply.text.lower()


def test_read_only_tool_with_null_preview_runs_normally():
    """Cổng duyệt mới KHÔNG được chặn nhầm tool chỉ đọc có gắn preview trả None."""
    from agent.tools import Tool
    ran = []
    reg = registry_with(actions=make_actions())
    reg.register(Tool(
        name="list_mail", description="đọc mail",
        input_schema={"type": "object", "properties": {}},
        handler=lambda **kw: ran.append(kw) or "Có 3 thư mới.",
        preview=lambda **a: None,
    ))
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "list_mail", {})]),
        AssistantTurn(text="Bạn có 3 thư mới."),
    ])
    agent = Agent(llm, reg, on_pending=lambda _p: None)
    reply = agent.run("có mail mới không")
    assert ran == [{}] and reply.text == "Bạn có 3 thư mới."


def test_confirm_pending_without_anything_pending():
    assert Agent(FakeLLMClient([]), _mail_registry([])).confirm_pending("yes") is None


def test_voice_confirmation_also_closes_the_panel():
    # Nói 'có' và bấm nút phải đi CÙNG một đường; panel không được để lại lơ lửng.
    shown, sent = [], []
    llm = FakeLLMClient([AssistantTurn(tool_calls=[ToolCall("t1", "send_mail", _MAIL_ARGS)])])
    agent = Agent(llm, _mail_registry(sent), on_pending=shown.append)
    agent.run("gửi mail cho sếp")
    reply = agent.run("có")

    assert sent == [_MAIL_ARGS] and shown[-1] is None
    assert "Đã gửi" in reply.text


def test_dropping_pending_closes_the_panel():
    shown, sent = [], []
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "send_mail", _MAIL_ARGS)]),
        AssistantTurn(text="Đã mở Notepad."),
    ])
    agent = Agent(llm, _mail_registry(sent), on_pending=shown.append)
    agent.run("gửi mail cho sếp")
    agent.run("mở notepad")

    assert sent == [] and shown[-1] is None


def test_destructive_without_preview_asks_as_before():
    # close_app không có preview -> không panel, không câu 'xem trên màn hình'.
    shown = []
    actions = make_actions()
    actions.close_application.return_value = "Đã đóng Chrome."
    llm = FakeLLMClient([
        AssistantTurn(tool_calls=[ToolCall("t1", "close_app", {"app_name": "chrome"})]),
    ])
    agent = Agent(llm, registry_with(actions=actions), on_pending=shown.append)
    reply = agent.run("đóng chrome")
    assert shown == [None] and "màn hình" not in reply.text.lower()
    assert "chắc" in reply.text.lower()


def test_broken_preview_does_not_break_confirmation():
    from agent.tools import Tool
    reg = registry_with(actions=make_actions())
    reg.register(Tool(
        name="boom", description="x", input_schema={"type": "object", "properties": {}},
        handler=lambda **kw: "xong", destructive=True,
        preview=lambda **a: (_ for _ in ()).throw(RuntimeError("hỏng")),
    ))
    llm = FakeLLMClient([AssistantTurn(tool_calls=[ToolCall("t1", "boom", {})])])
    agent = Agent(llm, reg, on_pending=lambda _p: None)
    assert "chắc" in agent.run("làm đi").text.lower() and agent.pending is not None


def test_broken_sink_does_not_break_confirmation():
    def explode(_payload):
        raise RuntimeError("panel hỏng")

    llm = FakeLLMClient([AssistantTurn(tool_calls=[ToolCall("t1", "send_mail", _MAIL_ARGS)])])
    agent = Agent(llm, _mail_registry([]), on_pending=explode)
    reply = agent.run("gửi mail cho sếp")
    # Panel hỏng -> mất phần NHÌN, nhưng xác nhận bằng giọng vẫn còn nguyên.
    assert agent.pending is not None and "chắc" in reply.text.lower()
    assert "màn hình" not in reply.text.lower()


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
    def __init__(self, summary, ten=None):
        self._summary = summary
        self._ten = ten
    def summary(self, query=None):
        return self._summary
    def resolve(self, text):
        from memory.profile import thay_tham_chieu
        return thay_tham_chieu(text, {"name": self._ten})


def test_profile_summary_injected_into_system():
    llm = FakeLLMClient([AssistantTurn(text="Chào Nam!")])
    agent = Agent(llm, registry_with(actions=make_actions()),
                  profile=_FakeProfile("Tên người dùng: Nam."))
    agent.run("chào")
    assert "Tên người dùng: Nam." in llm.last_system


def test_empty_profile_not_injected():
    llm = FakeLLMClient([AssistantTurn(text="Chào!")])
    agent = Agent(llm, registry_with(actions=make_actions()), profile=_FakeProfile(""))
    agent.run("chào")
    # Không có tóm tắt -> system không bị thêm tiền tố trống/xuống dòng
    assert llm.last_system and not llm.last_system.startswith("\n")


# --------------------------- Persona + tâm trạng --------------------------- #

def test_persona_and_mood_injected_into_system():
    from agent.persona import PersonaState, MoodState
    llm = FakeLLMClient([AssistantTurn(text="Chào bạn nhé!")])
    persona = PersonaState(provider="ollama", persist=False)
    mood = MoodState(baseline_valence=0.2)
    agent = Agent(llm, registry_with(actions=make_actions()), persona=persona, mood=mood)
    agent.run("chào")
    assert "Văn phong" in llm.last_system and "Tâm trạng hiện tại" in llm.last_system


def test_mood_drives_reply_emotion_positive():
    from agent.persona import PersonaState, MoodState
    # Thẻ #emotion=happy (làm được việc) + câu user tích cực -> mood đẩy pose 'happy'
    llm = FakeLLMClient([AssistantTurn(text="Xong rồi!\n#emotion: happy")])
    persona = PersonaState(provider="ollama", persist=False)
    agent = Agent(llm, registry_with(actions=make_actions()),
                  persona=persona, mood=MoodState(baseline_valence=0.2))
    reply = agent.run("tuyệt quá cảm ơn bạn")
    assert reply.emotion == "happy"


def test_persona_familiarity_grows_with_interaction():
    from agent.persona import PersonaState, MoodState
    persona = PersonaState(provider="ollama", persist=False)
    start = persona.familiarity()
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(5)]),
                  registry_with(actions=make_actions()),
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
    def resolve(self, text):
        return text
    def add_auto_fact(self, fact):
        self.facts.append(fact)


def _agent_cung_co(profile, trich="Thích uống trà", **kw):
    return Agent(FakeLLMClient([AssistantTurn(text=f"trả lời {i}") for i in range(10)]),
                 registry_with(actions=make_actions()),
                 profile=profile, auto_extract=True, consolidate_every=1,
                 max_history_turns=1, extractor=lambda transcript: trich, **kw)


def test_MAC_DINH_khong_tu_ghi_su_that_ben_vung(monkeypatch):
    """`LTM_AUTO_FACTS` tắt sẵn: trợ lý chỉ nhớ điều người dùng CHỦ ĐỘNG bảo nhớ.

    Đây là trường dữ liệu TỰ DO — sức khoẻ, tài chính, quan hệ đều rơi vào đây — mà lại
    được ghi khi người dùng không hề yêu cầu, rồi bơm vào mọi prompt sau đó.
    """
    profile = _CapturingProfile()
    agent = _agent_cung_co(profile)
    agent.run("tôi hay uống trà buổi sáng")
    agent.run("câu khác")
    assert profile.facts == []


def test_bat_LTM_AUTO_FACTS_thi_ghi_nhu_cu(monkeypatch):
    from utils.config import config
    monkeypatch.setattr(config, "LTM_AUTO_FACTS", True)
    profile = _CapturingProfile()
    agent = _agent_cung_co(profile)
    agent.run("tôi hay uống trà buổi sáng")
    agent.run("câu khác")
    assert "Thích uống trà" in profile.facts


def test_auto_tune_nudges_persona_traits():
    from agent.persona import PersonaState, MoodState
    persona = PersonaState(provider="ollama", persist=False)
    h0, f0 = persona._trait("humor"), persona._trait("formality")
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(10)]),
                  registry_with(actions=make_actions()),
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
                  registry_with(actions=make_actions()),
                  persona=persona, mood=MoodState(), auto_tune=False,
                  consolidate_every=1, max_history_turns=1,
                  persona_tuner=lambda transcript, traits: "humor: +")
    agent.run("a"); agent.run("b")
    assert persona._trait("humor") == h0           # tắt -> không đổi


def test_no_consolidation_when_auto_extract_off():
    profile = _CapturingProfile()
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(10)]),
                  registry_with(actions=make_actions()),
                  profile=profile, auto_extract=False, consolidate_every=1,
                  max_history_turns=1, extractor=lambda t: "Không nên lưu")
    agent.run("a"); agent.run("b"); agent.run("c")
    assert profile.facts == []                   # tắt -> không trích gì


def test_consolidation_survives_extractor_error():
    profile = _CapturingProfile()

    def _boom(transcript):
        raise RuntimeError("model lỗi")
    agent = Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(10)]),
                  registry_with(actions=make_actions()),
                  profile=profile, auto_extract=True, consolidate_every=1,
                  max_history_turns=1, extractor=_boom)
    agent.run("a"); reply = agent.run("b")       # trích lỗi KHÔNG được làm vỡ luồng
    assert reply.text == "r1" and profile.facts == []


# --------------------------- Thói quen (học từ hành vi lặp lại) --------------------------- #

class _CapturingHabits:
    """Kho thói quen giả — chỉ ghi lại lời gọi để test, không đụng file."""

    def __init__(self, text=""):
        self.ghi = []
        self.text = text

    def record(self, value, label_template):
        self.ghi.append((value, label_template))

    def summary(self):
        return self.text


def test_habit_recorded_after_successful_tool():
    """Tool có khai báo `habit` chạy xong -> đếm thêm một lần cho tham số của nó."""
    habits = _CapturingHabits()
    agent = make_agent([AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "Chrome"})]),
                        AssistantTurn(text="Đã mở Chrome.")], habits=habits)
    agent.run("mở chrome")
    assert habits.ghi == [("Chrome", "mở {}")]


def test_habit_not_recorded_when_tool_fails():
    """Mở app thất bại KHÔNG phải một lần dùng — đếm vào là bịa thói quen."""
    actions = make_actions()
    actions.open_application.side_effect = RuntimeError("không mở được")
    habits = _CapturingHabits()
    agent = make_agent([AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "Chrome"})]),
                        AssistantTurn(text="Xin lỗi.")], actions=actions, habits=habits)
    agent.run("mở chrome")
    assert habits.ghi == []


def test_tool_without_habit_records_nothing():
    habits = _CapturingHabits()
    agent = make_agent([AssistantTurn(tool_calls=[ToolCall("t1", "set_volume", {"change": 20})]),
                        AssistantTurn(text="Xong.")], habits=habits)
    agent.run("tăng âm lượng")
    assert habits.ghi == []


def test_habits_summary_goes_into_system_prompt():
    """Đây là cả mục đích của tính năng: hỏi 'tôi hay nghe gì' phải có sẵn đáp án."""
    llm = FakeLLMClient([AssistantTurn(text="Cậu hay nghe bài đó.")])
    agent = Agent(llm, registry_with(actions=make_actions()),
                  habits=_CapturingHabits("Thói quen: hay nghe 'Chúng ta của hiện tại' (5 lần)."))
    agent.run("tôi hay nghe nhạc gì?")
    assert "Chúng ta của hiện tại" in llm.last_system


def test_broken_habit_store_does_not_break_turn():
    class _Vo(_CapturingHabits):
        def record(self, value, label_template):
            raise RuntimeError("kho hỏng")

        def summary(self):
            raise RuntimeError("kho hỏng")

    agent = make_agent([AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {"app_name": "Chrome"})]),
                        AssistantTurn(text="Đã mở Chrome.")], habits=_Vo())
    assert agent.run("mở chrome").text == "Đã mở Chrome."


# --------------------------- Củng cố nốt lúc đóng phiên --------------------------- #

def _agent_de_cung_co(profile, **kwargs):
    return Agent(FakeLLMClient([AssistantTurn(text=f"r{i}") for i in range(10)]),
                 registry_with(actions=make_actions()),
                 profile=profile, auto_extract=True, consolidate_every=99,
                 extractor=lambda transcript: "Thích uống trà", **kwargs)


def test_flush_memory_consolidates_leftover_turns(monkeypatch):
    """Phiên ngắn: chưa lượt nào bị đẩy ra, nhưng tắt app là mất hết -> phải trích nốt.

    Không có bước này thì mặc dù auto_extract BẬT, một phiên nói vài câu rồi tắt sẽ không
    học được gì — đúng lý do trợ lý mãi không biết người dùng thích nghe nhạc nào.
    """
    from utils.config import config
    monkeypatch.setattr(config, "LTM_AUTO_FACTS", True)   # test đường ống, không phải chính sách
    profile = _CapturingProfile()
    agent = _agent_de_cung_co(profile)
    agent.run("tôi hay nghe nhạc Trịnh")
    assert profile.facts == []                   # chưa tới ngưỡng củng cố giữa phiên
    agent.flush_memory()
    assert "Thích uống trà" in profile.facts


def test_flush_memory_only_runs_once(monkeypatch):
    from utils.config import config
    monkeypatch.setattr(config, "LTM_AUTO_FACTS", True)
    profile = _CapturingProfile()
    agent = _agent_de_cung_co(profile)
    agent.run("a")
    agent.flush_memory()
    agent.flush_memory()
    assert profile.facts == ["Thích uống trà"]


def test_flush_memory_bo_qua_luot_con_luu_file(tmp_path):
    """STM có lưu file thì lượt còn lại chưa mất -> để phiên sau trích, khỏi trích hai lần."""
    profile = _CapturingProfile()
    agent = _agent_de_cung_co(profile, memory_path=str(tmp_path / "stm.json"))
    agent.run("a")
    agent.flush_memory()
    assert profile.facts == []


def test_flush_memory_khong_lam_gi_khi_tat_auto_extract():
    profile = _CapturingProfile()
    agent = Agent(FakeLLMClient([AssistantTurn(text="r")]),
                  registry_with(actions=make_actions()), profile=profile,
                  auto_extract=False, extractor=lambda t: "Không nên lưu")
    agent.run("a")
    agent.flush_memory()
    assert profile.facts == []


# --------------------------- Bộ nhớ hội thoại --------------------------- #

def test_remembers_previous_turns():
    llm = FakeLLMClient([AssistantTurn(text="Chào Anh."), AssistantTurn(text="Bạn tên Anh.")])
    agent = Agent(llm, registry_with(actions=make_actions()))
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
                   registry_with(actions=make_actions()), memory_path=path)
        a1.run("câu ghi nhớ")
        a2 = Agent(FakeLLMClient([AssistantTurn(text="ok2")]),
                   registry_with(actions=make_actions()), memory_path=path)
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
# `prompt_eval` (đọc prompt) chiếm phần lớn chi phí một lượt LLM, và runtime tái dùng
# KV cache theo TIỀN TỐ CHUNG. Thứ gì đổi mỗi lượt mà nằm ở ĐẦU prompt sẽ phá cache của TOÀN BỘ
# prompt lẫn lịch sử hội thoại phía sau.
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
    agent = Agent(FakeLLMClient([]), registry_with(actions=make_actions()),
                  profile=_QueryProfile())
    system = agent._compose_system("BASE_VA_CASE_ON_DINH", "mở chrome")
    assert system.startswith("BASE_VA_CASE_ON_DINH")


def test_system_prompt_prefix_stable_across_turns():
    """Đổi phút VÀ đổi câu hỏi -> tiền tố chung vẫn phải > 95% khối ổn định."""
    from unittest.mock import patch
    stable = "HUONG DAN CO DINH. " * 60          # ~1.100 ký tự, cỡ BASE+CASE thật
    agent = Agent(FakeLLMClient([]), registry_with(actions=make_actions()),
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
    agent = Agent(FakeLLMClient([]), registry_with(actions=make_actions()),
                  profile=_QueryProfile())
    with patch("agent.agent.format_now", return_value="MOC_THOI_GIAN"):
        system = agent._compose_system(stable, "xin chào")
    assert system.index(stable) < system.index("MOC_THOI_GIAN")
    assert system.index("MOC_THOI_GIAN") < system.index("Ngữ cảnh cho")
