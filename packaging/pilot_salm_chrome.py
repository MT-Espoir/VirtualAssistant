"""Pilot media SALM bằng một Chrome profile tạm và audio local.

Không điều khiển hoặc đóng các Chrome process đã tồn tại. Script tạo WAV/HTML/profile
tạm, mở một app-window cô lập, đo GSMTC/WASAPI theo process rồi đóng đúng cây process
do chính nó tạo.
"""

import json
import math
import os
import subprocess
import sys
import tempfile
import time
import wave
from array import array
from pathlib import Path

import psutil


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from features.salm.media import GsmtcProbe, WasapiProbe  # noqa: E402


CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DURATION_SECONDS = 12.0
SAMPLE_INTERVAL = 0.5


def _write_quiet_tone(path, duration=DURATION_SECONDS, rate=22_050):
    amplitude = 1_600
    total = int(duration * rate)
    frames = array("h", (
        int(amplitude * math.sin(2 * math.pi * 440 * index / rate))
        for index in range(total)))
    if sys.byteorder != "little":
        frames.byteswap()
    with wave.open(path, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(frames.tobytes())


def _stop_tree(pid):
    try:
        root = psutil.Process(pid)
        processes = root.children(recursive=True) + [root]
    except psutil.Error:
        return
    for process in reversed(processes):
        try:
            process.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(processes, timeout=3)
    for process in alive:
        try:
            process.kill()
        except psutil.Error:
            pass


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    if not os.path.isfile(CHROME):
        print(json.dumps({"ok": False, "reason": "chrome_not_installed"}))
        return 3

    pilot_root = os.path.join(ROOT, "logs", "salm")
    os.makedirs(pilot_root, exist_ok=True)
    wasapi = WasapiProbe()
    gsmtc = GsmtcProbe(poll_seconds=SAMPLE_INTERVAL)
    process = None
    result = None
    gsmtc.start()
    try:
        with tempfile.TemporaryDirectory(prefix="chrome-pilot-", dir=pilot_root) as temp_dir:
            tone = os.path.join(temp_dir, "quiet-tone.wav")
            page = os.path.join(temp_dir, "pilot.html")
            profile = os.path.join(temp_dir, "profile")
            _write_quiet_tone(tone)
            Path(page).write_text(
                '<!doctype html><meta charset="utf-8"><title>SALM media pilot</title>'
                '<body style="background:#111;color:#ddd;font:24px sans-serif">'
                'SALM media pilot — cửa sổ sẽ tự đóng.'
                '<audio autoplay loop src="quiet-tone.wav"></audio></body>',
                encoding="utf-8")
            process = subprocess.Popen(
                [CHROME, f"--user-data-dir={profile}", "--no-first-run",
                 "--no-default-browser-check", "--disable-extensions",
                 "--disable-background-networking",
                 "--autoplay-policy=no-user-gesture-required",
                 "--window-size=640,360", f"--app={Path(page).as_uri()}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            samples = 0
            wasapi_hits = 0
            gsmtc_hits = 0
            deadline = time.monotonic() + DURATION_SECONDS + 4
            while time.monotonic() < deadline and process.poll() is None:
                active = wasapi.sample()
                sessions = gsmtc.apps()
                samples += 1
                wasapi_hits += int("chrome" in active)
                gsmtc_hits += int("chrome" in sessions)
                time.sleep(SAMPLE_INTERVAL)
            result = {
                "ok": wasapi_hits > 0 or gsmtc_hits > 0,
                "samples": samples,
                "wasapi_chrome_hits": wasapi_hits,
                "gsmtc_chrome_hits": gsmtc_hits,
                "gsmtc_available": gsmtc.available,
                "isolated_profile": True,
                "raw_peaks_persisted": False,
            }
            _stop_tree(process.pid)
            process = None
    finally:
        gsmtc.stop()
        if process is not None:
            _stop_tree(process.pid)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result and result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
