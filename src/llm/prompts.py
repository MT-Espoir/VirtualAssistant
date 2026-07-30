"""
Nạp system prompt theo case từ components/data/system_prompt.json (DRY: một nguồn).

Cấu trúc: {"base": ..., "router": ..., "cases": {tên_case: prompt_bổ_sung}}.
Thiếu file -> fallback tối thiểu để app vẫn chạy.
"""

import json
import os

from utils.logger import get_logger

logger = get_logger(__name__)

_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "components", "data", "system_prompt.json")

_FALLBACK = {
    "base": ("Bạn là trợ lý điều khiển máy tính bằng tiếng Việt. Với mọi yêu cầu hành "
             "động, gọi ngay công cụ phù hợp. Trả lời ngắn gọn, CHỈ bằng tiếng Việt. "
             "Kết thúc bằng '#emotion: neutral'."),
    "router": "",
    "cases": {},
}


def load(path=_FILE):
    """Trả dict {base, router, cases}. Lỗi/thiếu file -> fallback."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"base": data.get("base", _FALLBACK["base"]),
                "router": data.get("router", ""),
                "cases": data.get("cases", {})}
    except (OSError, ValueError) as e:
        logger.warning("Không đọc được system_prompt.json (%s) — dùng prompt tối thiểu.", e)
        return dict(_FALLBACK)


def base():
    return load()["base"]
