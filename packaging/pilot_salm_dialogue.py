"""Eval paraphrase SALM-1.1a bằng LLM đang cấu hình, hoàn toàn không mutate state.

Chạy từ gốc repo:
    python packaging/pilot_salm_dialogue.py

Script chỉ gọi ``CareDialogue.classify`` với tool schema cô lập, không dựng Agent, không
ghi SALM storage và không bật DND. Các câu fixture được in ở terminal để người chạy review.
"""

import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from features.salm.dialogue import CareDialogue  # noqa: E402
from llm.client import build_default_llm_client  # noqa: E402


CASES = (
    ("Tôi sẽ cố làm thêm tí nữa", ("snooze", None, None, None)),
    ("Để tôi chốt nốt đoạn này", ("snooze", None, None, None)),
    ("Cho tôi thêm 20 phút", ("snooze", 20, None, None)),
    ("Tôi nghỉ một chút đây", ("accept", None, None, None)),
    ("Ừ, mình nghỉ thôi", ("accept", None, None, None)),
    ("Không sao đâu, tôi vẫn ổn", ("decline_once", None, None, None)),
    ("Bỏ qua lần nhắc này nhé", ("decline_once", None, None, None)),
    ("Đừng nhắc tôi trong hai giờ", ("care_dnd", 120, None, "deadline")),
    ("Tắt nhắc nghỉ 30 phút", ("care_dnd", 30, None, "deadline")),
    ("Để tôi yên tới 17:00 rồi nhắc nghỉ sau", ("care_dnd", None, "17:00", "deadline")),
    ("Để tôi hoàn thành công việc này", ("care_dnd", None, None, "work_cycle_reset")),
    ("Đừng chen vào phiên làm việc này nữa", ("care_dnd", None, None, "work_cycle_reset")),
    ("Tạm thời đừng nhắc nghỉ nữa", ("care_dnd", None, None, "app_session")),
    ("Nhắc nghỉ lại đi", ("resume_care", None, None, "explicit_resume")),
    ("Bật lại nhắc nghỉ cho tôi", ("resume_care", None, None, "explicit_resume")),
    ("Mở Chrome", ("unrelated", None, None, None)),
    ("Tăng âm lượng lên", ("unrelated", None, None, None)),
    ("Đừng làm phiền tôi", ("unclear", None, None, None)),
    ("Đừng bao giờ nhắc nữa", ("unclear", None, None, None)),
    ("Hoãn mười phút và tắt luôn mọi thông báo", ("unclear", None, None, None)),
)


def _shape(intent):
    if intent is None:
        return None
    return (intent.intent, intent.requested_minutes, intent.until_local_time,
            intent.release_condition)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    dialogue = CareDialogue(build_default_llm_client())
    passed = 0
    for index, (utterance, expected) in enumerate(CASES, 1):
        actual = _shape(dialogue.classify(utterance, "work_engagement", "soft"))
        ok = actual == expected
        passed += int(ok)
        print(f"{'PASS' if ok else 'FAIL'} {index:02d}: {utterance}")
        if not ok:
            print(f"         expected={expected}")
            print(f"         actual  ={actual}")
    accuracy = 100.0 * passed / len(CASES)
    print(f"\nKết quả: {passed}/{len(CASES)} = {accuracy:.1f}%")
    print("Không có state SALM/DND nào được thay đổi.")
    return 0 if accuracy >= 95.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
