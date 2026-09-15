"""Chạy SALM shadow độc lập trong một cửa sổ thời gian ngắn và in diagnostic hẹp.

Không khởi động LLM, micro, TTS hoặc care cue. Dữ liệu interval/metric được ghi vào
``logs/salm`` theo cùng schema TTL 14 ngày của runtime thật.
"""

import argparse
import json
import os
import sys
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from features.salm import SalmRuntime  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="SALM shadow desktop probe")
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--wasapi", action="store_true",
                        help="bật WASAPI fallback trong riêng lần probe")
    args = parser.parse_args(argv)
    seconds = max(1.0, min(300.0, args.seconds))
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    runtime = SalmRuntime(
        data_dir=os.path.join(ROOT, "logs", "salm"),
        poll_seconds=1.0,
        wasapi_fallback=args.wasapi,
        policy_shadow=True,
        silent_care=False,
    )
    runtime.start()
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        diagnostic = runtime.diagnostic()
    finally:
        runtime.stop()

    print(json.dumps(diagnostic, ensure_ascii=False, indent=2))
    return 0 if diagnostic["runtime"]["last_error"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
