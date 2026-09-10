"""ContactStore — sổ danh bạ cục bộ (tên -> email), bền vững.

Nhái TaskStore (KHÔNG thread/lock — chỉ thao tác từ luồng agent). Cho phép lưu địa chỉ
email theo TÊN/biệt danh để lần sau chỉ cần gọi tên ('gửi mail cho sếp') mà không phải
đọc cả địa chỉ. Khớp theo tên bỏ dấu để tiện ra lệnh bằng giọng. Logic thuần (find) tách
khỏi I/O để test. Đây là NGUỒN PHỤ: trợ lý tra Google Contacts trước, không thấy mới dùng.
"""

import json
import os
import uuid
from datetime import datetime

from utils.atomic_json import write_json
from utils.logger import get_logger
from utils.text_norm import strip_accents

logger = get_logger(__name__)

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "contacts.json")


class ContactStore:
    def __init__(self, path=None):
        self.path = path or _DEFAULT_PATH
        self._contacts = {}       # id -> {"id","name","email","created_at"}
        self._load()

    # ------------------------- thao tác dữ liệu ------------------------- #
    def add(self, name, email):
        """Lưu liên hệ. Nếu đã có người CÙNG TÊN (bỏ dấu) thì cập nhật email. Trả contact,
        hoặc None nếu thiếu tên/email."""
        name = (name or "").strip()
        email = (email or "").strip()
        if not name or not email:
            return None
        key = strip_accents(name.lower())
        for c in self._contacts.values():
            if strip_accents(c["name"].lower()) == key:
                c["email"] = email
                self._save()
                return c
        c = {"id": uuid.uuid4().hex[:6], "name": name, "email": email,
             "created_at": datetime.now().isoformat()}
        self._contacts[c["id"]] = c
        self._save()
        return c

    def list(self):
        """Liên hệ theo thứ tự tạo."""
        return sorted(self._contacts.values(), key=lambda c: c["created_at"])

    def find(self, keyword):
        """Mọi liên hệ khớp keyword: theo id, hoặc chuỗi con (bỏ dấu) trong tên. Hàm THUẦN."""
        raw = (keyword or "").strip()
        key = strip_accents(raw.lower())
        if not key:
            return []
        return [c for c in self._contacts.values()
                if c["id"] == raw or key in strip_accents(c["name"].lower())]

    def remove(self, contact_id):
        """Xoá theo id chính xác. Trả contact đã xoá, hoặc None."""
        c = self._contacts.pop(contact_id, None)
        if c is not None:
            self._save()
        return c

    # ------------------------- lưu / nạp ------------------------- #
    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._contacts = {c["id"]: c for c in data}
        except (OSError, ValueError, KeyError) as e:
            logger.warning("Không đọc được sổ danh bạ: %s", e)

    def _save(self):
        try:
            write_json(self.path, list(self._contacts.values()))
        except OSError as e:
            logger.error("Không lưu được sổ danh bạ: %s", e)
