"""Khai báo Feature `browser`."""

from features.contract import Feature
from features.browser import tools
from features.browser.prompt import CASE_BROWSER

FEATURE = Feature(
    name="browser",
    register=tools.register,
    requires=('browser',),
    prompt=CASE_BROWSER,
    max_spec_chars=2_600,
)
