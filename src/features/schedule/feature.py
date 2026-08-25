"""Khai báo Feature `schedule`."""

from features.contract import Feature
from features.schedule import tools
from features.schedule.prompt import CASE_SCHEDULE

FEATURE = Feature(
    name="schedule",
    register=tools.register,
    requires=('scheduler',),
    prompt=CASE_SCHEDULE,
    max_spec_chars=1_700,
)
