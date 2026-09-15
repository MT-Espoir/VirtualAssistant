"""Pilot media SALM bằng VLC thật, không dùng Internet hoặc nội dung cá nhân.

Script tạo tone WAV rất nhỏ trong thư mục tạm, mở một VLC headless riêng, lấy mẫu
GSMTC/WASAPI theo process rồi xóa tone. Nếu VLC đã chạy từ trước, script từ chối để
không đụng nhầm phiên media của người dùng.
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

import psutil


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from features.salm.media import GsmtcProbe, WasapiProbe  # noqa: E402
from features.salm.windows import normalize_app_id  # noqa: E402


VLC = r"C:\Program Files\VideoLAN\VLC\vlc.exe"
DURATION_SECONDS = 12.0
SAMPLE_INTERVAL = 0.5


def _vlc_is_running():
    for process in psutil.process_iter(("name",)):
        try:
            if normalize_app_id(process.info.get("name")) == "vlc":
                return True
        except (psutil.Error, OSError):
            continue
    return False


def _write_quiet_tone(path, duration=DURATION_SECONDS, rate=22_050):
    amplitude = 1_600  # khoảng 5% full-scale; VLC còn hạ volume xuống 1/16.
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


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    if not os.path.isfile(VLC):
        print(json.dumps({"ok": False, "reason": "vlc_not_installed"}))
        return 3
    if _vlc_is_running():
        print(json.dumps({"ok": False, "reason": "vlc_already_running"}))
        return 4

    pilot_root = os.path.join(ROOT, "logs", "salm")
    os.makedirs(pilot_root, exist_ok=True)
    wasapi = WasapiProbe()
    gsmtc = GsmtcProbe(poll_seconds=SAMPLE_INTERVAL)
    process = None
    result = None
    gsmtc.start()
    try:
        with tempfile.TemporaryDirectory(prefix="vlc-pilot-", dir=pilot_root) as temp_dir:
            tone = os.path.join(temp_dir, "quiet-tone.wav")
            _write_quiet_tone(tone)
            process = subprocess.Popen(
                [VLC, "--intf", "dummy", "--no-video", "--no-one-instance",
                 "--play-and-exit", "--volume=16", tone],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            samples = 0
            wasapi_hits = 0
            gsmtc_hits = 0
            deadline = time.monotonic() + DURATION_SECONDS + 4
            while time.monotonic() < deadline and process.poll() is None:
                active = wasapi.sample()
                sessions = gsmtc.apps()
                samples += 1
                wasapi_hits += int("vlc" in active)
                gsmtc_hits += int("vlc" in sessions)
                time.sleep(SAMPLE_INTERVAL)
            result = {
                "ok": wasapi_hits > 0 or gsmtc_hits > 0,
                "samples": samples,
                "wasapi_vlc_hits": wasapi_hits,
                "gsmtc_vlc_hits": gsmtc_hits,
                "gsmtc_available": gsmtc.available,
                "raw_peaks_persisted": False,
            }
    finally:
        gsmtc.stop()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result and result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
