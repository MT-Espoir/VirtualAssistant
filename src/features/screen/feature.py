"""Khai báo Feature `screen`."""

from features.contract import Feature
from features.screen import tools
from features.screen.prompt import CASE_SCREEN

FEATURE = Feature(
    name="screen",
    register=tools.register,
    requires=('screen',),
    prompt=CASE_SCREEN,
    max_spec_chars=1_200,
)
