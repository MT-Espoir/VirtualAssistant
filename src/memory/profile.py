"""Bộ nhớ NGƯỜI DÙNG bền vững — các sự thật cá nhân giúp trợ lý "nhớ bạn".

Khác bộ nhớ HỘI THOẠI (agent.history — vài lượt nói gần đây): đây là sự thật LÂU DÀI
(tên, cách xưng hô, địa điểm mặc định, vài ghi chú) sống qua mọi phiên. Trợ lý học khi
người dùng nói ra (tool remember_about_user) và được bơm tóm tắt vào system prompt để
cá nhân hoá + xưng hô đúng.

Phần LOGIC thuần (cập nhật/tóm tắt dict) tách khỏi I/O để test được và suy biến an toàn
khi thiếu/hỏng file. (Thay hẳn thiết kế cũ command-history/daily-stats — vốn dựa trên
intent/entities không còn tồn tại trong kiến trúc tool-calling hiện tại.)
"""

import hashlib
import json
import os
import re

from datetime import datetime

from utils.atomic_json import write_json
from utils.logger import get_logger
from utils.text_norm import norm
from memory.timefmt import describe_age, is_past, older_than_days, parse_iso

logger = get_logger(__name__)

# SỰ KIỆN (có thời điểm) tách riêng khỏi sự thật BỀN VỮNG: tên/sở thích không bao giờ hết
# hạn, còn "phỏng vấn lúc 12h" thì có. Gộp chung khiến trợ lý nhắc việc đã xong như sắp
# tới. Giữ lại vài ngày sau khi qua để còn hỏi thăm ("hôm qua phỏng vấn sao rồi?").
_EVENT_KEEP_DAYS = 7
_MAX_EVENTS = 20

# Truy hồi liên quan: khi tổng số ghi chú vượt ngưỡng, CHỈ bơm top-K fact liên quan câu
# hỏi hiện tại (thay vì bơm hết) — né "lost in the middle" + tiết kiệm token. Dưới ngưỡng
# thì bơm hết như cũ.
_RETRIEVAL_THRESHOLD = 6
_RETRIEVAL_K = 5

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "data", "profile.json")

# Tham chiếu tượng trưng cho TÊN người dùng. Model chỉ thấy chuỗi này; tên thật được thay
# ở tầng runtime ngay trước khi nói ra. Xem `summarize` và `thay_tham_chieu`.
THAM_CHIEU_TEN = "@ten"


# auto_facts: sự thật TỰ TRÍCH từ hội thoại (độ tin thấp hơn notes tường minh) -> giữ
# riêng để phân biệt nguồn và giới hạn số lượng.
_MAX_AUTO_FACTS = 20


def _empty():
    return {"name": None, "address_form": None,
            "preferences": {"default_location": None}, "notes": [], "auto_facts": [],
            "events": []}


def make_event(text, when=None, now=None):
    """Dựng một sự kiện. `when` = thời điểm diễn ra (ISO); rỗng = không rõ giờ. Hàm THUẦN."""
    created = (now or datetime.now()).isoformat(timespec="seconds")
    parsed = parse_iso(when)
    return {"text": (text or "").strip(),
            "when": parsed.isoformat(timespec="seconds") if parsed else None,
            "created_at": created}


def prune_events(events, now=None, keep_days=_EVENT_KEEP_DAYS):
    """Bỏ sự kiện quá cũ (tính từ lúc diễn ra, hoặc lúc ghi nếu không rõ giờ). Hàm THUẦN."""
    kept = []
    for e in events or []:
        stamp = e.get("when") or e.get("created_at")
        if not older_than_days(stamp, keep_days, now=now):
            kept.append(e)
    return kept[-_MAX_EVENTS:]


def apply_update(data, name=None, address_form=None, location=None, note=None, when=None,
                 now=None):
    """Cập nhật (thuần) hồ sơ từ các trường KHÔNG rỗng. Trả (data_mới, [mô tả thay đổi]).

    Không sửa `data` gốc (copy sâu). Ghi chú trùng thì không thêm lại.
    `when` kèm `note` -> ghi thành SỰ KIỆN (có thời điểm) thay vì ghi chú bền vững, để sau
    khi qua giờ trợ lý biết là việc cũ. `now` cho phép chốt mốc "bây giờ" (test).
    """
    data = json.loads(json.dumps(data)) if data else _empty()
    data.setdefault("preferences", {})
    data.setdefault("notes", [])
    data.setdefault("auto_facts", [])
    data.setdefault("events", [])
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
        if when:                    # có thời điểm -> là SỰ KIỆN, không phải sự thật bền vững
            # Dọn kho CŨ trước rồi mới thêm, để sự kiện vừa ghi không bị chính lượt ghi đó
            # xoá (khi người dùng kể lại việc đã qua lâu): không thể hứa "đã ghi" mà kho rỗng.
            kept = prune_events(data["events"], now=now)[-(_MAX_EVENTS - 1):]
            data["events"] = kept + [make_event(n, when, now=now)]
            changes.append(f'sự kiện "{n}"')
        else:
            if n not in data["notes"]:
                data["notes"].append(n)
            changes.append(f'ghi chú "{n}"')
    return data, changes


def _relevant_facts(facts, query, k):
    """Chọn tối đa k fact liên quan 'query' nhất (đếm token trùng, bỏ dấu). Bỏ fact không
    trùng token nào (0 điểm) -> khi câu hỏi không liên quan gì thì không bơm nhiễu."""
    entries = [{"source": "fact", "text": fact} for fact in facts]
    return [item["text"] for item in rank_memory_entries(entries, query, k)]


def _memory_ref(source, text):
    """Mã ổn định để trace/eval tham chiếu một fact mà không chép nội dung nhạy cảm."""
    raw = f"{source}\0{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def rank_memory_entries(entries, query, k=_RETRIEVAL_K):
    """Xếp hạng các entry ``{source, text, id?}`` bằng đúng logic production hiện tại.

    Hàm công khai có chủ ý: benchmark Phase 4 gọi chính implementation này, tránh một
    bản sao evaluator âm thầm lệch khỏi code thực tế. Entry trả về là bản sao có thêm
    ``id`` và ``score``; thứ tự mới hơn vẫn thắng khi điểm bằng nhau.
    """
    qt = set(norm(query or "").split())
    scored = []
    for i, original in enumerate(entries or []):
        entry = dict(original)
        text = str(entry.get("text") or "")
        source = str(entry.get("source") or "fact")
        overlap = len(qt & set(norm(text).split()))
        if overlap > 0:
            entry["text"] = text
            entry["source"] = source
            entry["id"] = str(entry.get("id") or _memory_ref(source, text))
            entry["score"] = overlap
            scored.append((overlap, i, entry))     # (điểm, thứ tự=độ mới, fact)
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [entry for _, _, entry in scored[:max(0, int(k))]]


def retrieve_profile_facts(data, query=None, k=_RETRIEVAL_K,
                           threshold=_RETRIEVAL_THRESHOLD):
    """Chọn fact cho prompt và trả trace đã ẩn danh.

    Trace tuyệt đối không chứa query hay text của fact. Nó chỉ đủ để đo fact nào được
    chọn, từ nguồn nào và vì sao; nội dung thật vẫn chỉ sống trong kho memory hiện hữu.
    """
    data = data or {}
    entries = []
    for source in ("notes", "auto_facts"):
        for text in data.get(source) or []:
            text = str(text)
            entries.append({"source": source, "text": text,
                            "id": _memory_ref(source, text)})

    if not entries:
        selected = []
        mode = "none"
    elif query and len(entries) > threshold:
        selected = rank_memory_entries(entries, query, k)
        mode = "top_k"
    else:
        query_tokens = set(norm(query or "").split())
        selected = []
        for entry in entries:
            item = dict(entry)
            item["score"] = len(query_tokens & set(norm(item["text"]).split()))
            selected.append(item)
        mode = "all"

    trace = {
        "version": 1,
        "mode": mode,
        "total_facts": len(entries),
        "selected_count": len(selected),
        "query_token_count": len(set(norm(query or "").split())),
        "events_injected": len(data.get("events") or []),
        "selected": [
            {"id": item["id"], "source": item["source"],
             "score": int(item.get("score") or 0), "rank": rank}
            for rank, item in enumerate(selected, start=1)
        ],
    }
    return selected, trace


def describe_events(events, now=None):
    """Sự kiện -> (danh sách câu 'sắp tới', danh sách câu 'đã qua'). Hàm THUẦN.

    Sự kiện đã qua ĐƯỢC GIỮ nhưng gắn nhãn rõ ràng, để trợ lý vừa không nhắc như sắp diễn
    ra, vừa còn hỏi thăm được ("hôm qua phỏng vấn sao rồi?").
    """
    upcoming, past = [], []
    for e in events or []:
        text = (e.get("text") or "").strip()
        if not text:
            continue
        when = e.get("when")
        if is_past(when, now=now):
            age = describe_age(when or e.get("created_at"), now=now)
            past.append(f"{text} ({age})" if age else text)
        else:
            dt = parse_iso(when)
            upcoming.append(f"{text} (lúc {dt.strftime('%H:%M %d/%m')})" if dt else text)
    return upcoming, past


def find_memories(data, keyword):
    """Mọi mẩu trí nhớ khớp `keyword` (chuỗi con, bỏ dấu). Hàm THUẦN.

    Trả list (nguồn, chỉ số, nội dung) với nguồn ∈ notes | auto_facts | events — đủ để nơi
    gọi xoá đúng chỗ mà không cần biết cấu trúc bên trong.
    """
    key = norm(keyword or "").strip()
    if not key:
        return []
    hits = []
    for source in ("notes", "auto_facts"):
        for i, text in enumerate(data.get(source) or []):
            if key in norm(str(text)):
                hits.append((source, i, str(text)))
    for i, event in enumerate(data.get("events") or []):
        text = (event or {}).get("text") or ""
        if key in norm(text):
            hits.append(("events", i, text))
    return hits


def thay_tham_chieu(text, data):
    """Thay `@ten` bằng tên thật trong câu sắp nói ra. Hàm THUẦN.

    Chưa lưu tên -> bỏ tham chiếu đi thay vì để model đọc "@ten" cho người dùng nghe.
    """
    if not text or THAM_CHIEU_TEN not in text:
        return text
    ten = ((data or {}).get("name") or "").strip()
    if ten:
        return text.replace(THAM_CHIEU_TEN, ten)
    # Không có tên: xoá tham chiếu + khoảng trắng thừa do nó để lại.
    return re.sub(r"\s{2,}", " ", text.replace(THAM_CHIEU_TEN, "")).strip()


def summarize_with_trace(data, query=None, now=None):
    """Câu ngắn mô tả người dùng để bơm vào system prompt. '' nếu chưa biết gì.

    Nếu có `query` và số ghi chú vượt ngưỡng -> chỉ đưa top-K fact LIÊN QUAN; ngược lại
    đưa hết (giữ hành vi cũ khi ít fact / không có query).
    """
    if not data:
        return "", {"version": 1, "mode": "none", "total_facts": 0,
                    "selected_count": 0, "query_token_count": 0,
                    "events_injected": 0, "selected": []}
    parts = []
    # TÊN đi vào prompt dưới dạng THAM CHIẾU, không phải giá trị: model viết `@ten`, tầng
    # runtime thay bằng tên thật ngay trước khi nói (`thay_tham_chieu`). Model không thấy
    # tên thì model bị chiếm cũng không đọc ra được — mạnh hơn mọi cổng, vì cổng lách được
    # còn dữ liệu vắng mặt thì không. Cùng khuôn với toạ độ ở `services/location.py`.
    #
    # GIỚI HẠN, nói rõ để đừng ảo tưởng: nếu người dùng vừa tự nói tên ra trong hội thoại
    # thì tên đó nằm sẵn trong lịch sử ngắn hạn. Chỗ này chỉ chặn việc bơm tên vào MỌI
    # lượt một cách hệ thống, không xoá được tên khỏi ngữ cảnh nói chung.
    if data.get("name"):
        parts.append(f"Người dùng có tên đã lưu. Khi cần gọi tên, viết đúng "
                     f"'{THAM_CHIEU_TEN}' — hệ thống tự thay bằng tên thật.")
    if data.get("address_form"):
        parts.append(f"Xưng hô với người dùng là '{data['address_form']}'.")
    # ĐỊA ĐIỂM MẶC ĐỊNH cố ý KHÔNG vào prompt: đây là dữ liệu vị trí, mà model không cần
    # nó — `get_weather` để trống `location` thì tầng tool tự lấy từ hồ sơ. Mô tả tool đã
    # dặn sẵn "không nói địa điểm thì để trống".

    selected, trace = retrieve_profile_facts(data, query=query)
    if trace["mode"] == "top_k":
        if selected:
            parts.append("Liên quan lúc này: " +
                         "; ".join(item["text"] for item in selected) + ".")
    else:
        notes = [item["text"] for item in selected if item["source"] == "notes"]
        auto = [item["text"] for item in selected if item["source"] == "auto_facts"]
        if notes:
            parts.append("Cần nhớ: " + "; ".join(notes) + ".")
        if auto:
            parts.append("Quan sát từ hội thoại: " + "; ".join(auto) + ".")

    # Sự kiện luôn bơm (không qua truy hồi theo từ khoá): biết việc nào đã xong là thứ trợ
    # lý cần ở MỌI lượt, không chỉ khi câu hỏi tình cờ trùng từ.
    upcoming, past = describe_events(data.get("events"), now=now)
    if upcoming:
        parts.append("Sắp tới/đang diễn ra: " + "; ".join(upcoming) + ".")
    if past:
        parts.append("ĐÃ QUA (việc cũ — hỏi thăm thì được, TUYỆT ĐỐI đừng nhắc như sắp "
                     "diễn ra): " + "; ".join(past) + ".")

    if not parts:
        return "", trace
    text = "Thông tin người dùng (dùng để cá nhân hoá và xưng hô đúng): " + " ".join(parts)
    return text, trace


def summarize(data, query=None, now=None):
    """Câu ngắn mô tả người dùng; API tương thích cho các nơi gọi cũ."""
    return summarize_with_trace(data, query=query, now=now)[0]


class UserProfile:
    """Hồ sơ người dùng trên SQLite, với JSON làm chế độ tương thích/dự phòng.

    `database=None` giữ nguyên hành vi file cũ cho test và các cấu hình tối giản. Khi có
    database, file hiện hữu chỉ được import một lần rồi SQLite trở thành nguồn chính.
    """

    def __init__(self, path=None, database=None, import_legacy=True):
        self.path = path or _DEFAULT_PATH
        self.database = database
        self._last_retrieval_trace = None
        if self.database is not None:
            try:
                if import_legacy:
                    self.database.import_profile_file(self.path)
                self.database.prune_expired_memory()
                self.data = self.database.load_user_profile()
                return
            except Exception as e:
                logger.warning("Không mở được hồ sơ SQLite; tạm dùng file cũ: %s", e)
                self.database = None
        self.data = self._load_file()

    def _load_file(self):
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
        if self.database is not None:
            return
        try:
            write_json(self.path, self.data)
        except OSError as e:
            logger.error("Không lưu được hồ sơ người dùng: %s", e)

    def _database_failed(self, action, error):
        logger.error("SQLite lỗi khi %s; chuyển sang file hồ sơ: %s", action, error)
        self.database = None
        self._save()

    def remember(self, name=None, address_form=None, location=None, note=None, when=None):
        """Ghi nhớ thông tin cá nhân lâu dài + lưu file. Trả câu xác nhận tiếng Việt."""
        self.data, changes = apply_update(self.data, name=name, address_form=address_form,
                                          location=location, note=note, when=when)
        if not changes:
            return ("Bạn muốn tôi nhớ điều gì? Hãy cho biết tên, cách xưng hô, "
                    "địa điểm hoặc điều cần ghi nhớ.")
        if self.database is not None:
            try:
                if name and name.strip():
                    self.database.set_profile_name(name.strip())
                if address_form and address_form.strip():
                    self.database.set_user_preference(
                        "address_form", address_form.strip(), source="explicit_user")
                if location and location.strip():
                    self.database.set_user_preference(
                        "default_location", location.strip(), source="explicit_user")
                if note and note.strip():
                    if when:
                        self.database.add_profile_event(self.data["events"][-1], inferred=False)
                    else:
                        self.database.add_profile_note(note.strip(), inferred=False)
            except Exception as e:
                self._database_failed("ghi nhớ thông tin người dùng", e)
        else:
            self._save()
        return "Đã nhớ: " + ", ".join(changes) + "."

    def add_auto_fact(self, fact, evidence=None, confidence=0.6, source_id=None):
        """Thêm một sự thật TỰ TRÍCH (từ củng cố STM->LTM). Bỏ trùng, giới hạn số lượng."""
        if not fact or not fact.strip():
            return
        self.data.setdefault("auto_facts", [])
        fact = fact.strip()
        if fact in self.data["auto_facts"] or fact in (self.data.get("notes") or []):
            return                                   # đã biết (tường minh hoặc tự trích)
        self.data["auto_facts"].append(fact)
        self.data["auto_facts"] = self.data["auto_facts"][-_MAX_AUTO_FACTS:]
        if self.database is not None:
            try:
                self.database.add_profile_note(
                    fact, inferred=True, evidence=evidence,
                    confidence=confidence, source_id=source_id)
                # Projection DB tự loại candidate thiếu evidence/confidence/expiry.
                self.data = self.database.load_user_profile()
            except Exception as e:
                self._database_failed("lưu sự thật suy luận", e)
        else:
            self._save()

    def forget(self, keyword):
        """Xoá một mẩu trí nhớ khớp `keyword`. Trả câu trả lời tiếng Việt.

        Khớp NHIỀU mẩu -> hỏi lại chứ KHÔNG đoán: xoá nhầm trí nhớ thì không khôi phục được.
        """
        hits = find_memories(self.data, keyword)
        if not hits:
            return f"Tôi không nhớ điều nào giống '{keyword}'."
        if len(hits) > 1:
            listing = ", ".join(f'"{text}"' for _, _, text in hits)
            return (f"Có {len(hits)} điều khớp: {listing}. "
                    f"Bạn muốn tôi quên điều nào?")
        source, index, text = hits[0]
        removed = self.data[source].pop(index)
        if self.database is not None:
            try:
                self.database.delete_profile_item(source, removed)
            except Exception as e:
                self._database_failed("xóa trí nhớ", e)
        else:
            self._save()
        return f'Đã quên: "{text}".'

    def add_event(self, text, when=None, evidence=None, confidence=0.8, source_id=None):
        """Ghi một SỰ KIỆN có thời điểm (tự trích từ hội thoại). Dọn luôn sự kiện quá cũ."""
        if not text or not text.strip():
            return
        self.data.setdefault("events", []).append(make_event(text, when))
        self.data["events"] = prune_events(self.data["events"])
        event = self.data["events"][-1]
        if self.database is not None:
            try:
                self.database.add_profile_event(
                    event, inferred=True, evidence=evidence,
                    confidence=confidence, source_id=source_id)
                self.database.prune_expired_memory()
                self.data = self.database.load_user_profile()
            except Exception as e:
                self._database_failed("lưu sự kiện suy luận", e)
        else:
            self._save()

    def resolve(self, text):
        """Thay tham chiếu tượng trưng bằng giá trị thật, ngay trước khi nói ra."""
        return thay_tham_chieu(text, self.data)

    def summary(self, query=None):
        # Dọn sự kiện quá hạn ngay lúc đọc -> hồ sơ không phình theo thời gian.
        events = self.data.get("events")
        if events:
            pruned = prune_events(events)
            if len(pruned) != len(events):
                self.data["events"] = pruned
                if self.database is not None:
                    try:
                        self.database.prune_expired_memory()
                    except Exception as e:
                        self._database_failed("dọn sự kiện hết hạn", e)
                else:
                    self._save()
        text, trace = summarize_with_trace(self.data, query=query)
        self._last_retrieval_trace = trace
        return text

    def last_retrieval_trace(self):
        """Trace của lần ``summary`` gần nhất, trả bản sao để caller không sửa state."""
        if self._last_retrieval_trace is None:
            return None
        return json.loads(json.dumps(self._last_retrieval_trace))

    def get_default_location(self):
        return (self.data.get("preferences") or {}).get("default_location")

    def get_address_form(self):
        """Cùng nguồn xưng hô mà Agent đưa vào system context."""
        return self.data.get("address_form")

    def export_data(self, destination=None):
        """Xuất hồ sơ có thể đọc được để người dùng kiểm tra/di chuyển dữ liệu."""
        if destination is None:
            if self.database is not None:
                base = self.database.path.parent
            else:
                base = os.path.dirname(os.path.abspath(self.path))
            filename = "user-memory-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json"
            destination = os.path.join(base, "exports", filename)
        if self.database is not None:
            return self.database.export_user_memory(destination)
        write_json(str(destination), self.data)
        return destination

    def clear(self):
        """Xóa toàn bộ trí nhớ cá nhân và cả file nguồn cũ để không tự import lại."""
        result = {"facts": 0, "preferences": 0, "habits": 0}
        if self.database is not None:
            result = self.database.delete_user_memory()
        if os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError as e:
                logger.error("Không xóa được file hồ sơ cũ: %s", e)
                raise
        self.data = _empty()
        return result
