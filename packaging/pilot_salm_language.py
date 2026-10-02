"""Pilot SALM-1.1b/1.2 với context tổng hợp, không mutate SALM và không phát TTS.

Không đọc UserProfile. ``--address-form`` chỉ nhận giá trị do người chạy truyền; mặc định
dùng "anh" để pilot không gửi dữ liệu cá nhân sang provider.
"""

import argparse
import os
import sys
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from features.salm.care_action import CareActionResult  # noqa: E402
from features.salm.care_language import CareLanguage  # noqa: E402
from features.salm.checkin import checkin_text  # noqa: E402
from llm.client import build_default_llm_client  # noqa: E402
from utils.config import config  # noqa: E402


REPLIES = (
    CareActionResult(True, True, "snooze", "Được rồi, thêm 10 phút nhé.",
                     "short_delay", 10),
    CareActionResult(True, True, "timed_dnd",
                     "Được ạ, em sẽ không nhắc nghỉ trong 120 phút.",
                     "explicit_duration", 120),
    CareActionResult(True, True, "cycle_dnd",
                     "Được ạ, em sẽ không chen vào phiên làm việc này nữa.",
                     "finish_current_work"),
    CareActionResult(True, True, "session_dnd",
                     "Được ạ, em sẽ tạm ngừng nhắc nghỉ trong phiên này.",
                     "suppress_session"),
    CareActionResult(True, True, "resume_care",
                     "Được ạ, em đã bật lại nhắc nghỉ.", "explicit_resume"),
    CareActionResult(True, True, "decline_once",
                     "Vâng, em sẽ không nhắc lại lượt này.", "explicit_decline"),
    CareActionResult(True, True, "accept", "Vâng, mình nghỉ một chút nhé.",
                     "explicit_accept"),
)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--address-form", default="anh")
    args = parser.parse_args()
    language = CareLanguage(
        build_default_llm_client(),
        timeout_seconds=config.SALM_CARE_LLM_TIMEOUT_SECONDS,
        address_form_provider=lambda: args.address_form)
    generated = 0
    total = 0

    for clock, level in (("work_engagement", "soft"),
                         ("work_engagement", "soft"),
                         ("screen_exposure", "hard")):
        fallback = checkin_text(clock, level, args.address_form)
        started = time.monotonic()
        text = language.generate_initial(clock, level)
        elapsed = time.monotonic() - started
        source = "fallback" if text == fallback else "LLM"
        generated += int(source == "LLM")
        total += 1
        print(f"initial {clock}/{level} [{source}, {elapsed:.2f}s]: {text}")
        language.wait_until_idle(15.0)
        candidate = language.last_candidate()
        if source == "fallback" and candidate and not candidate[1]:
            print(f"  rejected candidate: {candidate[0]}")

    for result in REPLIES:
        started = time.monotonic()
        text = language.generate_reply(result, "work_engagement", "soft")
        elapsed = time.monotonic() - started
        source = "fallback" if text == result.reply else "LLM"
        generated += int(source == "LLM")
        total += 1
        print(f"reply {result.action} [{source}, {elapsed:.2f}s]: {text}")
        language.wait_until_idle(15.0)
        candidate = language.last_candidate()
        if source == "fallback" and candidate and not candidate[1]:
            print(f"  rejected candidate: {candidate[0]}")

    print(f"LLM generated: {generated}/{total}")
    print("Không có state SALM/DND nào được thay đổi; không phát TTS.")
    return 0 if generated else 1


if __name__ == "__main__":
    raise SystemExit(main())
