"""Khai báo Feature `web`."""

from features.contract import Feature
from features.web import tools
from features.web.prompt import CASE_WEB, ROUTER_HINT

FEATURE = Feature(
    name="web",
    register=tools.register,
    requires=('actions',),
    prompt=CASE_WEB,
    router_hint=ROUTER_HINT,
    max_spec_chars=3_600,
)
