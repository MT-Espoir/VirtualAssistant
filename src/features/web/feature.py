"""Khai báo Feature `web`."""

from features.contract import Feature
from features.web import tools
from features.web.prompt import CASE_WEB

FEATURE = Feature(
    name="web",
    register=tools.register,
    requires=('actions',),
    prompt=CASE_WEB,
    max_spec_chars=4_200,
)
