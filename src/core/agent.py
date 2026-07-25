"""
Agent — vòng lặp tool-calling, tách hoàn toàn khỏi I/O và khỏi nhà cung cấp LLM.

Nhận một câu (text) → hỏi LLM → nếu LLM muốn gọi tool thì chạy tool, đưa kết quả
lại cho LLM → lặp đến khi LLM trả lời cuối. Trả về chuỗi phản hồi.

Phụ thuộc được tiêm vào (dependency injection) nên test được với LLM giả:
  - llm:      LLMClient (Claude thật, hoặc fake trong test)
  - registry: ToolRegistry (dựng từ actions thật, hoặc mock)
"""

from typing import List

from core.llm_client import LLMClient, Message, ToolResult
from core.tools import ToolRegistry
from utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_SYSTEM = (
    "Bạn là trợ lý điều khiển máy tính bằng tiếng Việt.\n"
    "Với MỌI yêu cầu hành động (mở/đóng app, chỉnh âm lượng/độ sáng, xem thông tin "
    "máy, tìm kiếm web, phát nhạc, tắt/khởi động lại máy...), BẮT BUỘC gọi ngay công "
    "cụ phù hợp với đúng tham số. KHÔNG hỏi lại nếu lệnh đã đủ rõ — chỉ hỏi khi thật "
    "sự thiếu thông tin bắt buộc.\n"
    "Sau khi công cụ chạy xong, trả lời ngắn gọn, thân thiện bằng tiếng Việt."
)


class Agent:
    def __init__(self, llm: LLMClient, registry: ToolRegistry,
                 system: str = DEFAULT_SYSTEM, max_iterations: int = 6):
        self.llm = llm
        self.registry = registry
        self.system = system
        self.max_iterations = max_iterations

    def run(self, user_text: str) -> str:
        """Chạy một yêu cầu qua vòng lặp tool-calling, trả về phản hồi cuối."""
        messages: List[Message] = [Message(role="user", text=user_text)]
        tools = self.registry.specs()

        for _ in range(self.max_iterations):
            turn = self.llm.generate(system=self.system, messages=messages, tools=tools)

            # Ghi lại lượt assistant (kèm các tool_call để LLM thấy lịch sử nhất quán)
            messages.append(Message(role="assistant", text=turn.text,
                                    tool_calls=turn.tool_calls))

            # Không gọi tool nữa -> đây là câu trả lời cuối
            if not turn.wants_tools:
                return turn.text

            # Thực thi từng tool, gom kết quả gửi lại LLM
            results = []
            for call in turn.tool_calls:
                results.append(self._run_tool(call))
            messages.append(Message(role="user", tool_results=results))

        logger.warning("Agent đạt giới hạn %d vòng công cụ", self.max_iterations)
        return "Xin lỗi, yêu cầu quá phức tạp nên tôi chưa hoàn tất được."

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
