"""Khai báo Feature `task`."""

from features.contract import Feature
from features.task import tools
from features.task.prompt import CASE_TASK, ROUTER_HINT

FEATURE = Feature(
    name="task",
    register=tools.register,
    # KHÔNG khai `requires`: hai nguồn độc lập, thiếu một cái thì phần kia
    # vẫn dùng được — `register` tự bỏ qua nguồn nào là None.
    prompt=CASE_TASK,
    router_hint=ROUTER_HINT,
    max_spec_chars=2_800,
)
