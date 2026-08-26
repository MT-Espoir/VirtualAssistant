"""Khai báo Feature `screen`."""

from features.contract import Feature
from features.screen import tools
from features.screen.fast import FAST_PATHS
from features.screen.prompt import CASE_SCREEN, ROUTER_HINT

FEATURE = Feature(
    name="screen",
    register=tools.register,
    fast_paths=FAST_PATHS,
    requires=('screen',),
    prompt=CASE_SCREEN,
    router_hint=ROUTER_HINT,
    max_spec_chars=1_200,
)
