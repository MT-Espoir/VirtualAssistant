"""Pilot ngôn ngữ lifecycle greeting, không khởi động SALM hoặc phát TTS.

Chạy từ gốc repo: ``python packaging/pilot_salm_welcome.py``.
Chỉ gửi loại event, style hint và cách xưng hô từ UserProfile cho provider LLM.
Không đọc ghi chú, history Agent hay activity,
không lưu state và không làm thay đổi DND/clock.
"""

import argparse
import os
import sys
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from features.salm.welcome import WelcomeDialogue, welcome_fallback  # noqa: E402
from llm.client import build_default_llm_client  # noqa: E402
from memory.profile import UserProfile  # noqa: E402
from utils.config import config  # noqa: E402


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=1,
                        help="Số cặp startup/return, mặc định 1")
    args = parser.parse_args()
    profile = UserProfile(config.USER_PROFILE_PATH or None)
    dialogue = WelcomeDialogue(
        build_default_llm_client(),
        timeout_seconds=config.SALM_WELCOME_LLM_TIMEOUT_SECONDS,
        address_form_provider=profile.get_address_form)
    generated = 0
    for _ in range(max(1, args.rounds)):
        for kind in ("startup", "return"):
            started = time.monotonic()
            text = dialogue.generate(kind)
            seconds = time.monotonic() - started
            source = ("fallback" if text == welcome_fallback(
                kind, profile.get_address_form()) else "LLM")
            generated += int(source == "LLM")
            print(f"{kind} [{source}, {seconds:.2f}s]: {text}")
    print(f"LLM generated: {generated}/{max(1, args.rounds) * 2}")
    return 0 if generated else 1


if __name__ == "__main__":
    raise SystemExit(main())
