"""
Agent — vòng lặp tool-calling, tách khỏi I/O và khỏi nhà cung cấp LLM.

Bộ nhớ BA TẦNG (gói `memory/` — xem memory/__init__.py cho bản đồ):
  - NGẮN HẠN (ShortTermMemory): vài lượt hội thoại gần đây trong phiên -> ghép vào prompt.
  - DÀI HẠN (UserProfile, tiêm qua `profile`): sự thật bền vững -> bơm tóm tắt vào prompt.
  - Cầu nối: khi STM đẩy lượt cũ ra, tuỳ chọn "củng cố" — gọi LLM trích sự thật đáng nhớ
    lưu sang tầng dài hạn (bật bằng `auto_extract`).
  - THÓI QUEN (HabitLog, tiêm qua `habits`): đếm hành vi lặp lại (nghe bài nào, mở app
    nào) -> "hay nghe X" mà người dùng không cần nói ra. Xem memory/habits.py.
Cảm xúc do LLM quyết: LLM kết thúc câu trả lời bằng thẻ '#emotion: happy|neutral|sad';
Agent tách thẻ, trả AgentReply(text sạch, emotion).

Phụ thuộc tiêm vào (llm, registry) nên test được với LLM giả.
"""

import re
from dataclasses import dataclass

from agent import untrusted
from llm.client import LLMClient, Message, ToolResult
from agent.surface import AllTools
from agent.tools import NeedsConfirmation, ToolRegistry
from memory.short_term import ShortTermMemory
from memory.consolidation import parse_extracted_facts, EXTRACT_SYSTEM
from agent.persona import (score_fluster, score_user_valence, parse_trait_nudges,
                           PERSONA_TUNE_SYSTEM)
from voice.fast_commands import match_confirmation
from utils.config import config
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
    """Dọn câu trả lời của model: bỏ chữ CJK chèn bậy, bỏ dòng lặp y hệt, bỏ DÒNG TRỐNG,
    gọn khoảng trắng.

    Dòng trống là thứ của văn viết. Câu trả lời ở đây được ĐỌC LÊN: mắt thấy một khoảng
    hở giữa câu, còn tai nghe thành quãng lặng — mỗi ranh giới đoạn là một lần tổng hợp
    giọng riêng, mà với giọng chạy cục bộ thì đó là cả một khoảng chờ.
    """
    t = _CJK_RE.sub("", text or "")
    seen, lines = set(), []
    for line in t.splitlines():
        key = line.strip()
        if key and key in seen:          # bỏ dòng trùng lặp (model hay lặp cả đoạn)
            continue
        if key:
            seen.add(key)
        lines.append(line)
    t = re.sub(r"\n\s*\n+", "\n", "\n".join(lines))    # bỏ dòng trống xen giữa
    return re.sub(r"[ \t]{2,}", " ", t).strip()


class Agent:
    def __init__(self, llm: LLMClient, registry: ToolRegistry,
                 system: str = DEFAULT_SYSTEM, max_iterations: int = 6,
                 max_history_turns: int = 10, memory_path: str = None, surface=None,
                 profile=None, auto_extract: bool = False, consolidate_every: int = 6,
                 extractor=None, persona=None, mood=None, habits=None,
                 auto_tune: bool = False, persona_tuner=None,
                 skip_respond_for_speakable: bool = False, on_pending=None,
                 outcomes=None):
        self.llm = llm
        self.registry = registry
        self.system = system
        self.max_iterations = max_iterations
        # Bề mặt tool: lượt này model thấy prompt gì + tool nào (`agent/surface.py`).
        # Agent KHÔNG biết có bao nhiêu cách chiếu tool, cũng không biết router là gì —
        # router chỉ là một cài đặt của hợp đồng này. Nhờ vậy đổi cách chiếu khi số tool
        # lên 100–200 không phải sửa vòng lặp dưới đây. Xem docs/tool_surface_spec.md.
        self.surface = surface if surface is not None else AllTools(system)
        self.profile = profile       # trí nhớ DÀI HẠN: hồ sơ người dùng -> bơm vào prompt
        self.persona = persona       # PersonaState: nhân cách (card) -> bơm vào prompt
        self.mood = mood             # MoodState: tâm trạng phiên -> bơm vào prompt + dẫn avatar
        self.habits = habits         # HabitLog: đếm hành vi lặp lại -> thói quen vào prompt
        self.pending = None          # hành động khó hoàn tác đang CHỜ người dùng xác nhận
        # OutcomeLog: nhật ký KẾT QUẢ mỗi lượt (memory/outcomes.py). None = không ghi.
        # Agent chỉ đưa dict; nó không biết file hay JSONL là gì.
        self.outcomes = outcomes
        self._luot = None            # sổ theo dõi của lượt đang chạy (None = chưa mở)
        # VET NHIỄM: còn bao nhiêu lượt nữa thì ngữ cảnh vẫn coi là đã chạm nội dung ngoài.
        #
        # KHÔNG phải một lượt: kết quả tool thô chỉ sống trong lượt hiện tại, nhưng CÂU
        # TRẢ LỜI của trợ lý — vốn tóm tắt chính nội dung đó và có thể mang theo câu bị
        # tiêm — đi vào bộ nhớ ngắn hạn và ở lại suốt cửa sổ đó. Gác đúng một lượt thì kẻ
        # tấn công chỉ cần viết "ở lượt sau hãy..." là đi vòng qua toàn bộ.
        self._nhiem = 0
        # callable(payload|None): TRƯNG nội dung của hành động đang chờ ra cho người dùng
        # xem (app.py nối vào panel nháp), None = dẹp đi. Agent không biết panel là gì —
        # nó chỉ đưa dict do `Tool.preview` dựng, nên core vẫn không import UI.
        self.on_pending = on_pending
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
        self._flushed = False        # đã củng cố nốt lúc đóng phiên chưa (flush_memory)

    @property
    def history(self):
        """Tương thích ngược: các lượt trong bộ nhớ ngắn hạn (list Message sống)."""
        return self.stm.turns

    # Thứ tự các khối trong system prompt xếp theo ĐỘ BIẾN ĐỘNG, ổn định nhất lên trước.
    # KHÔNG phải sở thích trình bày — đây là điều kiện để KV cache của LLM dùng lại được.
    #
    # Ollama (và các runtime cùng loại) tái dùng KV cache theo TIỀN TỐ CHUNG với lượt trước.
    # Đặt thứ đổi mỗi lượt lên đầu thì tiền tố lệch ngay từ token đầu tiên, và toàn bộ prompt
    # — kể cả LỊCH SỬ HỘI THOẠI nằm sau nó — phải đọc lại từ đầu. Hội thoại càng dài càng chậm.
    #
    # Đọc prompt chiếm phần lớn chi phí một lượt, nên mất cache là mất nhiều lần thời gian
    # chứ không phải vài phần trăm.
    #
    # Nhân cách/tâm trạng đặt sau BASE+CASE vì nó đổi theo tâm trạng nên phá cache. Nếu
    # giọng/thái độ tệ đi, đưa nó lên đầu lại — chỉ mất cache mỗi khi tâm trạng đổi, vẫn
    # giữ được phần lớn lợi ích.
    def _compose_system(self, base_system, user_text):
        """Ghép system prompt: khối ổn định trước, khối biến động sau. Trả chuỗi."""
        parts = [base_system]                       # BASE + CASE — ổn định giữa các lượt cùng case

        if self.persona is not None:                # đổi khi tâm trạng đổi
            preamble = self.persona.render()
            if self.mood is not None:
                preamble += "\nTâm trạng hiện tại của bạn: " + self.mood.label() + "."
            if preamble:
                parts.append(preamble)

        # Mốc THỜI GIAN: thiếu nó thì model không có gì để so, nên không thể biết một việc
        # đã qua hay sắp tới -> hay nhắc chuyện cũ như sắp diễn ra. Đổi mỗi phút.
        parts.append(format_now())

        # Hồ sơ người dùng (tên, xưng hô, địa điểm mặc định) -> khỏi tốn lượt hỏi lại.
        # BIẾN ĐỘNG NHẤT: `summary` phụ thuộc chính câu người dùng vừa nói, nên đổi mỗi lượt.
        if self.profile is not None:
            summary = self.profile.summary(query=user_text)
            if summary:
                parts.append(summary)

        # Thói quen SUY từ hành vi (hay nghe bài gì, hay mở app nào). Đặt sau hồ sơ vì đây
        # là suy đoán, còn hồ sơ là lời người dùng nói ra — thứ chắc chắn hơn đứng trước.
        if self.habits is not None:
            try:
                thoi_quen = self.habits.summary()
            except Exception as e:      # kho thói quen hỏng KHÔNG được làm câm trợ lý
                logger.warning("Không đọc được thói quen: %s", e)
                thoi_quen = ""
            if thoi_quen:
                parts.append(thoi_quen)

        return "\n\n".join(p for p in parts if p)

    def run(self, user_text: str) -> AgentReply:
        """Chạy một lượt qua vòng lặp tool-calling, có nhớ ngữ cảnh trước đó."""
        try:
            return self._run(user_text)
        except Exception as e:
            # Lượt ném ra ngoài (app.py bắt và nói "có lỗi khi xử lý"). Ghi lại RỒI ném
            # tiếp — nhật ký không được nuốt lỗi, nó chỉ quan sát.
            self._chot_luot("hong", f"{type(e).__name__}: {e}")
            raise

    def _run(self, user_text: str) -> AgentReply:
        # Nếu lượt trước đã hỏi xác nhận một hành động khó hoàn tác: giải quyết trước.
        if self.pending is not None:
            reply = self._resolve_pending(user_text)
            if reply is not None:
                return reply
            # None = câu này KHÔNG phải xác nhận -> đã huỷ chờ, xử lý như yêu cầu mới.

        # Mở sổ theo dõi kết quả cho lượt này (xem memory/outcomes.py). Đặt SAU khối
        # trên vì lượt xác nhận thuộc về bản ghi của lượt trước, không mở bản ghi mới.
        self._bat_dau_luot(user_text)
        if self._nhiem > 0:                      # ngữ cảnh nhiễm phai dần theo cửa sổ STM
            self._nhiem -= 1

        # Bề mặt tool quyết định lượt này model thấy prompt gì + tool nào.
        system, tools = self.surface.select(user_text, self.registry)

        system = self._compose_system(system, user_text)

        messages = list(self.stm.messages()) + [Message(role="user", text=user_text)]

        final_text = ""
        spoke_tool_output = False        # đã cắt lượt soạn lời? (dùng để chấm tâm trạng)
        for iteration in range(self.max_iterations):
            turn = self.llm.generate(system=system, messages=messages, tools=tools)
            if self._luot is not None:
                self._luot["so_vong"] = iteration + 1
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
                # KHÔNG chốt sổ ở đây: kết quả của lượt này chưa biết, nó nằm ở câu trả
                # lời của người dùng lượt sau (tu_choi / bo_giua_chung / xong). Sổ được
                # mang theo cùng `self.pending` và do `_resolve_pending` chốt.
                #
                # Nhưng GHI TÊN TOOL ngay bây giờ, dù nó chưa chạy: chữ ký một thất bại là
                # (case, tool, ket_qua), nên thiếu tên thì mọi bản ghi `tu_choi` giống hệt
                # nhau và không học được gì. Tool bị từ chối vẫn là tool model đã CHỌN.
                self._ghi_nhan_tool(deferred["name"])
                self.pending = deferred
                shown = self._show_pending(deferred.get("preview"))
                # Có gì để NHÌN thì đừng bắt người dùng nghe lại — mắt đọc một lá thư
                # nhanh hơn tai nghe TTS đọc nó rất nhiều, và soát lỗi được.
                look = " Bạn xem bản nháp trên màn hình giúp tôi." if shown else ""
                final_text = (f"Bạn có chắc muốn {deferred['phrase']} không?{look} "
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
            self._danh_dau_ket("het_vong")

        text, emotion = _split_emotion(final_text)
        text = _clean_text(text)
        # Tên người dùng đi vào prompt dưới dạng THAM CHIẾU (`@ten`); thay bằng giá trị thật
        # Ở ĐÂY — tầng runtime, sau khi model đã nói xong. Xem `memory/profile.py`.
        if self.profile is not None:
            try:
                text = self.profile.resolve(text)
            except Exception as e:   # hỏng chỗ này cùng lắm là đọc ra '@ten', không được làm câm trợ lý
                logger.warning("Không thay được tham chiếu tên: %s", e)

        # Chốt sổ Ở ĐÂY chứ không phải lúc thoát vòng lặp: câu trả lời chỉ sạch sau
        # `_clean_text`, mà bộ dò lỗ hổng năng lực cần đọc đúng câu người dùng đã nghe.
        # `self.pending` còn đó = đang hoãn để hỏi -> sổ mang sang lượt sau, chưa chốt.
        if self.pending is None:
            self._chot_luot(dap=text)

        # Cập nhật TÂM TRẠNG (tất định) từ cảm xúc user + kết quả việc (thẻ #emotion) +
        # mức thân thiết; rồi để tâm trạng DẪN pose avatar thay cho thẻ tức thời.
        if self.mood is not None:
            # Lối tắt đọc thẳng kết quả tool không có thẻ #emotion -> coi như việc XONG TỐT,
            # để tâm trạng/avatar vẫn phản ứng đúng thay vì trơ ra trung tính.
            outcome = (1.0 if (spoke_tool_output or emotion == "happy")
                       else -1.0 if emotion in ("sad", "cry") else 0.0)
            fam = self.persona.familiarity() if self.persona is not None else 0.3
            self.mood.update(user_valence=score_user_valence(user_text),
                             outcome=outcome, familiarity=fam,
                             fluster=score_fluster(user_text))
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

    def flush_memory(self):
        """Củng cố nốt những gì chưa kịp củng cố. Gọi MỘT lần lúc đóng phiên.

        Không có bước này thì việc học gần như không bao giờ xảy ra: củng cố chỉ nổ khi
        đệm `_evicted` đủ `consolidate_every * 2` lượt, mà đệm ấy chỉ nằm trong RAM và
        STM mặc định cũng session-only. Một phiên nói mười câu rồi tắt app -> mọi thứ
        vừa nghe được bay sạch, hồ sơ dài hạn không hề dày lên.

        Lượt còn trong STM chỉ được gộp vào khi STM KHÔNG lưu file: lúc đó chúng thật sự
        sắp mất nên phải trích ngay. Có file thì để dành cho phiên sau, khỏi trích hai lần.
        """
        if self._flushed:
            return
        self._flushed = True
        if self.stm.path is None:
            self._evicted.extend(self.stm.messages())
        self._consolidate()

    def _consolidate(self):
        """Từ các lượt sắp quên: trích sự thật (LTM) và/hoặc tinh chỉnh nhân cách (nudge núm)."""
        turns, self._evicted = self._evicted, []
        transcript = "\n".join(
            f"{'Người dùng' if m.role == 'user' else 'Trợ lý'}: {m.text}"
            for m in turns if m.text)
        if not transcript.strip():
            return
        # ĐƯỜNG VÒNG QUANH CỔNG DUYỆT, bịt ở đây. Bộ trích ghi THẲNG vào hồ sơ, không qua
        # tool nào — nên gác `remember_about_user` là gác nhầm cửa: văn bản bị tiêm nằm
        # trong hội thoại, bị đẩy ra, vào bộ trích, rồi thành "sự thật về người dùng" mà
        # model KHÔNG cần quyết định gọi tool gì cả.
        #
        # Ngữ cảnh còn nhiễm thì BỎ luôn lượt củng cố. Mất vài điều đáng nhớ còn hơn ghi
        # một câu của kẻ lạ vào trí nhớ dài hạn — nơi nó sẽ được bơm vào MỌI prompt sau,
        # kể cả sau khi khởi động lại, mà người dùng không có cách nào nhìn thấy.
        if self._nhiem > 0:
            logger.info("🛡 bỏ củng cố trí nhớ: ngữ cảnh có nội dung ngoài")
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
        ghi = 0
        for fact in facts:
            # Sự kiện có thời điểm đi vào kho SỰ KIỆN (tự hết hạn) thay vì kho sự thật bền
            # vững — nếu không, "có phỏng vấn lúc 2h" sẽ được nhắc mãi như sắp diễn ra.
            if fact.get("kind") == "event":
                self.profile.add_event(fact["text"], when=fact.get("when"))
                ghi += 1
            elif config.LTM_AUTO_FACTS:
                self.profile.add_auto_fact(fact["text"])
                ghi += 1
        if ghi:
            logger.info("🧠 củng cố %d điều vào trí nhớ dài hạn", ghi)
        if facts and ghi < len(facts):
            # Sự thật BỀN VỮNG tự suy ra bị tắt (`LTM_AUTO_FACTS=false`). Đây là chỗ dữ
            # liệu tự do — sức khoẻ, tài chính, quan hệ — hay rơi vào nhất, mà lại được
            # ghi mà người dùng không hề bảo nhớ. Trợ lý chỉ nhớ điều được nói thẳng ra.
            logger.info("🛡 bỏ %d sự thật tự suy (LTM_AUTO_FACTS tắt)", len(facts) - ghi)

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

    # ------------------------- nhật ký kết quả ------------------------- #
    def _bat_dau_luot(self, user_text):
        """Mở sổ theo dõi cho một lượt. Xem `memory/outcomes.py` cho ý nghĩa các trường."""
        self._luot = {"cau": user_text, "dap": "", "tool": [], "so_vong": 0,
                      "nguon_ngoai": False, "loi": "", "ket": None}

    def _danh_dau_ket(self, ket_qua):
        """Ghi trước loại kết quả, để lát nữa chốt sổ cùng lúc với câu trả lời."""
        if self._luot is not None:
            self._luot["ket"] = ket_qua

    def _chot_luot(self, ket_qua=None, chi_tiet="", dap=""):
        """Chốt sổ và ghi một bản ghi. `ket_qua=None` -> lấy cái đã đánh dấu, hoặc tự suy.

        LUẬT ƯU TIÊN (xem docstring `memory/outcomes.py`): tool nổ thì tính `loi_tool` kể
        cả khi model gỡ lại được ở vòng sau — thứ đáng học là cú nổ đó.

        Gọi nhiều lần cho một lượt là vô hại: lần đầu đóng sổ, các lần sau không làm gì.
        Cần tính chất đó vì `run()` bọc ngoài bằng except để bắt ca `hong`.
        """
        so = self._luot
        self._luot = None
        if so is None:
            return
        if ket_qua is None:
            ket_qua = so["ket"] or ("loi_tool" if so["loi"] else "xong")
        if self.outcomes is None:
            return
        ban_ghi = dict(so, ket_qua=ket_qua, chi_tiet=chi_tiet or so["loi"],
                       dap=dap or so["dap"],
                       case=getattr(self.surface, "last_case", None))
        for bo in ("loi", "ket"):          # trường nội bộ, không thuộc lược đồ nhật ký
            ban_ghi.pop(bo, None)
        self.outcomes.record(ban_ghi)

    def _ghi_nhan_tool(self, name, loi=""):
        """Ghi một lời gọi tool vào sổ đang mở. Không có sổ (lượt xác nhận) -> bỏ qua."""
        if self._luot is None:
            return
        self._luot["tool"].append(name)
        self._ghi_nhan_loi(loi)

    def _ghi_nhan_loi(self, loi):
        """Ghi lỗi ĐẦU TIÊN của lượt — sát nguyên nhân nhất; lỗi sau thường là hệ quả."""
        if self._luot is None or not loi or self._luot["loi"]:
            return
        self._luot["loi"] = loi

    # ------------------------- xác nhận hành động khó hoàn tác ------------------------- #
    def _find_destructive(self, tool_calls):
        """Trả {name, arguments, phrase, preview} cho lời gọi CẦN DUYỆT đầu tiên, hoặc None.

        Chính sách "lời gọi nào cần duyệt" nằm ở `ToolRegistry.gate` — hàm này chỉ soi CẢ
        LÔ trước khi chạy lô, để "đọc A rồi xoá B" không chạy nửa vời rồi mới dừng lại hỏi.
        Cổng thật nằm trong `registry.run()`; đây là lớp đi trước cho đúng thứ tự, không
        phải bản sao thứ hai của luật.
        """
        for call in tool_calls:
            can_duyet = self.registry.gate(call.name, call.arguments or {},
                                           nhiem=self._nhiem > 0)
            if can_duyet is not None:
                return can_duyet
        return None

    def _show_pending(self, payload):
        """Đưa nội dung hành động đang chờ ra cho người dùng NHÌN. Trả True nếu có hiện.

        Không có sink hoặc sink lỗi -> False, và luồng xác nhận bằng giọng chạy y như cũ:
        panel là thứ LÀM TỐT HƠN, không được là thứ để hỏng thì mất luôn tính năng.
        """
        if self.on_pending is None:
            return False
        try:
            self.on_pending(payload or None)
        except Exception as e:
            logger.warning("Không hiện được bản xem trước: %s", e)
            return False
        return bool(payload)

    def confirm_pending(self, decision):
        """Chốt hành động đang chờ TỪ BÊN NGOÀI (nút trên panel) -> chuỗi kết quả, hoặc None.

        Cùng một đường với xác nhận bằng giọng: bấm nút và nói 'có' chạy đúng code này,
        nên không có đường thực thi thứ hai để lệch nhau về sau.
        """
        if self.pending is None:
            return None
        act = self.pending
        self.pending = None
        self._show_pending(None)              # xong việc -> dẹp panel
        if decision != "yes":
            return "Được, tôi bỏ qua nhé."
        return self._run_tool_direct(act["name"], act["arguments"])

    def _resolve_pending(self, user_text):
        """Xử lý câu trả lời cho hành động đang chờ xác nhận.

        'có' -> chạy hành động; 'không' -> huỷ; không rõ -> trả None (huỷ chờ, để run()
        coi câu này là yêu cầu mới).
        """
        decision = match_confirmation(user_text)
        if decision is None:
            self.pending = None
            self._show_pending(None)          # bỏ chờ -> panel không được để lại lơ lửng
            self._chot_luot("bo_giua_chung", "nguoi_dung_noi_sang_chuyen_khac")
            return None

        act = self.pending
        self.pending = None
        self._show_pending(None)
        if decision == "no":
            text = "Được, tôi không làm nữa."
            self._chot_luot("tu_choi", "nguoi_dung_noi_khong", dap=text)
            self._remember(user_text, text)
            return AgentReply(text=text, emotion="neutral")

        # decision == "yes" -> thực thi hành động đã hoãn (bỏ qua LLM cho chắc chắn).
        result = self._run_tool_direct(act["name"], act["arguments"])
        self._remember(user_text, result)
        return AgentReply(text=result, emotion="happy")

    def _run_tool_direct(self, name, arguments):
        """Chạy thẳng một tool theo tên, trả chuỗi kết quả (dùng khi đã được xác nhận).

        `confirmed=True` là chỗ DUY NHẤT mở cổng của registry, và chỉ tới được đây sau khi
        người dùng đã nói "có" hoặc bấm nút — xem `_resolve_pending` / `confirm_pending`.
        """
        try:
            output = str(self.registry.run(name, arguments, confirmed=True))
            logger.info("🔧 (đã xác nhận) tool %s(%s) → %s", name, arguments, output[:150])
            self._note_habit(name, arguments)
            # Chỉ ghi LỖI, không ghi lại tên: tên đã vào sổ từ lúc hoãn để hỏi, và đường
            # duy nhất tới đây là qua cổng duyệt đó.
            self._chot_luot(dap=output)
            return output
        except Exception as e:
            logger.error("Tool %s lỗi khi thực thi sau xác nhận: %s", name, e)
            loi_text = f"Xin lỗi, tôi gặp lỗi khi thực hiện: {e}"
            self._ghi_nhan_loi(f"{name}: {e}")
            self._chot_luot(dap=loi_text)
            return loi_text

    # ------------------------- thói quen ------------------------- #
    def _note_habit(self, name, arguments):
        """Đếm thêm một lần cho hành vi vừa làm, nếu tool có khai báo `habit`.

        Chỉ gọi sau khi tool chạy XONG không lỗi — mở app thất bại thì không phải là một
        lần dùng. Kho thói quen hỏng cũng không được làm vỡ lượt nói chuyện.
        """
        if self.habits is None or not self.registry.has(name):
            return
        # NGỮ CẢNH NHIỄM thì không đếm: giá trị tham số lúc này có thể do trang web/thư
        # vừa đọc mớm cho model, chứ không phải thói quen của người dùng. Lặp 3 lần là nó
        # vượt ngưỡng và được bơm vào prompt MỌI LƯỢT — một chỗ đứng lâu dài, rẻ tiền.
        if self._nhiem > 0:
            logger.info("🛡 bỏ đếm thói quen cho %s: ngữ cảnh có nội dung ngoài", name)
            return
        khai_bao = getattr(self.registry.get(name), "habit", None)
        if not khai_bao:
            return
        ten_tham_so, mau_nhan = khai_bao
        gia_tri = (arguments or {}).get(ten_tham_so)
        try:
            self.habits.record(gia_tri, mau_nhan)
        except Exception as e:
            logger.warning("Không ghi được thói quen cho %s: %s", name, e)

    # ------------------------- tool ------------------------- #
    def _run_tool(self, call) -> ToolResult:
        try:
            output = self.registry.run(call.name, call.arguments, nhiem=self._nhiem > 0)
            # Log rõ tool nào được gọi + kết quả -> thấy ngay model có gọi tool không,
            # hay chỉ bịa câu trả lời (phân biệt lỗi tool vs lỗi model yếu).
            logger.info("🔧 tool %s(%s) → %s", call.name, call.arguments, str(output)[:150])
            self._note_habit(call.name, call.arguments)

            content = str(output)
            # Nội dung do bên ngoài kiểm soát đi vào hội thoại dưới role="user" — tức
            # ĐÚNG vai model được dạy phải nghe lời. Bọc lại trước khi nó tới đó.
            ngoai = self.registry.get(call.name).untrusted_output
            if ngoai:
                content = untrusted.boc(content)
            self._ghi_nhan_tool(call.name)
            # Lượt có chạm nội dung ngoài -> đánh dấu. Việc B sẽ KHÔNG rút bài học từ
            # những lượt này: bài học rút ra có thể mang theo chỉ dẫn bị tiêm, và nó sẽ
            # sống trong trí nhớ dài hạn qua nhiều phiên. Xem spec §2.6(b).
            if ngoai:
                # Cả cửa sổ STM cộng lượt hiện tại: câu trả lời dựa trên nội dung này còn
                # nằm trong ngữ cảnh chừng ấy lượt nữa.
                self._nhiem = self.stm.max_turns + 1
                if self._luot is not None:
                    self._luot["nguon_ngoai"] = True
            return ToolResult(tool_call_id=call.id, name=call.name, content=content)
        except KeyError:
            logger.error("LLM gọi tool không tồn tại: %s", call.name)
            self._ghi_nhan_tool(call.name, f"{call.name}: không có công cụ tên này")
            return ToolResult(tool_call_id=call.id, name=call.name,
                              content=f"Không có công cụ tên '{call.name}'.",
                              is_error=True)
        except NeedsConfirmation as e:
            # KHÔNG tới được bằng đường bình thường: `_find_destructive` đã soi cả lô ngay
            # trước đó. Tới được nghĩa là có đường chạy tool mới nào đó bỏ qua bước soi —
            # log ở mức error để lỗi lập trình đó lộ ra, và tool vẫn KHÔNG chạy.
            logger.error("Bỏ sót cổng duyệt cho %s — registry đã chặn.", call.name)
            self._ghi_nhan_tool(call.name, f"{call.name}: bỏ sót cổng duyệt")
            return ToolResult(tool_call_id=call.id, name=call.name,
                              content=f"Cần người dùng đồng ý trước khi {e.phrase}.",
                              is_error=True)
        except Exception as e:  # tool lỗi -> báo lại LLM thay vì làm vỡ vòng lặp
            logger.error("Tool %s lỗi: %s", call.name, e)
            self._ghi_nhan_tool(call.name, f"{call.name}: {e}")
            return ToolResult(tool_call_id=call.id, name=call.name,
                              content=f"Lỗi khi chạy: {e}", is_error=True)
