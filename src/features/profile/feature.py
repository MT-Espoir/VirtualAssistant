"""Khai báo Feature `profile`."""

from features.contract import Feature
from features.profile import tools
from features.profile.prompt import CASE_PROFILE, ROUTER_HINT

FEATURE = Feature(
    name="profile",
    register=tools.register,
    requires=('profile',),
    prompt=CASE_PROFILE,
    router_hint=ROUTER_HINT,
    max_spec_chars=1_700,
)
