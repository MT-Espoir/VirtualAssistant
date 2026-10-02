"""Model-facing control for the webcam owned by Alice."""

from agent.tools import Tool
from features.camera.commands import turn_off_webcam


def register(reg, ctx):
    reg.register(Tool(
        name="turn_off_webcam",
        description="Tắt webcam/camera của Alice; dừng capture.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda: turn_off_webcam(ctx.camera),
        # Compound requests may need another tool in a later iteration; do not
        # trigger the Agent's single-tool speech shortcut and truncate that work.
    ))
