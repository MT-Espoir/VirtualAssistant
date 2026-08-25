"""
Định nghĩa "tool" (công cụ) và registry cho agent.

Mỗi Tool = tên + mô tả + JSON schema tham số + hàm thực thi. LLM đọc mô tả +
schema để quyết định gọi tool nào với tham số gì (tool-calling). Registry gom
các tool lại, cung cấp:
  - specs():  danh sách định nghĩa tool để gửi cho LLM
  - run():    thực thi tool theo tên với tham số LLM sinh ra

Registry KHÔNG còn tự biết tool nào tồn tại: mỗi tính năng tự đăng ký tool của mình
qua hợp đồng ở `features/contract.py`, và `features/registry.py::build_registry` gom
chúng lại theo danh mục `features/catalog.py`.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Dict, List

from utils.config import config
from utils.logger import get_logger
from utils.text_norm import strip_accents

logger = get_logger(__name__)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict          # JSON Schema cho tham số
    handler: Callable[..., str]  # nhận **kwargs theo schema, trả về chuỗi
    destructive: bool = False    # True = khó hoàn tác -> Agent hỏi xác nhận trước khi chạy
    confirm_message: Callable[..., str] = None  # (**args) -> cụm mô tả việc sẽ làm, để hỏi
    # (**args) -> dict để HIỆN RA cho người dùng xem trước khi xác nhận, hoặc None nếu
    # không có gì đáng xem. Chỉ có nghĩa với tool destructive (Agent gọi lúc hoãn hành
    # động). Dùng cho nội dung mà TAI không kiểm được — thư dài, văn bản do LLM viết ra.
    preview: Callable[..., dict] = None
    # True = kết quả trả về ĐÃ là câu tiếng Việt hoàn chỉnh, đọc thẳng cho người dùng được.
    # Agent dùng cờ này để BỎ lượt LLM soạn lời (tiết kiệm 1 call) — chỉ khi model gọi đúng
    # MỘT tool này và không làm gì thêm. Đánh đổi: câu trả lời không mang giọng persona,
    # nên chỉ bật cho tool mà output vốn đã tự nhiên. KHÔNG bật cho tool cần diễn giải
    # (tìm web, đọc mail, tóm tắt trang).
    speakable: bool = False

    def spec(self) -> dict:
        """Định nghĩa tool gửi cho LLM (định dạng Anthropic tool-use)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        if tool.name in self._tools:
            raise ValueError(f"Tool trùng tên: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> List[str]:
        """Tên tool THEO ĐÚNG thứ tự đăng ký (dict giữ thứ tự chèn).

        Bộ nạp feature so tên trước/sau khi gọi `register` để biết feature nào đăng ký
        tool nào — nhờ vậy `CASE_TOOLS` suy ra được thay vì chép tay.
        """
        return list(self._tools)

    def specs(self) -> List[dict]:
        return [t.spec() for t in self._tools.values()]

    def run(self, name: str, arguments: dict) -> str:
        """Thực thi tool. Ném KeyError nếu không có tool tên đó."""
        tool = self._tools[name]
        logger.debug("Chạy tool %s(%s)", name, arguments)
        return tool.handler(**(arguments or {}))

# Bộ tool mặc định (điều khiển máy tính) dựng từ AssistantActions
