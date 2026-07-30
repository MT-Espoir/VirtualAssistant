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

from llm.client import LLMClient, Message, ToolResult
from agent.tools import ToolRegistry
from voice.fast_commands import match_confirmation
from utils.logger import get_logger

logger = get_logger(__name__)

from llm import prompts

# Prompt mặc định (khi KHÔNG dùng router) — nạp base từ components/data/system_prompt.json.
DEFAULT_SYSTEM = prompts.base()

_EMO_RE = re.compile(r"#\s*emotion\s*:\s*(happy|neutral|sad|cry)\b", re.IGNORECASE)

# Chữ CJK (Trung/Nhật/Hàn) + ký tự fullwidth — model 3B hay chèn rác các ngôn ngữ này.
_CJK_RE = re.compile(r"[　-〿぀-ヿ㐀-䶿一-鿿"
                     r"가-힯＀-￯]+")


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


def _clean_text(text):
    """Dọn câu trả lời của model 3B: bỏ chữ CJK chèn bậy, bỏ dòng lặp y hệt, gọn khoảng trắng."""
    t = _CJK_RE.sub("", text or "")
    seen, lines = set(), []
    for line in t.splitlines():
        key = line.strip()
        if key and key in seen:          # bỏ dòng trùng lặp (model hay lặp cả đoạn)
            continue
        if key:
            seen.add(key)
        lines.append(line)
    t = "\n".join(lines)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


class Agent:
    def __init__(self, llm: LLMClient, registry: ToolRegistry,
                 system: str = DEFAULT_SYSTEM, max_iterations: int = 6,
                 max_history_turns: int = 10, memory_path: str = None, router=None,
                 profile=None):
        self.llm = llm
        self.registry = registry
        self.system = system
        self.max_iterations = max_iterations
        self.max_history_turns = max_history_turns
        self.memory_path = memory_path
        self.router = router         # tùy chọn: phân loại case -> thu hẹp prompt+tool
        self.profile = profile       # tùy chọn: hồ sơ người dùng -> bơm tóm tắt vào prompt
        self.history = []            # chỉ lượt text: Message(user)/Message(assistant)
        self.pending = None          # hành động khó hoàn tác đang CHỜ người dùng xác nhận
        self._load_memory()

    def run(self, user_text: str) -> AgentReply:
        """Chạy một lượt qua vòng lặp tool-calling, có nhớ ngữ cảnh trước đó."""
        # Nếu lượt trước đã hỏi xác nhận một hành động khó hoàn tác: giải quyết trước.
        if self.pending is not None:
            reply = self._resolve_pending(user_text)
            if reply is not None:
                return reply
            # None = câu này KHÔNG phải xác nhận -> đã huỷ chờ, xử lý như yêu cầu mới.

        # Router (nếu có) chọn prompt + thu hẹp tool theo loại yêu cầu; nếu không,
        # dùng prompt mặc định + toàn bộ tool.
        if self.router is not None:
            system, tools = self.router.select(user_text, self.registry)
        else:
            system, tools = self.system, self.registry.specs()

        # Bơm tóm tắt hồ sơ người dùng vào đầu system prompt -> trợ lý luôn "biết" người
        # dùng (tên, xưng hô, địa điểm mặc định) mà không tốn lượt hỏi lại.
        if self.profile is not None:
            summary = self.profile.summary()
            if summary:
                system = summary + "\n\n" + system

        messages = list(self.history) + [Message(role="user", text=user_text)]

        final_text = ""
        for _ in range(self.max_iterations):
            turn = self.llm.generate(system=system, messages=messages, tools=tools)
            messages.append(Message(role="assistant", text=turn.text,
                                    tool_calls=turn.tool_calls))

            # Model tự quyết khi nào XONG: khi không còn gọi tool nữa -> câu cuối là
            # câu trả lời. Không đoán "đã xong" hộ model (đoán sai làm rớt các bước
            # sau: 'mở A, B, C' mà không có từ nối vẫn phải chạy đủ). Đổi lại mỗi lệnh
            # tốn thêm 1 lượt LLM soạn lời — chấp nhận để đúng & dễ đoán.
            if not turn.wants_tools:
                final_text = turn.text
                break

            # Chặn hành động khó hoàn tác: nếu model định gọi tool destructive, KHÔNG
            # chạy ngay — hoãn lại + hỏi người dùng, chỉ thực thi khi họ đáp "có" ở lượt
            # sau. Chốt trong CODE nên STT/model nghe nhầm cũng không lỡ tay.
            deferred = self._find_destructive(turn.tool_calls)
            if deferred is not None:
                self.pending = deferred
                final_text = (f"Bạn có chắc muốn {deferred['phrase']} không? "
                              f"Nói 'có' để tôi làm, 'không' để bỏ qua.")
                break

            results = [self._run_tool(c) for c in turn.tool_calls]
            messages.append(Message(role="user", tool_results=results))
        else:
            logger.warning("Agent đạt giới hạn %d vòng công cụ", self.max_iterations)
            final_text = "Xin lỗi, yêu cầu quá phức tạp nên tôi chưa hoàn tất được."

        text, emotion = _split_emotion(final_text)
        text = _clean_text(text)
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
            # MEMORY_PATH có thể là tên file trơn (không thư mục) -> dirname rỗng;
            # chỉ tạo thư mục khi thực sự có đường dẫn thư mục.
            directory = os.path.dirname(self.memory_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.memory_path, "w", encoding="utf-8") as f:
                json.dump([{"role": m.role, "text": m.text} for m in self.history],
                          f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Không lưu được bộ nhớ hội thoại: %s", e)

    # ------------------------- xác nhận hành động khó hoàn tác ------------------------- #
    def _find_destructive(self, tool_calls):
        """Trả {name, arguments, phrase} cho lời gọi tool destructive ĐẦU TIÊN, hoặc None."""
        for call in tool_calls:
            if not self.registry.has(call.name):
                continue
            tool = self.registry.get(call.name)
            if not getattr(tool, "destructive", False):
                continue
            args = call.arguments or {}
            try:
                phrase = tool.confirm_message(**args) if tool.confirm_message else call.name
            except Exception:                 # confirm_message lỗi -> vẫn hỏi, dùng tên tool
                phrase = call.name
            return {"name": call.name, "arguments": args, "phrase": phrase}
        return None

    def _resolve_pending(self, user_text):
        """Xử lý câu trả lời cho hành động đang chờ xác nhận.

        'có' -> chạy hành động; 'không' -> huỷ; không rõ -> trả None (huỷ chờ, để run()
        coi câu này là yêu cầu mới).
        """
        decision = match_confirmation(user_text)
        if decision is None:
            self.pending = None
            return None

        act = self.pending
        self.pending = None
        if decision == "no":
            text = "Được, tôi không làm nữa."
            self._remember(user_text, text)
            return AgentReply(text=text, emotion="neutral")

        # decision == "yes" -> thực thi hành động đã hoãn (bỏ qua LLM cho chắc chắn).
        result = self._run_tool_direct(act["name"], act["arguments"])
        self._remember(user_text, result)
        return AgentReply(text=result, emotion="happy")

    def _run_tool_direct(self, name, arguments):
        """Chạy thẳng một tool theo tên, trả chuỗi kết quả (dùng khi đã được xác nhận)."""
        try:
            output = str(self.registry.run(name, arguments))
            logger.info("🔧 (đã xác nhận) tool %s(%s) → %s", name, arguments, output[:150])
            return output
        except Exception as e:
            logger.error("Tool %s lỗi khi thực thi sau xác nhận: %s", name, e)
            return f"Xin lỗi, tôi gặp lỗi khi thực hiện: {e}"

    # ------------------------- tool ------------------------- #
    def _run_tool(self, call) -> ToolResult:
        try:
            output = self.registry.run(call.name, call.arguments)
            # Log rõ tool nào được gọi + kết quả -> thấy ngay model có gọi tool không,
            # hay chỉ bịa câu trả lời (phân biệt lỗi tool vs lỗi model yếu).
            logger.info("🔧 tool %s(%s) → %s", call.name, call.arguments, str(output)[:150])
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
