"""Khai báo Feature `pim`."""

from features.contract import Feature
from features.pim import tools
from features.pim.prompt import CASE_PIM

FEATURE = Feature(
    name="pim",
    register=tools.register,
    # KHÔNG khai `requires`: hai nguồn độc lập, thiếu một cái thì phần kia
    # vẫn dùng được — `register` tự bỏ qua nguồn nào là None.
    prompt=CASE_PIM,
    max_spec_chars=1_500,
)
