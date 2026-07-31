"""Bộ nhớ NGƯỜI DÙNG bền vững — các sự thật cá nhân giúp trợ lý "nhớ bạn".

Khác bộ nhớ HỘI THOẠI (agent.history — vài lượt nói gần đây): đây là sự thật LÂU DÀI
(tên, cách xưng hô, địa điểm mặc định, vài ghi chú) sống qua mọi phiên. Trợ lý học khi
người dùng nói ra (tool remember_about_user) và được bơm tóm tắt vào system prompt để
cá nhân hoá + xưng hô đúng.

Phần LOGIC thuần (cập nhật/tóm tắt dict) tách khỏi I/O để test được và suy biến an toàn
khi thiếu/hỏng file. (Thay hẳn thiết kế cũ command-history/daily-stats — vốn dựa trên
intent/entities không còn tồn tại trong kiến trúc tool-calling hiện tại.)
"""

import json
import os

from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "user_data", "profile.json")


# auto_facts: sự thật TỰ TRÍCH từ hội thoại (độ tin thấp hơn notes tường minh) -> giữ
# riêng để phân biệt nguồn và giới hạn số lượng.
_MAX_AUTO_FACTS = 20


def _empty():
    return {"name": None, "address_form": None,
            "preferences": {"default_location": None}, "notes": [], "auto_facts": []}


def apply_update(data, name=None, address_form=None, location=None, note=None):
    """Cập nhật (thuần) hồ sơ từ các trường KHÔNG rỗng. Trả (data_mới, [mô tả thay đổi]).

    Không sửa `data` gốc (copy sâu). Ghi chú trùng thì không thêm lại.
    """
    data = json.loads(json.dumps(data)) if data else _empty()
    data.setdefault("preferences", {})
    data.setdefault("notes", [])
    data.setdefault("auto_facts", [])
    changes = []
    if name and name.strip():
        data["name"] = name.strip()
        changes.append(f"tên {data['name']}")
    if address_form and address_form.strip():
        data["address_form"] = address_form.strip()
        changes.append(f"xưng hô '{data['address_form']}'")
    if location and location.strip():
        data["preferences"]["default_location"] = location.strip()
        changes.append(f"địa điểm mặc định {location.strip()}")
    if note and note.strip():
        n = note.strip()
        if n not in data["notes"]:
            data["notes"].append(n)
        changes.append(f'ghi chú "{n}"')
    return data, changes


def summarize(data):
    """Câu ngắn mô tả người dùng để bơm vào system prompt. '' nếu chưa biết gì."""
    if not data:
        return ""
    parts = []
    if data.get("name"):
        parts.append(f"Tên người dùng: {data['name']}.")
    if data.get("address_form"):
        parts.append(f"Xưng hô với người dùng là '{data['address_form']}'.")
    loc = (data.get("preferences") or {}).get("default_location")
    if loc:
        parts.append(f"Địa điểm mặc định của người dùng: {loc}.")
    notes = data.get("notes") or []
    if notes:
        parts.append("Cần nhớ: " + "; ".join(notes) + ".")
    auto = data.get("auto_facts") or []
    if auto:
        parts.append("Quan sát từ hội thoại: " + "; ".join(auto) + ".")
    if not parts:
        return ""
    return "Thông tin người dùng (dùng để cá nhân hoá và xưng hô đúng): " + " ".join(parts)


class UserProfile:
    """Hồ sơ người dùng lưu JSON. `path=None` -> file mặc định trong user_data/."""

    def __init__(self, path=None):
        self.path = path or _DEFAULT_PATH
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return _empty()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else _empty()
        except (OSError, ValueError) as e:
            logger.warning("Không đọc được hồ sơ người dùng: %s — dùng hồ sơ trống.", e)
            return _empty()

    def _save(self):
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Không lưu được hồ sơ người dùng: %s", e)

    def remember(self, name=None, address_form=None, location=None, note=None):
        """Ghi nhớ thông tin cá nhân lâu dài + lưu file. Trả câu xác nhận tiếng Việt."""
        self.data, changes = apply_update(self.data, name=name, address_form=address_form,
                                          location=location, note=note)
        if not changes:
            return ("Bạn muốn tôi nhớ điều gì? Hãy cho biết tên, cách xưng hô, "
                    "địa điểm hoặc điều cần ghi nhớ.")
        self._save()
        return "Đã nhớ: " + ", ".join(changes) + "."

    def add_auto_fact(self, fact):
        """Thêm một sự thật TỰ TRÍCH (từ củng cố STM->LTM). Bỏ trùng, giới hạn số lượng."""
        if not fact or not fact.strip():
            return
        self.data.setdefault("auto_facts", [])
        fact = fact.strip()
        if fact in self.data["auto_facts"] or fact in (self.data.get("notes") or []):
            return                                   # đã biết (tường minh hoặc tự trích)
        self.data["auto_facts"].append(fact)
        self.data["auto_facts"] = self.data["auto_facts"][-_MAX_AUTO_FACTS:]
        self._save()

    def summary(self):
        return summarize(self.data)

    def get_default_location(self):
        return (self.data.get("preferences") or {}).get("default_location")
