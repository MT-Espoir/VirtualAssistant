"""Khai báo Feature `weather`."""

from features.contract import Feature
from features.weather import tools
from features.weather.prompt import CASE_WEATHER, ROUTER_HINT

FEATURE = Feature(
    name="weather",
    register=tools.register,
    requires=('actions',),
    prompt=CASE_WEATHER,
    router_hint=ROUTER_HINT,
    max_spec_chars=600,
)
