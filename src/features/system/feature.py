"""Khai báo Feature `system`."""

from features.contract import Feature
from features.system import tools
from features.system.fast import FAST_PATHS
from features.system.prompt import CASE_SYSTEM, ROUTER_HINT

FEATURE = Feature(
    name="system",
    register=tools.register,
    fast_paths=FAST_PATHS,
    requires=('actions',),
    prompt=CASE_SYSTEM,
    router_hint=ROUTER_HINT,
    max_spec_chars=2_500,
)
