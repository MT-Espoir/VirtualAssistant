"""Khai báo Feature `schedule`."""

from features.contract import Feature
from features.schedule import tools
from features.schedule.prompt import CASE_SCHEDULE, ROUTER_HINT

FEATURE = Feature(
    name="schedule",
    register=tools.register,
    requires=('scheduler',),
    prompt=CASE_SCHEDULE,
    router_hint=ROUTER_HINT,
    max_spec_chars=1_700,
)
