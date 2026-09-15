"""Preview thủ công care pulse SALM-0B, không cần LLM/mic/TTS.

Chạy từ gốc repo:
    python packaging/preview_salm_care.py

Avatar lần lượt pulse ở opacity 1.0, 0.7, 0.25 rồi chạy một ca cancel giữa nhịp.
Cửa sổ tự đóng sau khoảng 11 giây. Script không chụp hoặc lưu nội dung màn hình.
"""

import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from ui.avatar import AvatarWindow  # noqa: E402
from utils.events import AssistantBus  # noqa: E402


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    bus = AssistantBus()
    window = AvatarWindow(bus=bus, title="SALM-0B — Care pulse preview",
                          scale=0.7, opacity=1.0, emotion_hold_ms=0)

    def pulse(opacity, token):
        print(f"SALM care preview: opacity={opacity:g}, token={token}", flush=True)
        window.set_opacity(opacity)
        bus.emit_care("pulse", token)

    window.root.after(600, lambda: pulse(1.0, "preview-1.0"))
    window.root.after(3200, lambda: pulse(0.7, "preview-0.7"))
    window.root.after(5800, lambda: pulse(0.25, "preview-0.25"))
    window.root.after(8400, lambda: pulse(0.7, "preview-cancel"))
    window.root.after(8900, lambda: bus.emit_care("cancel", "preview-cancel"))
    window.root.after(10500, window.root.destroy)
    window.run()
    print("SALM care preview: hoàn tất.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
