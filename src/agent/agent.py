"""
Agent — vòng lặp tool-calling, tách khỏi I/O và khỏi nhà cung cấp LLM.

Bộ nhớ HAI TẦNG (gói `memory/` — xem memory/__init__.py cho bản đồ):
  - NGẮN HẠN (ShortTermMemory): vài lượt hội thoại gần đây trong phiên -> ghép vào prompt.
  - DÀI HẠN (UserProfile, tiêm qua `profile`): sự thật bền vững -> bơm tóm tắt vào prompt.
  - Cầu nối: khi STM đẩy lượt cũ ra, tuỳ chọn "củng cố" — gọi LLM trích sự thật đáng nhớ
    lưu sang tầng dài hạn (bật bằng `auto_extract`, mặc định tắt).
Cảm xúc do LLM quyết: LLM kết thúc câu trả lời bằng thẻ '#emotion: happy|neutral|sad';
Agent tách thẻ, trả AgentReply(text sạch, emotion).

Phụ thuộc tiêm vào (llm, registry) nên test được với LLM giả.
"""

import re
from dataclasses import dataclass

from llm.client import LLMClient, Message, ToolResult
from agent.tools import ToolRegistry
from memory.short_term import ShortTermMemory
from memory.consolidation import parse_extracted_facts, EXTRACT_SYSTEM
from agent.persona import score_user_valence, parse_trait_nudges, PERSONA_TUNE_SYSTEM
from voice.fast_commands import match_confirmation
from utils.logger import get_logger
from memory.timefmt import format_now

logger = get_logger(__name__)

from llm import prompts

# Prompt mặc định (khi KHÔNG dùng router) — nạp base từ llm/prompt_texts.py.
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
                 profile=None, auto_extract: bool = False, consolidate_every: int = 6,
                 extractor=None, persona=None, mood=None,
                 auto_tune: bool = False, persona_tuner=None,
                 skip_respond_for_speakable: bool = False):
        self.llm = llm
        self.registry = registry
        self.system = system
        self.max_iterations = max_iterations
        self.router = router         # tùy chọn: phân loại case -> thu hẹp prompt+tool
        self.profile = profile       # trí nhớ DÀI HẠN: hồ sơ người dùng -> bơm vào prompt
        self.persona = persona       # PersonaState: nhân cách (card) -> bơm vào prompt
        self.mood = mood             # MoodState: tâm trạng phiên -> bơm vào prompt + dẫn avatar
        self.pending = None          # hành động khó hoàn tác đang CHỜ người dùng xác nhận
        # Bỏ lượt LLM soạn lời khi tool đã trả câu hoàn chỉnh (xem _speakable_shortcut).
        self.skip_respond_for_speakable = skip_respond_for_speakable
        # Trí nhớ NGẮN HẠN: vài lượt gần đây (session-only nếu memory_path rỗng).
        self.stm = ShortTermMemory(max_turns=max_history_turns, path=memory_path or None)
        # Củng cố STM -> LTM: gom lượt bị đẩy ra, thỉnh thoảng trích sự thật bền vững.
        self.auto_extract = auto_extract
        self.auto_tune = auto_tune   # Phase 2: LLM nudge núm tính cách khi củng cố (opt-in)
        self.consolidate_every = consolidate_every
        self.extractor = extractor   # callable(transcript)->text; None = dùng self.llm
        self.persona_tuner = persona_tuner  # callable(transcript, traits)->text; None = self.llm
        self._evicted = []           # đệm các lượt bị đẩy khỏi STM, chờ củng cố

    @property
    def history(self):
        """Tương thích ngược: các lượt trong bộ nhớ ngắn hạn (list Message sống)."""
        return self.stm.turns

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

        # Mốc THỜI GIAN: thiếu nó thì model không có gì để so, nên không thể biết một việc
        # đã qua hay sắp tới -> hay nhắc chuyện cũ như sắp diễn ra.
        system = format_now() + "\n\n" + system

        # Bơm tóm tắt hồ sơ người dùng vào đầu system prompt -> trợ lý luôn "biết" người
        # dùng (tên, xưng hô, địa điểm mặc định) mà không tốn lượt hỏi lại.
        if self.profile is not None:
            summary = self.profile.summary(query=user_text)
            if summary:
                system = summary + "\n\n" + system

        # Bơm NHÂN CÁCH + TÂM TRẠNG lên trên cùng -> định hình giọng/thái độ câu trả lời.
        if self.persona is not None:
            preamble = self.persona.render()
            if self.mood is not None:
                preamble += "\nTâm trạng hiện tại của bạn: " + self.mood.label() + "."
            if preamble:
                system = preamble + "\n\n" + system

        messages = list(self.stm.messages()) + [Message(role="user", text=user_text)]

        final_text = ""
        spoke_tool_output = False        # đã cắt lượt soạn lời? (dùng để chấm tâm trạng)
        for iteration in range(self.max_iterations):
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

            # Kết quả tool đã là câu hoàn chỉnh -> đọc thẳng, khỏi tốn 1 lượt LLM soạn lời.
            shortcut = self._speakable_shortcut(iteration, turn.tool_calls, results)
            if shortcut is not None:
                final_text, spoke_tool_output = shortcut, True
                break

            messages.append(Message(role="user", tool_results=results))
        else:
            logger.warning("Agent đạt giới hạn %d vòng công cụ", self.max_iterations)
            final_text = "Xin lỗi, yêu cầu quá phức tạp nên tôi chưa hoàn tất được."

        text, emotion = _split_emotion(final_text)
        text = _clean_text(text)

        # Cập nhật TÂM TRẠNG (tất định) từ cảm xúc user + kết quả việc (thẻ #emotion) +
        # mức thân thiết; rồi để tâm trạng DẪN pose avatar thay cho thẻ tức thời.
        if self.mood is not None:
            # Lối tắt đọc thẳng kết quả tool không có thẻ #emotion -> coi như việc XONG TỐT,
            # để tâm trạng/avatar vẫn phản ứng đúng thay vì trơ ra trung tính.
            outcome = (1.0 if (spoke_tool_output or emotion == "happy")
                       else -1.0 if emotion in ("sad", "cry") else 0.0)
            fam = self.persona.familiarity() if self.persona is not None else 0.3
            self.mood.update(user_valence=score_user_valence(user_text),
                             outcome=outcome, familiarity=fam)
            emotion = self.mood.to_pose()
        if self.persona is not None:
            self.persona.record_interaction()      # thân thiết tăng dần theo tương tác

        self._remember(user_text, text)
        return AgentReply(text=text, emotion=emotion)

    # ------------------------- lối tắt: đọc thẳng kết quả tool ------------------------- #
    def _speakable_shortcut(self, iteration, tool_calls, results):
        """Trả chuỗi để đọc thẳng (bỏ lượt LLM soạn lời), hoặc None nếu KHÔNG được cắt.

        Điều kiện cố ý HẸP. Từng có lối tắt 'terminal' bị gỡ vì nó cắt dựa trên THUỘC TÍNH
        TOOL nên làm rớt các bước sau ('mở A, B, C' chỉ chạy A). Ở đây chỉ cắt khi model
        cho thấy nó chỉ định làm ĐÚNG MỘT việc rồi thôi:
          1. đang ở vòng ĐẦU (chưa có kết quả tool nào trước đó -> không cắt giữa chuỗi);
          2. lượt này gọi ĐÚNG 1 tool (>=2 tool = đang làm nhiều bước);
          3. tool được đánh dấu `speakable` (output đã là câu hoàn chỉnh);
          4. tool chạy KHÔNG lỗi (lỗi thì để LLM diễn đạt lại cho dễ nghe);
          5. tool KHÔNG destructive (đường destructive đã rẽ nhánh xác nhận từ trước).
        Thiếu bất kỳ điều nào -> None -> chạy y như cũ (mặc định an toàn).
        """
        if not self.skip_respond_for_speakable or iteration != 0:
            return None
        if len(tool_calls) != 1 or len(results) != 1:
            return None
        result = results[0]
        if getattr(result, "is_error", False):
            return None
        name = tool_calls[0].name
        if not self.registry.has(name):
            return None
        tool = self.registry.get(name)
        if not getattr(tool, "speakable", False) or getattr(tool, "destructive", False):
            return None
        text = (result.content or "").strip()
        if not text:
            return None
        logger.info("⚡ đọc thẳng kết quả %s (bỏ lượt soạn lời)", name)
        return text

    # ------------------------- bộ nhớ hai tầng ------------------------- #
    def _remember(self, user_text, assistant_text):
        """Ghi lượt vào STM; các lượt bị đẩy ra được gom lại để (tuỳ chọn) củng cố vào LTM
        (trích sự thật) và/hoặc tinh chỉnh nhân cách (nudge núm)."""
        evicted = self.stm.add(user_text, assistant_text)
        wants = ((self.auto_extract and self.profile is not None)
                 or (self.auto_tune and self.persona is not None))
        if wants and evicted:
            self._evicted.extend(evicted)
            if len(self._evicted) >= self.consolidate_every * 2:
                self._consolidate()

    def clear_memory(self):
        self.stm.clear()
        self._evicted = []

    def _consolidate(self):
        """Từ các lượt sắp quên: trích sự thật (LTM) và/hoặc tinh chỉnh nhân cách (nudge núm)."""
        turns, self._evicted = self._evicted, []
        transcript = "\n".join(
            f"{'Người dùng' if m.role == 'user' else 'Trợ lý'}: {m.text}"
            for m in turns if m.text)
        if not transcript.strip():
            return
        if self.auto_extract and self.profile is not None:
            self._extract_facts(transcript)
        if self.auto_tune and self.persona is not None:
            self._tune_persona(transcript)

    def _extract_facts(self, transcript):
        try:
            raw = self._extract(transcript)
        except Exception as e:                 # trích xuất lỗi KHÔNG được làm vỡ luồng chính
            logger.warning("Củng cố trí nhớ dài hạn lỗi: %s", e)
            return
        facts = parse_extracted_facts(raw)
        for fact in facts:
            # Sự kiện có thời điểm đi vào kho SỰ KIỆN (tự hết hạn) thay vì kho sự thật bền
            # vững — nếu không, "có phỏng vấn lúc 2h" sẽ được nhắc mãi như sắp diễn ra.
            if fact.get("kind") == "event":
                self.profile.add_event(fact["text"], when=fact.get("when"))
            else:
                self.profile.add_auto_fact(fact["text"])
        if facts:
            logger.info("🧠 củng cố %d điều vào trí nhớ dài hạn", len(facts))

    def _tune_persona(self, transcript):
        """Phase 2: LLM gợi ý nudge núm tính cách (có biên) từ hội thoại. Lỗi -> bỏ qua."""
        traits = self.persona.data.get("traits", {})
        try:
            raw = self._suggest_nudges(transcript, traits)
        except Exception as e:
            logger.warning("Tinh chỉnh nhân cách lỗi: %s", e)
            return
        nudges = parse_trait_nudges(raw)
        for trait, delta in nudges.items():
            self.persona.adjust(trait, delta)          # adjust đã kẹp [0,1] + log + lưu
        if nudges and self.mood is not None:           # warmth/energy đổi -> cập nhật baseline
            self.mood.set_baseline(self.persona.baseline_valence(),
                                   self.persona.baseline_arousal())
        if nudges:
            logger.info("🎭 tinh chỉnh %d núm tính cách", len(nudges))

    def _suggest_nudges(self, transcript, traits):
        """Bộ gợi ý nudge (tiêm vào để test) hoặc LLM."""
        if self.persona_tuner is not None:
            return self.persona_tuner(transcript, traits)
        tstr = ", ".join(f"{k}={v:.2f}" for k, v in traits.items())
        turn = self.llm.generate(
            system=PERSONA_TUNE_SYSTEM,
            messages=[Message(role="user", text=f"Núm hiện tại: {tstr}\n\nHội thoại:\n{transcript}")],
            tools=[])
        return turn.text

    def _extract(self, transcript):
        """Gọi bộ trích (tiêm vào để test) hoặc LLM để rút sự thật từ đoạn hội thoại."""
        if self.extractor is not None:
            return self.extractor(transcript)
        turn = self.llm.generate(system=EXTRACT_SYSTEM,
                                 messages=[Message(role="user", text=transcript)], tools=[])
        return turn.text

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
