"""Khai báo Feature `profile`."""

from features.contract import Feature
from features.profile import tools
from features.profile.prompt import CASE_PROFILE

FEATURE = Feature(
    name="profile",
    register=tools.register,
    requires=('profile',),
    prompt=CASE_PROFILE,
    max_spec_chars=1_600,
)
