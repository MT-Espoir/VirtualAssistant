"""Khai báo Feature `system`."""

from features.contract import Feature
from features.system import tools
from features.system.fast import FAST_PATHS
from features.system.prompt import CASE_SYSTEM, ROUTER_HINT

FEATURE = Feature(
    name="system",
    register=tools.register,
    fast_paths=FAST_PATHS,
    requires=('actions',),
    prompt=CASE_SYSTEM,
    router_hint=ROUTER_HINT,
    # 2.500 -> 2.900 (2026-09-11, nhận `list_processes` + `power`) -> 3.900 (2026-09-12,
    # nhận nốt Tầng 1: `kill_process`, `keep_awake`, `audio_device`).
    # `docs/system_admin_spec.md` §4. Nâng CÓ CÂN NHẮC, không phải nới cho hết đỏ: đây là
    # feature quản trị máy, nó đáng phần ngân sách lớn hơn mức 2.000 mặc định, và từ khi
    # `IndexedTools` bật thì tool ngoài bộ lõi KHÔNG còn tính vào payload mỗi lượt nữa —
    # con số cần canh đã chuyển sang `tests/test_bo_loi.py` (cỡ bộ lõi).
    max_spec_chars=3_900,
)
