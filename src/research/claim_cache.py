"""
Nhớ lại TỪNG NGUỒN ĐÃ NÓI GÌ, để không phải đọc lại web mỗi lượt.

Đơn vị được nhớ là **lời của một nguồn**, không phải câu trả lời hoàn chỉnh:

    khoá truy vấn -> { domain: {url, records: [{name, address, photos, quote}]} }

Cắt ở đúng chỗ đó là có chủ đích. Nhớ câu trả lời hoàn chỉnh thì cache chỉ là một bảng
tra cứu; nhớ lời từng nguồn thì mọi bước hạ nguồn — gộp biến thể tên, khử trùng nguồn,
đếm đồng thuận — vẫn chạy nguyên vẹn trên tập nguồn HỢP NHẤT của nhiều lượt.

BA CHẾ ĐỘ:

  hit       Trong cửa sổ TƯƠI -> trả thẳng, không đụng mạng.

  merge     Quá cửa sổ tươi nhưng chưa hết hạn -> vẫn đi tìm, rồi HỢP NHẤT nguồn cũ với
            nguồn mới. Đây là chế độ đáng giá nhất và nó sinh ra từ một KHUYẾT TẬT: tập
            kết quả tìm kiếm KHÔNG ổn định giữa hai lần gọi. Hợp nhất biến sự bất ổn đó
            từ khuyết tật thành lợi thế: mỗi lượt góp thêm nguồn độc lập, nên ứng viên
            từng chỉ có một nguồn có thể đạt ngưỡng ở lượt sau. Không có gì bị thổi phồng
            — hai trang khác nhau đúng là hai trang khác nhau, dù đọc cách nhau một tuần.

  fallback  Tìm kiếm HỎNG mà còn bản nhớ (kể cả cũ) -> dùng bản nhớ và NÓI RÕ nó cũ bao
            lâu. Máy tìm kiếm bị chặn không phải ca hiếm, và im lặng ở đây là bịa: người
            dùng sẽ tưởng trợ lý vừa đọc web xong.

TTL THEO LỚP BIẾN ĐỘNG: thẩm mỹ của một quán đổi theo năm, nên hạn dài. Những thứ đổi
nhanh — giờ mở cửa, điểm số, khoảng cách — KHÔNG nằm trong này; chúng đến từ bản đồ lúc
người dùng bấm vào thẻ, và bấm lúc nào thì tra lúc đó.

Module này TRUNG LẬP VỀ MIỀN: khoá là một chuỗi mờ, bản ghi là dữ liệu mờ. Nó không biết
"quán cà phê" là gì.
"""

import io
import json
import os
import time

from utils.atomic_json import write_json
from utils.logger import get_logger

logger = get_logger(__name__)

# Đổi số này khi ĐỔI CÁCH bóc bản ghi (thêm trường, sửa luật chọn trích dẫn...). Bản nhớ
# cũ khi đó không sai về nội dung nhưng đã lệch về hình dạng -> bỏ hết còn hơn trộn lẫn.
CACHE_VERSION = 1

# Cửa sổ TƯƠI: trong bao lâu thì trả thẳng bản nhớ mà không đụng mạng.
DEFAULT_FRESH_HOURS = 24

# Hạn dùng: quá mốc này thì bản nhớ bị bỏ. Lấy theo lớp biến động chậm nhất.
DEFAULT_TTL_DAYS = 90

# Trần số mục: cả file phải đọc xong trong một nhịp lúc khởi tạo, nên giữ ở mức vài chục
# mục — đủ cho thói quen hỏi của một người.
MAX_ENTRIES = 50

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "data", "claims.json")


class ClaimCache:
    """Kho lời-của-nguồn theo khoá truy vấn. `path` rỗng = chỉ sống trong phiên.

    Hỏng ở tầng này KHÔNG được làm hỏng lượt tìm: mọi lỗi đọc/ghi đều nuốt kèm log, và
    người dùng cùng lắm mất phần tăng tốc.
    """

    def __init__(self, path=None, fresh_hours=DEFAULT_FRESH_HOURS,
                 ttl_days=DEFAULT_TTL_DAYS, now=None):
        self.path = path or None
        self.fresh_seconds = max(0.0, float(fresh_hours)) * 3600.0
        self.ttl_seconds = max(0.0, float(ttl_days)) * 86400.0
        self._now = now or time.time
        self._entries = self._load()

    # ---------- I/O ----------

    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with io.open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("claim_cache: đọc '%s' lỗi (%s) — bắt đầu rỗng.", self.path, e)
            return {}
        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
            return {}
        entries = data.get("entries")
        if not isinstance(entries, dict):
            return {}
        # Dọn hàng hết hạn ngay lúc đọc, không đợi tới lúc tra.
        now = self._now()
        return {k: v for k, v in entries.items()
                if isinstance(v, dict) and not self._expired(v, now)}

    def _save(self):
        if not self.path:
            return
        try:
            write_json(self.path, {"version": CACHE_VERSION, "entries": self._entries},
                       indent=None)          # cache: gọn hơn, không ai đọc bằng mắt
        except Exception as e:
            logger.warning("claim_cache: ghi '%s' lỗi: %s", self.path, e)

    # ---------- tra / ghi ----------

    def _expired(self, entry, now):
        return (now - float(entry.get("saved_at") or 0)) > self.ttl_seconds

    def get(self, key):
        """-> {sources, age_hours, fresh} hoặc None nếu không có / đã hết hạn."""
        entry = self._entries.get(key)
        if not entry:
            return None
        now = self._now()
        if self._expired(entry, now):
            self._entries.pop(key, None)
            return None
        age = max(0.0, now - float(entry.get("saved_at") or 0))
        sources = entry.get("sources")
        if not isinstance(sources, dict) or not sources:
            return None
        return {"sources": sources, "age_hours": age / 3600.0,
                "fresh": age <= self.fresh_seconds}

    def put(self, key, sources):
        """Ghi đè lời-của-nguồn cho một khoá. `sources` rỗng -> không ghi gì."""
        if not key or not sources:
            return
        self._entries[key] = {"saved_at": self._now(), "sources": sources}
        if len(self._entries) > MAX_ENTRIES:
            # Bỏ mục CŨ NHẤT theo lúc ghi. Không dùng "ít tra tới nhất" vì để biết điều đó
            # phải ghi thêm mỗi lần đọc, mà lần đọc thì nên rẻ.
            oldest = sorted(self._entries.items(),
                            key=lambda kv: kv[1].get("saved_at") or 0)
            for k, _ in oldest[:len(self._entries) - MAX_ENTRIES]:
                self._entries.pop(k, None)
        self._save()


def merge_sources(old, new):
    """Hợp nhất hai tập lời-của-nguồn theo DOMAIN. Hàm thuần.

    Một domain có ở cả hai bên -> lấy bản MỚI: trang có thể đã sửa, và bản vừa đọc bao giờ
    cũng đúng hơn. Đây cũng là chỗ giữ luật MỘT DOMAIN MỘT PHIẾU qua nhiều lượt: hợp nhất
    theo domain chứ không theo URL, nếu không thì một site đổi đường dẫn bài sẽ tự nhân
    đôi phiếu của nó.
    """
    merged = dict(old or {})
    merged.update(new or {})
    return merged
