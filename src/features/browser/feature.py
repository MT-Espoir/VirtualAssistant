"""Khai báo Feature `browser`."""

from features.contract import Feature
from features.browser import tools
from features.browser.prompt import CASE_BROWSER, ROUTER_HINT

FEATURE = Feature(
    name="browser",
    register=tools.register,
    requires=('browser',),
    prompt=CASE_BROWSER,
    router_hint=ROUTER_HINT,
    max_spec_chars=2_600,
)
