"""Thói quen — điều học được từ HÀNH VI LẶP LẠI, khác hẳn hai tầng nhớ còn lại.

`profile.py` nhớ những gì người dùng NÓI RA ("tôi tên Minh", "nhớ giúp tôi..."), còn ở
đây trợ lý tự nhận ra bằng cách ĐẾM: mở Chrome bảy lần, nghe một bài bốn lần thì đó là
thói quen, dù người dùng chưa bao giờ nói "tôi thích bài này".

Vì sao không nhét vào bộ trích xuất LLM (`consolidation.py`): nó chỉ đọc ĐƯỢC một đoạn
hội thoại ngắn, nơi mỗi bài hát chỉ xuất hiện một lần — và chính prompt trích xuất dặn
"bỏ qua chuyện vặt nhất thời". Không có bộ đếm sống qua nhiều phiên thì "hay nghe" là
thứ không cách nào biết được.

Ngưỡng `_MIN_COUNT` là chỗ chặn nói bừa: làm một lần chưa phải thói quen. `_FADE_DAYS`
là chỗ để quên: lâu không làm nữa thì rơi ra, khỏi bám mãi một sở thích đã cũ.

Phần LOGIC thuần tách khỏi I/O như `profile.py` — cùng lý do (test được, hỏng file thì
suy biến an toàn).
"""

import json
import os

from datetime import datetime

from utils.atomic_json import write_json
from utils.logger import get_logger
from utils.text_norm import norm, strip_accents
from memory.timefmt import older_than_days

logger = get_logger(__name__)

_MIN_COUNT = 3        # dưới ngưỡng này mới là chuyện tình cờ, chưa gọi là thói quen
_TOP_K = 3            # chỉ bơm vài thói quen mạnh nhất vào prompt (né nhiễu + tốn token)
_FADE_DAYS = 60       # lâu ngần này không làm lại -> quên, đừng bám sở thích đã cũ
_MAX_ENTRIES = 40     # trần kho: giữ thứ làm nhiều/mới, bỏ thứ đếm lẻ tẻ
_MAX_NHAN = 60        # trần độ dài một nhãn — xem `HabitLog.record`

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "data", "habits.json")


def _empty():
    return {"items": {}}


def _items(data):
    return (data or {}).get("items") or {}


def _so_dau(s):
    return sum(1 for c in (s or "") if strip_accents(c) != c)


def _nhan_tot_hon(cu, moi):
    """Giữ bản CÓ DẤU giữa hai cách viết cùng một thứ. Hàm THUẦN.

    Cùng một bài hát vào kho qua nhiều lối: người dùng gõ có dấu, STT nghe ra không dấu.
    Nhãn này rồi sẽ được TTS ĐỌC LÊN, mà "chung ta cua hien tai" đọc ra nghe sai hẳn — nên
    lần ghi sau không được phép xoá mất bản có dấu đã có.
    """
    if not cu:
        return moi
    return moi if _so_dau(moi) > _so_dau(cu) else cu


def bump(data, key, label, now=None):
    """Đếm thêm một lần cho hành vi `key`. Trả data MỚI (hàm thuần, không sửa data gốc).

    `key` đã chuẩn hoá (bỏ dấu, thường hoá) nên "Chúng ta của hiện tại" và "chung ta cua
    hien tai" là MỘT — người dùng nói lại bằng giọng khác dấu vẫn cộng dồn đúng chỗ.
    `label` là câu hiển thị, luôn lấy bản mới nhất.
    """
    key = norm(key)
    if not key or not (label or "").strip():
        return data if data else _empty()
    # Dọn mục đã phai TRƯỚC khi cộng: bài không nghe suốt ba tháng mà bật lại một lần thì
    # phải đếm lại từ đầu, chứ không được sống dậy nguyên số cũ rồi khoe "hay nghe (6 lần)".
    data = prune(data, now=now)
    cu = data["items"].get(key) or {}
    data["items"][key] = {"label": _nhan_tot_hon(cu.get("label"), label.strip()),
                          "count": int(cu.get("count") or 0) + 1,
                          "last": (now or datetime.now()).isoformat(timespec="seconds")}
    return prune(data, now=now)


def prune(data, now=None, fade_days=_FADE_DAYS, max_entries=_MAX_ENTRIES):
    """Bỏ hành vi quá cũ, và cắt kho về `max_entries` mục mạnh nhất. Hàm THUẦN."""
    con = {k: v for k, v in _items(data).items()
           if not older_than_days((v or {}).get("last"), fade_days, now=now)}
    if len(con) > max_entries:
        xep = sorted(con.items(), key=lambda kv: (kv[1].get("count") or 0,
                                                  kv[1].get("last") or ""), reverse=True)
        con = dict(xep[:max_entries])
    return {"items": con}


def top(data, k=_TOP_K, min_count=_MIN_COUNT, now=None):
    """`k` thói quen mạnh nhất dạng [(label, count)]. Hàm THUẦN.

    Chỉ lấy mục đã đạt ngưỡng và chưa phai — thà không nói gì còn hơn khẳng định người
    dùng "hay" làm một việc họ mới làm đúng một lần.
    """
    dat = [(v.get("label") or "", int(v.get("count") or 0), v.get("last") or "")
           for v in _items(prune(data, now=now)).values()
           if int((v or {}).get("count") or 0) >= min_count and (v or {}).get("label")]
    dat.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [(label, count) for label, count, _ in dat[:k]]


def describe(data, k=_TOP_K, min_count=_MIN_COUNT, now=None):
    """Câu bơm vào system prompt. '' nếu chưa đủ dữ liệu để nói gì chắc chắn.

    Nói rõ đây là SUY ĐOÁN từ số lần làm: người dùng chưa từng phát biểu điều này, nên
    trợ lý được phép gợi ý nhưng không được khẳng định như lời họ nói ra.
    """
    manh = top(data, k=k, min_count=min_count, now=now)
    if not manh:
        return ""
    ve = "; ".join(f"hay {label} ({count} lần)" for label, count in manh)
    return ("Thói quen quan sát được từ hành vi (SUY ĐOÁN theo số lần làm, người dùng "
            f"chưa tự nói ra — gợi ý thì được, đừng khẳng định chắc nịch): {ve}.")


class HabitLog:
    """Bộ đếm thói quen lưu JSON. `path=None` -> file mặc định trong memory/data/."""

    def __init__(self, path=None):
        self.path = path or _DEFAULT_PATH
        self.data = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return _empty()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) and isinstance(data.get("items"), dict) \
                else _empty()
        except (OSError, ValueError) as e:
            logger.warning("Không đọc được kho thói quen: %s — dùng kho trống.", e)
            return _empty()

    def _save(self):
        try:
            write_json(self.path, self.data)
        except OSError as e:
            logger.error("Không lưu được kho thói quen: %s", e)

    def record(self, value, label_template):
        """Ghi nhận một lần làm việc gì đó. `label_template` vd "nghe '{}'".

        Giá trị bị CẮT theo `_MAX_NHAN`: nhãn này rồi sẽ được bơm vào prompt mọi lượt và
        được TTS đọc lên. Tên một bài hát hay một app không bao giờ dài tới mức đó; một
        đoạn chỉ dẫn bị tiêm thì có. Cắt là vừa chặn được đoạn văn lạc vào kho, vừa giữ
        cho khối thói quen không phình ra trong prompt.
        """
        value = (str(value) if value is not None else "").strip()[:_MAX_NHAN]
        if not value:
            return
        self.data = bump(self.data, value, label_template.format(value))
        self._save()

    def summary(self):
        return describe(self.data)
