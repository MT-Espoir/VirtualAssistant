"""Feature declaration for Activity Insights."""

from features.activity_insights import tools
from features.activity_insights.prompt import CASE_ACTIVITY, ROUTER_HINT
from features.contract import Feature


FEATURE = Feature(
    name="activity",
    register=tools.register,
    requires=("activity_insights",),
    prompt=CASE_ACTIVITY,
    router_hint=ROUTER_HINT,
    max_spec_chars=900,
)
