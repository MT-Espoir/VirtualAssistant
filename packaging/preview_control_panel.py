"""Render the real HUD with fixture data; never starts camera, IoT or the agent."""

import sys
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import ImageGrab
from features.catalog import FEATURES
from features.contract import LoadReport, LoadedFeature
from services.control_panel import SystemControls
from ui.control_panel import control_blocks
from ui.hud import HudPanel
from utils.control_settings import ControlSettings


def main():
    output = ROOT / "artifacts" / "control-panel"
    output.mkdir(parents=True, exist_ok=True)
    camera = SimpleNamespace(status=lambda: {
        "state": "available", "paused": False, "present": True,
        "face_auth": {"enabled": True, "enrolled": True, "state": "ready",
                      "samples": 0, "error": None},
    })
    report = LoadReport(loaded=[LoadedFeature(f.name) for f in FEATURES])
    service = SystemControls(report, camera, store=ControlSettings(output / "preview-settings.json"))
    snapshot = service.snapshot()
    root = tk.Tk()
    root.withdraw()
    panel = HudPanel(root, title="BẢNG ĐIỀU KHIỂN", size=(520, 700), alpha=1.0)
    try:
        for section, name in (("Thiết bị trong phòng", "iot"), ("Webcam", "webcam"),
                              ("Nhóm công cụ", "features")):
            panel.show(control_blocks(snapshot, section))
            root.update()
            panel.win.geometry("+60+60")
            root.update()
            root.after(250, root.quit)
            root.mainloop()
            win = panel.win
            box = (win.winfo_rootx(), win.winfo_rooty(),
                   win.winfo_rootx() + win.winfo_width(), win.winfo_rooty() + win.winfo_height())
            ImageGrab.grab(bbox=box).save(output / (name + ".png"))
            print(output / (name + ".png"))
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
