"""
Interface LLM trung lập (provider-agnostic) + hiện thực cho Claude.

Agent chỉ phụ thuộc vào `LLMClient` với các kiểu dữ liệu trung lập bên dưới,
KHÔNG phụ thuộc trực tiếp vào SDK của một nhà cung cấp. Nhờ vậy:
  - Test tiêm một client giả (FakeLLMClient) — không cần mạng hay API key.
  - Có thể thêm Ollama/nhà cung cấp khác bằng một lớp dịch tương tự ClaudeClient.

Kiểu trung lập:
  ToolCall      : một lời gọi tool do LLM sinh ra (id, tên, tham số)
  ToolResult    : kết quả thực thi tool, gửi ngược lại LLM
  Message        : một lượt hội thoại (user/assistant) ở dạng trung lập
  AssistantTurn : phản hồi của LLM cho một lượt (text + các tool cần gọi)
"""

from dataclasses import dataclass, field
from typing import List, Protocol, runtime_checkable

from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    role: str                                    # "user" | "assistant"
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)     # assistant
    tool_results: List[ToolResult] = field(default_factory=list)  # user (kết quả tool)


@dataclass
class AssistantTurn:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@runtime_checkable
class LLMClient(Protocol):
    """Hợp đồng mà Agent dựa vào. Mọi nhà cung cấp phải hiện thực generate()."""

    def generate(self, *, system: str, messages: List[Message],
                 tools: List[dict]) -> AssistantTurn:
        ...


class ClaudeClient:
    """Hiện thực LLMClient bằng Anthropic Python SDK (Claude tool-calling)."""

    def __init__(self, model: str = "claude-opus-4-8", max_tokens: int = 1024,
                 api_key: str = None):
        # Import trong hàm để môi trường không cài 'anthropic' vẫn nạp được module.
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    # --- dịch Message trung lập -> định dạng Anthropic ---
    @staticmethod
    def _to_anthropic_messages(messages: List[Message]) -> List[dict]:
        out = []
        for m in messages:
            if m.role == "assistant":
                content = []
                if m.text:
                    content.append({"type": "text", "text": m.text})
                for tc in m.tool_calls:
                    content.append({
                        "type": "tool_use", "id": tc.id,
                        "name": tc.name, "input": tc.arguments,
                    })
                out.append({"role": "assistant", "content": content})
            else:  # user
                if m.tool_results:
                    content = [{
                        "type": "tool_result",
                        "tool_use_id": r.tool_call_id,
                        "content": r.content,
                        "is_error": r.is_error,
                    } for r in m.tool_results]
                    out.append({"role": "user", "content": content})
                else:
                    out.append({"role": "user", "content": m.text})
        return out

    def generate(self, *, system: str, messages: List[Message],
                 tools: List[dict]) -> AssistantTurn:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            tools=tools,
            messages=self._to_anthropic_messages(messages),
        )
        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name,
                                           arguments=dict(block.input)))
        return AssistantTurn(text="".join(text_parts), tool_calls=tool_calls)


def build_default_llm_client() -> LLMClient:
    """Tạo LLM client mặc định (Claude). Ném lỗi rõ ràng nếu chưa cài SDK/API key."""
    try:
        return ClaudeClient(model=config.LLM_MODEL, max_tokens=config.LLM_MAX_TOKENS)
    except ImportError as e:
        raise RuntimeError(
            "Chưa cài SDK 'anthropic'. Chạy: pip install anthropic"
        ) from e
