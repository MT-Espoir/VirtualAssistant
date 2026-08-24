"""
Kho VỊ TRÍ của người dùng — tầng RUNTIME giữ toạ độ chính xác.

Ranh giới ba tầng:
  LLM      : chỉ thấy ngữ cảnh THÔ (cấp tỉnh/thành) và tham chiếu tượng trưng '@current'
  Runtime  : giữ toạ độ chính xác — chính là module này
  Tool/nguồn: nhận toạ độ chính xác từ runtime ngay lúc gọi

Tách khỏi `UserProfile` là CÓ CHỦ ĐÍCH: hồ sơ được bơm vào system prompt mỗi lượt, tức
mọi thứ nằm trong đó đều đi lên nhà cung cấp LLM. Toạ độ nhà của người dùng không thuộc
loại đó. Ghi ra đĩa vẫn được (để không phải khai lại mỗi phiên), chỉ là không đi vào prompt.
"""

import io
import json
import os

from utils.logger import get_logger

logger = get_logger(__name__)

GRANULARITIES = ("province", "district", "none")


class LocationStore:
    """Vị trí hiện tại của người dùng. `path` rỗng = chỉ sống trong phiên."""

    def __init__(self, path=None, geocoder=None):
        self.path = path or None
        self._geocoder = geocoder
        self._data = self._load()

    # ---------- I/O ----------
    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with io.open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("location: đọc '%s' lỗi (%s) — bắt đầu rỗng.", self.path, e)
            return {}

    def _save(self):
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with io.open(self.path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("location: ghi '%s' lỗi: %s", self.path, e)

    # ---------- đọc ----------
    def has(self):
        return self._data.get("lat") is not None and self._data.get("lng") is not None

    def coords(self):
        """(lat, lng) hoặc None. CHỈ dùng ở tầng tool — không bao giờ đưa vào prompt."""
        if not self.has():
            return None
        return (float(self._data["lat"]), float(self._data["lng"]))

    def display(self):
        return self._data.get("display") or ""

    def coarse(self, granularity="province"):
        """Ngữ cảnh THÔ được phép bơm vào prompt. 'none' -> không bơm gì."""
        g = (granularity or "province").strip().lower()
        if g not in GRANULARITIES or g == "none" or not self.has():
            return ""
        if g == "district":
            return self._data.get("district") or self._data.get("province") or ""
        return self._data.get("province") or ""

    # ---------- ghi ----------
    def set_coords(self, lat, lng, display, province="", district=""):
        """Lưu toạ độ ĐÃ giải sẵn (bởi tầng tra địa điểm). Trả tên hiển thị.

        Tách khỏi `set_place` vì việc giải địa danh phải dùng CHUNG một đường với
        `find_nearby` — nếu không, cùng một câu "tôi đang ở X" sẽ lưu được ở chỗ này mà
        tra được ở chỗ kia.

        `province` chỉ được điền khi nguồn là danh bạ hành chính. Giải qua bản đồ thì để
        TRỐNG — tên một khu đô thị cụ thể không phải "ngữ cảnh thô", không được phép rơi
        vào prompt.
        """
        if lat is None or lng is None:
            return None
        self._data = {"lat": float(lat), "lng": float(lng),
                      "display": display or "", "province": province or "",
                      "district": district or ""}
        self._save()
        return self._data["display"]

    def set_place(self, name):
        """Tên địa danh người dùng nói -> geocode -> lưu toạ độ. Trả tên hiển thị|None."""
        if not name or not str(name).strip():
            return None
        geocode = self._geocoder
        if geocode is None:
            from actions.weather import geocode as _g
            geocode = _g
        hit = geocode(str(name).strip())
        if not hit or hit.get("latitude") is None:
            return None
        self._data = {
            "lat": hit.get("latitude"), "lng": hit.get("longitude"),
            "display": hit.get("name") or str(name).strip(),
            "province": hit.get("admin1") or "",
            "district": hit.get("admin2") or "",
        }
        self._save()
        return self._data["display"]

    def clear(self):
        self._data = {}
        self._save()
