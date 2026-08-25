"""Cấu hình pytest: thêm thư mục src vào sys.path để import core/, nlp/, ..."""

import os
import sys

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def full_registry(actions=None):
    """Registry có ĐỦ mọi nhóm tool, dựng qua CẢ HAI đường trong lúc migrate feature-module.

    Tiêm mock cho MỌI trường của FeatureContext nên không feature nào bị bỏ qua vì
    thiếu dependency — dùng khi cần đối chiếu toàn bộ payload hoặc bảng case->tool.
    """
    import dataclasses
    from unittest.mock import MagicMock

    from features.contract import FeatureContext
    from features.registry import build_registry

    ctx_kwargs = {f.name: MagicMock() for f in dataclasses.fields(FeatureContext)}
    if actions is not None:
        ctx_kwargs["actions"] = actions
    # `mcp` phải là None: tool MCP sinh ĐỘNG từ danh sách server trả về, tiêm mock vào là
    # đăng ký một mớ tool không tên tuổi rồi làm lệch mọi phép đếm payload.
    ctx_kwargs["mcp"] = None
    return build_registry(FeatureContext(**ctx_kwargs))[0]


def registry_with(actions=None, **ctx_kwargs):
    """Registry lõi + các feature nạp bằng ĐÚNG những dependency truyền vào.

    Thay cho lối cũ `build_default_registry(mock, contacts=..., mcp=...)`: các dịch vụ đó
    không còn là tham số của hàm dựng nữa mà nằm trong `FeatureContext`. Feature nào
    thiếu dependency sẽ tự bỏ qua, nên chỉ tool của phần truyền vào được đăng ký — đúng
    ý các test gọi kiểu này.
    """
    import dataclasses
    from unittest.mock import MagicMock

    from features.contract import FeatureContext
    from features.registry import build_registry

    truong_ctx = {f.name for f in dataclasses.fields(FeatureContext)}
    ctx = {k: v for k, v in ctx_kwargs.items() if k in truong_ctx}
    # `actions` là tham số riêng của helper nên không rơi vào **ctx_kwargs — phải đưa vào
    # ctx bằng tay, nếu không feature `web` thấy ctx.actions is None rồi nổ lúc chạy tool.
    ctx.setdefault("actions", actions or MagicMock())
    return build_registry(FeatureContext(**ctx))[0]
