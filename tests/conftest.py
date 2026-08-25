"""Cấu hình pytest: thêm thư mục src vào sys.path để import core/, nlp/, ..."""

import os
import sys

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def full_registry(actions=None):
    """Registry có ĐỦ mọi nhóm tool, dựng qua CẢ HAI đường trong lúc migrate feature-module.

    Nhóm chưa chuyển vẫn nằm ở `build_default_registry`, nhóm đã chuyển nạp sau theo
    `FEATURES`. Thứ tự này giữ đúng thứ tự tool cũ vì mỗi bước migrate rút khối đăng ký
    CUỐI CÙNG còn lại — xem `features/catalog.py`.

    Tham số của `build_default_registry` được suy ra bằng introspection: mỗi bước migrate
    lại bớt một tham số, helper này khỏi phải sửa theo từng bước.
    """
    import dataclasses
    import inspect
    from unittest.mock import MagicMock

    from agent.tools import build_default_registry
    from features.catalog import FEATURES
    from features.contract import FeatureContext, load_features

    con_lai = list(inspect.signature(build_default_registry).parameters)[1:]
    reg = build_default_registry(actions or MagicMock(),
                                 **{ten: MagicMock() for ten in con_lai})

    ctx_kwargs = {f.name: MagicMock() for f in dataclasses.fields(FeatureContext)}
    if actions is not None:
        ctx_kwargs["actions"] = actions
    # `mcp` phải là None: tool MCP sinh ĐỘNG từ danh sách server trả về, tiêm mock vào là
    # đăng ký một mớ tool không tên tuổi rồi làm lệch mọi phép đếm payload.
    ctx_kwargs["mcp"] = None
    load_features(reg, FeatureContext(**ctx_kwargs), FEATURES)
    return reg


def registry_with(actions=None, **ctx_kwargs):
    """Registry lõi + các feature nạp bằng ĐÚNG những dependency truyền vào.

    Thay cho lối cũ `build_default_registry(mock, contacts=..., mcp=...)`: sau khi tách
    feature, các dịch vụ đó không còn là tham số của hàm dựng nữa mà nằm trong
    `FeatureContext`. Feature nào thiếu dependency sẽ tự bỏ qua, nên chỉ tool của phần
    truyền vào được đăng ký — đúng ý các test gọi kiểu này.
    """
    import dataclasses
    import inspect
    from unittest.mock import MagicMock

    from agent.tools import build_default_registry
    from features.catalog import FEATURES
    from features.contract import FeatureContext, load_features

    # Một tên có thể thuộc CẢ HAI nơi trong lúc migrate: `profile` vừa là tham số của
    # `build_default_registry` (tool thời tiết dùng địa điểm mặc định) vừa là trường của
    # FeatureContext (feature `profile`). Chuyển tiếp sang bên nào nhận được thì nhận.
    con_lai = set(inspect.signature(build_default_registry).parameters)
    truong_ctx = {f.name for f in dataclasses.fields(FeatureContext)}

    actions = actions or MagicMock()
    reg = build_default_registry(
        actions, **{k: v for k, v in ctx_kwargs.items() if k in con_lai})

    # `actions` là tham số riêng của helper nên không rơi vào **ctx_kwargs — phải đưa vào
    # ctx bằng tay, nếu không feature `web` sẽ thấy ctx.actions is None rồi nổ lúc chạy tool.
    ctx = {k: v for k, v in ctx_kwargs.items() if k in truong_ctx}
    ctx.setdefault("actions", actions)
    load_features(reg, FeatureContext(**ctx), FEATURES)
    return reg
