"""Khai báo Feature `web`."""

from features.contract import Feature
from features.web import tools

FEATURE = Feature(
    name="web",
    register=tools.register,
    requires=('browser',),
    max_spec_chars=2_200,
)
