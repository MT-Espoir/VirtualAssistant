"""Khai báo Feature `system`."""

from features.contract import Feature
from features.system import tools
from features.system.prompt import CASE_SYSTEM

FEATURE = Feature(
    name="system",
    register=tools.register,
    requires=('actions',),
    prompt=CASE_SYSTEM,
    max_spec_chars=2_500,
)
