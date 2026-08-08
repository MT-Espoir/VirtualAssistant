"""Test lối tắt 'đọc thẳng kết quả tool' (bỏ lượt LLM soạn lời).

Quan trọng nhất là nhóm KHÔNG ĐƯỢC CẮT: một lối tắt tương tự (theo cờ 'terminal') từng
bị gỡ vì làm rớt các bước sau của yêu cầu đa bước. Các test dưới chốt đúng ranh giới đó.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llm.client import AssistantTurn, ToolCall          # noqa: E402
from agent.agent import Agent                            # noqa: E402
from agent.tools import Tool, ToolRegistry               # noqa: E402


class _FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def generate(self, *, system, messages, tools):
        turn = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return turn


def _registry(speakable=True, destructive=False, boom=False):
    reg = ToolRegistry()

    def handler(**_kw):
        if boom:
            raise RuntimeError("hỏng")
        return "RAM còn trống 5.5 GB."

    reg.register(Tool(name="system_info", description="", input_schema={"type": "object"},
                      handler=handler, speakable=speakable, destructive=destructive,
                      confirm_message=(lambda **a: "xem thông tin") if destructive else None))
    reg.register(Tool(name="open_app", description="",
                      input_schema={"type": "object"},
                      handler=lambda **kw: "Đã mở Chrome.", speakable=True))
    return reg


def _agent(llm, reg, on=True):
    return Agent(llm=llm, registry=reg, router=None, max_history_turns=0,
                 skip_respond_for_speakable=on)


# --------------------------- CÓ cắt --------------------------- #

def test_shortcut_uses_tool_output_and_saves_one_call():
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "system_info", {})]),
        AssistantTurn(text="KHÔNG ĐƯỢC DÙNG LƯỢT NÀY"),
    ])
    reply = _agent(llm, _registry()).run("máy còn bao nhiêu ram")
    assert reply.text == "RAM còn trống 5.5 GB."
    assert llm.calls == 1                 # đúng 1 call thay vì 2


def test_shortcut_marks_outcome_as_success_for_mood():
    """Không có thẻ #emotion -> tâm trạng vẫn phải nhận tín hiệu 'xong tốt'."""
    mood = MagicMock()
    mood.to_pose.return_value = "happy"
    llm = _FakeLLM([AssistantTurn(tool_calls=[ToolCall("t1", "system_info", {})])])
    Agent(llm=llm, registry=_registry(), router=None, max_history_turns=0,
          skip_respond_for_speakable=True, mood=mood).run("ram")
    assert mood.update.call_args.kwargs["outcome"] == 1.0


# --------------------------- KHÔNG được cắt --------------------------- #

def test_no_shortcut_when_disabled():
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "system_info", {})]),
        AssistantTurn(text="Máy bạn còn 5.5 GB nè!"),
    ])
    reply = _agent(llm, _registry(), on=False).run("ram")
    assert reply.text == "Máy bạn còn 5.5 GB nè!" and llm.calls == 2


def test_no_shortcut_for_multiple_tools_in_one_turn():
    """R2: 2 tool cùng lượt = đang làm nhiều bước -> tuyệt đối không cắt."""
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {}),
                                  ToolCall("t2", "system_info", {})]),
        AssistantTurn(text="Đã mở Chrome và xem máy xong."),
    ])
    reply = _agent(llm, _registry()).run("mở chrome rồi xem ram")
    assert reply.text == "Đã mở Chrome và xem máy xong." and llm.calls == 2


def test_no_shortcut_after_a_tool_already_ran():
    """R2: đã có kết quả tool từ vòng trước -> đang giữa chuỗi, không được cắt ngang.

    Vòng 1 gọi tool KHÔNG speakable (nên không cắt), vòng 2 mới gọi tool speakable —
    lúc này iteration != 0 nên lối tắt phải im lặng.
    """
    reg = _registry(speakable=False)          # system_info không speakable
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "system_info", {})]),   # vòng 1
        AssistantTurn(tool_calls=[ToolCall("t2", "open_app", {})]),      # vòng 2 (speakable)
        AssistantTurn(text="Xong cả hai việc."),
    ])
    reply = _agent(llm, reg).run("xem ram rồi mở chrome")
    assert reply.text == "Xong cả hai việc." and llm.calls == 3


def test_known_limit_sequential_multi_step_gets_cut():
    """GIỚI HẠN ĐÃ BIẾT (lý do SKIP_RESPOND_FOR_SPEAKABLE mặc định TẮT).

    Model làm nhiều bước TUẦN TỰ (mỗi lượt 1 tool) sẽ bị cắt mất bước sau: ở vòng 0 chỉ
    thấy 1 tool speakable nên lối tắt tưởng đã xong. Gemini phát HẾT tool trong cùng một
    lượt nên không dính (xem test đa-tool ở trên), nhưng model khác thì có thể.
    Test này CHỐT hành vi để không ai tưởng nhầm là an toàn tuyệt đối.
    """
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "open_app", {})]),      # bước 1
        AssistantTurn(tool_calls=[ToolCall("t2", "system_info", {})]),   # bước 2 — bị bỏ
        AssistantTurn(text="Xong cả hai việc."),
    ])
    reply = _agent(llm, _registry()).run("mở chrome rồi xem ram")
    assert reply.text == "Đã mở Chrome."     # bước 2 KHÔNG chạy
    assert llm.calls == 1


def test_no_shortcut_for_non_speakable_tool():
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "system_info", {})]),
        AssistantTurn(text="Diễn giải lại cho dễ nghe."),
    ])
    reply = _agent(llm, _registry(speakable=False)).run("ram")
    assert reply.text == "Diễn giải lại cho dễ nghe." and llm.calls == 2


def test_no_shortcut_when_tool_errors():
    """Lỗi thì để LLM diễn đạt, không đọc trần chuỗi lỗi cho người dùng."""
    llm = _FakeLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "system_info", {})]),
        AssistantTurn(text="Xin lỗi, mình chưa xem được."),
    ])
    reply = _agent(llm, _registry(boom=True)).run("ram")
    assert reply.text == "Xin lỗi, mình chưa xem được." and llm.calls == 2


def test_destructive_still_asks_confirmation():
    """R3: cổng xác nhận không được lối tắt nào đi vòng qua."""
    llm = _FakeLLM([AssistantTurn(tool_calls=[ToolCall("t1", "system_info", {})])])
    agent = _agent(llm, _registry(destructive=True))
    reply = agent.run("xem ram")
    assert "chắc" in reply.text.lower() and agent.pending is not None
