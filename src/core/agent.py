"""
Agent — vòng lặp tool-calling, tách khỏi I/O và khỏi nhà cung cấp LLM.

Có thêm:
  - Bộ nhớ hội thoại: nhớ các lượt text (user/assistant) qua nhiều lần run() để LLM
    hiểu ngữ cảnh; giới hạn số lượt; tùy chọn lưu file để sống qua restart.
  - Cảm xúc do LLM quyết: LLM kết thúc câu trả lời bằng thẻ '#emotion: happy|neutral|
    sad'; Agent tách thẻ, trả AgentReply(text sạch, emotion).

Phụ thuộc tiêm vào (llm, registry) nên test được với LLM giả.
"""

import json
import os
import re
from dataclasses import dataclass

from core.llm_client import LLMClient, Message, ToolResult
from core.tools import ToolRegistry
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SYSTEM = (
    "Bạn là trợ lý điều khiển máy tính bằng tiếng Việt.\n"
    "Với MỌI yêu cầu hành động (mở/đóng app, chỉnh âm lượng/độ sáng, xem thông tin "
    "máy, tìm kiếm/tra cứu web, phát nhạc, lập lịch nhắc, tắt/khởi động lại máy...), "
    "BẮT BUỘC gọi ngay công cụ phù hợp với đúng tham số. KHÔNG hỏi lại nếu lệnh đã "
    "đủ rõ. Nhớ ngữ cảnh các lượt trước.\n"
    "Trả lời ngắn gọn, thân thiện bằng tiếng Việt. Kết thúc mỗi câu trả lời bằng "
    "đúng một thẻ trên dòng riêng: '#emotion: happy' hoặc '#emotion: neutral' hoặc "
    "'#emotion: sad' — thể hiện cảm xúc phù hợp với nội dung."
)

_EMO_RE = re.compile(r"#\s*emotion\s*:\s*(happy|neutral|sad)\b", re.IGNORECASE)


@dataclass
class AgentReply:
    text: str
    emotion: str = None      # do LLM gắn; None nếu không có -> UI tự đoán


def _split_emotion(text):
    """Tách thẻ #emotion khỏi text. Trả (text_sạch, emotion|None)."""
    matches = list(_EMO_RE.finditer(text or ""))
    if not matches:
        return (text or "").strip(), None
    emotion = matches[-1].group(1).lower()
    clean = _EMO_RE.sub("", text).strip()
    return clean, emotion


class Agent:
    def __init__(self, llm: LLMClient, registry: ToolRegistry,
                 system: str = DEFAULT_SYSTEM, max_iterations: int = 6,
                 max_history_turns: int = 10, memory_path: str = None):
        self.llm = llm
        self.registry = registry
        self.system = system
        self.max_iterations = max_iterations
        self.max_history_turns = max_history_turns
        self.memory_path = memory_path
        self.history = []            # chỉ lượt text: Message(user)/Message(assistant)
        self._load_memory()

    def run(self, user_text: str) -> AgentReply:
        """Chạy một lượt qua vòng lặp tool-calling, có nhớ ngữ cảnh trước đó."""
        # Bắt đầu từ lịch sử + lượt mới
        messages = list(self.history) + [Message(role="user", text=user_text)]
        tools = self.registry.specs()

        final_text = ""
        for _ in range(self.max_iterations):
            turn = self.llm.generate(system=self.system, messages=messages, tools=tools)
            messages.append(Message(role="assistant", text=turn.text,
                                    tool_calls=turn.tool_calls))

            if not turn.wants_tools:
                final_text = turn.text
                break

            results = [self._run_tool(c) for c in turn.tool_calls]
            messages.append(Message(role="user", tool_results=results))
        else:
            logger.warning("Agent đạt giới hạn %d vòng công cụ", self.max_iterations)
            final_text = "Xin lỗi, yêu cầu quá phức tạp nên tôi chưa hoàn tất được."

        text, emotion = _split_emotion(final_text)
        self._remember(user_text, text)
        return AgentReply(text=text, emotion=emotion)

    # ------------------------- bộ nhớ ------------------------- #
    def _remember(self, user_text, assistant_text):
        self.history.append(Message(role="user", text=user_text))
        self.history.append(Message(role="assistant", text=assistant_text))
        cap = self.max_history_turns * 2
        if len(self.history) > cap:
            self.history = self.history[-cap:]
        self._save_memory()

    def clear_memory(self):
        self.history = []
        self._save_memory()

    def _load_memory(self):
        if not self.memory_path or not os.path.exists(self.memory_path):
            return
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.history = [Message(role=m["role"], text=m.get("text", "")) for m in data]
        except (OSError, ValueError, KeyError) as e:
            logger.warning("Không đọc được bộ nhớ hội thoại: %s", e)

    def _save_memory(self):
        if not self.memory_path:
            return
        try:
            os.makedirs(os.path.dirname(self.memory_path), exist_ok=True)
            with open(self.memory_path, "w", encoding="utf-8") as f:
                json.dump([{"role": m.role, "text": m.text} for m in self.history],
                          f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Không lưu được bộ nhớ hội thoại: %s", e)

    # ------------------------- tool ------------------------- #
    def _run_tool(self, call) -> ToolResult:
        try:
            output = self.registry.run(call.name, call.arguments)
            return ToolResult(tool_call_id=call.id, name=call.name, content=str(output))
        except KeyError:
            logger.error("LLM gọi tool không tồn tại: %s", call.name)
            return ToolResult(tool_call_id=call.id, name=call.name,
                              content=f"Không có công cụ tên '{call.name}'.",
                              is_error=True)
        except Exception as e:  # tool lỗi -> báo lại LLM thay vì làm vỡ vòng lặp
            logger.error("Tool %s lỗi: %s", call.name, e)
            return ToolResult(tool_call_id=call.id, name=call.name,
                              content=f"Lỗi khi chạy: {e}", is_error=True)
