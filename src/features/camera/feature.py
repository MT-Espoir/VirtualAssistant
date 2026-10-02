"""Camera background pipeline and its explicit webcam control tool."""

from features.contract import Feature
from features.camera import tools


FEATURE = Feature(
    name="camera",
    register=tools.register,
    requires=("camera",),
    prompt="Tắt camera/webcam của Alice dùng turn_off_webcam, không dùng kill_process hay close_app.",
    router_hint="- camera: tắt webcam/camera của Alice",
    max_spec_chars=250,
)
