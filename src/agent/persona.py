"""Persona — nhân cách + tâm trạng của trợ lý.

Hai khối, khớp bộ nhớ hai tầng:
- PersonaState (DÀI HẠN, persona.json): "character card" ổn định — danh tính, văn phong,
  núm tính cách (baseline ẤM ÁP/THÂN THIỆN), vài ví dụ few-shot. `render()` THÍCH NGHI
  PROVIDER: card đầy đủ + few-shot khi model mạnh (gemini/claude), tự rút gọn khi local.
- MoodState (NGẮN HẠN, phiên): tâm trạng tính bằng CÔNG THỨC tất định (không LLM), đổi theo
  cảm xúc user + kết quả việc + mức thân thiết, PHAI dần về baseline do persona quy định.

Cố ý KHÔNG tự học tính cách tự do (chỉ núm có biên). Thay hẳn
personality_learner.py cũ (thiết kế chết). Logic thuần, tách I/O để test được.
"""

import json
import os
import re

from utils.logger import get_logger
from utils.text_norm import norm

logger = get_logger(__name__)

_TRAIT_NAMES = ("warmth", "humor", "formality", "energy", "curiosity")
_NUDGE_STEP = 0.05             # mỗi lần củng cố chỉ nhích RẤT nhỏ (chống trôi dạt)

# Prompt "huấn luyện viên tính cách" (Phase 2, học ẩn qua LLM). Trả về mỗi núm một dòng
# 'tên: +/-/0' để bên ngoài parse thành nudge có biên.
PERSONA_TUNE_SYSTEM = (
    "Bạn là huấn luyện viên tính cách cho một trợ lý ảo. Dựa trên đoạn hội thoại, đề xuất "
    "ĐIỀU CHỈNH NHỎ cho từng núm tính cách để hợp người dùng hơn. Với MỖI núm trong: warmth, "
    "humor, formality, energy, curiosity — trả về ĐÚNG một dòng dạng 'tên: +' (nên tăng), "
    "'tên: -' (nên giảm), hoặc 'tên: 0' (giữ nguyên). CHỈ đề xuất tăng/giảm khi có tín hiệu "
    "RÕ trong hội thoại; còn lại để 0. KHÔNG giải thích, KHÔNG thêm gì khác."
)


def parse_trait_nudges(text, step=_NUDGE_STEP):
    """Tách gợi ý của LLM -> {trait: delta} có biên. Chỉ nhận núm hợp lệ + dấu +/-/0."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"\s*(warmth|humor|formality|energy|curiosity)\s*[:=]\s*([+\-0])",
                     line, re.IGNORECASE)
        if not m:
            continue
        name, sign = m.group(1).lower(), m.group(2)
        if sign == "+":
            out[name] = step
        elif sign == "-":
            out[name] = -step
        # '0' -> giữ nguyên, bỏ qua
    return out

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                             "memory", "data", "persona.json")

_STRONG_PROVIDERS = ("gemini", "claude")


def _clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def _default_persona():
    """Baseline ẤM ÁP / THÂN THIỆN (đã chốt)."""
    return {
        "identity": "một trợ lý ảo ấm áp, thân thiện và hay động viên người dùng",
        "style": ("nói gần gũi, tự nhiên như một người bạn; câu ngắn gọn, dễ nghe; "
                  "thỉnh thoảng hài nhẹ nhàng; luôn tích cực nhưng không giả tạo"),
        "traits": {"warmth": 0.85, "humor": 0.5, "formality": 0.25,
                   "energy": 0.6, "curiosity": 0.55},
        "examples": [
            {"user": "hôm nay tôi mệt quá", "assistant": "Nghe mệt thật đó. Nghỉ chút đi, cần gì cứ gọi mình nhé."},
            {"user": "mở giúp tôi youtube", "assistant": "Có ngay đây! Đang mở YouTube cho bạn."},
        ],
        "rapport": {"familiarity": 0.3, "interaction_count": 0},
    }


def _familiarity_label(f):
    if f >= 0.75:
        return "thân thiết"
    if f >= 0.5:
        return "khá thân"
    if f >= 0.25:
        return "đang quen dần"
    return "mới quen"


class PersonaState:
    """Character card + núm tính cách, lưu persona.json. `provider` quyết render đầy đủ hay gọn."""

    def __init__(self, path=None, provider="ollama", persist=True):
        self.path = path or _DEFAULT_PATH
        self.provider = (provider or "ollama").lower()
        self.persist = persist            # False -> KHÔNG đụng đĩa (không đọc/ghi) — test/eval
        self.data = self._load() if persist else _default_persona()

    def _load(self):
        if not os.path.exists(self.path):
            return _default_persona()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else _default_persona()
        except (OSError, ValueError) as e:
            logger.warning("Không đọc được persona: %s — dùng mặc định.", e)
            return _default_persona()

    def _save(self):
        if not self.persist:
            return
        try:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Không lưu được persona: %s", e)

    # --- HỌC TƯỜNG MINH: chỉnh núm tính cách (có biên) ---
    def adjust(self, trait, delta):
        """Nhích một núm tính cách theo delta, kẹp trong [0,1]. Trả giá trị mới."""
        traits = self.data.setdefault("traits", {})
        new = _clamp(traits.get(trait, 0.5) + delta, 0.0, 1.0)
        traits[trait] = new
        self._save()
        logger.info("🎚️ persona: %s -> %.2f (Δ%+.2f)", trait, new, delta)
        return new

    def reset_traits(self):
        """Đưa tính cách (núm + danh tính + văn phong) về baseline; GIỮ quan hệ (rapport)."""
        d = _default_persona()
        self.data["traits"] = d["traits"]
        self.data["identity"] = d["identity"]
        self.data["style"] = d["style"]
        self._save()

    # --- QUAN HỆ: thân thiết tăng chậm theo số lần tương tác ---
    def record_interaction(self):
        """Tăng đếm tương tác + độ thân thiết (tiệm cận 1.0). Trả familiarity mới."""
        rap = self.data.setdefault("rapport", {})
        rap["interaction_count"] = rap.get("interaction_count", 0) + 1
        rap["familiarity"] = _clamp(0.3 + 0.007 * rap["interaction_count"], 0.0, 1.0)
        self._save()
        return rap["familiarity"]

    # --- đọc trạng thái cho MoodState ---
    def _trait(self, name, default=0.5):
        return (self.data.get("traits") or {}).get(name, default)

    def baseline_valence(self):
        """Persona càng ẤM (warmth cao) -> baseline tâm trạng càng tích cực. Khoảng [-0.1, 0.4]."""
        return _clamp(-0.1 + 0.6 * self._trait("warmth", 0.5), -0.1, 0.4)

    def baseline_arousal(self):
        """Persona càng NĂNG ĐỘNG (energy cao) -> baseline hưng phấn hơn. Khoảng [0.3, 0.75]."""
        return _clamp(0.3 + 0.45 * self._trait("energy", 0.5), 0.3, 0.75)

    def familiarity(self):
        return (self.data.get("rapport") or {}).get("familiarity", 0.3)

    # --- render vào system prompt ---
    def render(self):
        """Đoạn mô tả nhân cách bơm vào system prompt. Đầy đủ + few-shot khi model mạnh."""
        identity = self.data.get("identity", "")
        style = self.data.get("style", "")
        fam = _familiarity_label(self.familiarity())
        parts = [f"Bạn là {identity}." if identity else "",
                 f"Văn phong: {style}." if style else "",
                 f"Mức thân thiết với người dùng: {fam}."]
        card = " ".join(p for p in parts if p)

        if self.provider in _STRONG_PROVIDERS:
            examples = self.data.get("examples") or []
            if examples:
                lines = ["Ví dụ cách bạn trò chuyện (bắt chước GIỌNG này, đừng lặp lại nguyên văn):"]
                for ex in examples[:3]:
                    u, a = ex.get("user", ""), ex.get("assistant", "")
                    if u and a:
                        lines.append(f"- Người dùng: {u}\n  Bạn: {a}")
                if len(lines) > 1:
                    card += "\n" + "\n".join(lines)
        return card


class MoodState:
    """Tâm trạng phiên: valence (tiêu↔tích cực) + arousal (trầm↔hưng phấn). Phai về baseline."""

    def __init__(self, baseline_valence=0.2, baseline_arousal=0.5, decay=0.5):
        self.baseline_v = _clamp(baseline_valence, -1.0, 1.0)
        self.baseline_a = _clamp(baseline_arousal, 0.0, 1.0)
        self.decay = _clamp(decay, 0.0, 1.0)
        self.valence = self.baseline_v
        self.arousal = self.baseline_a

    def set_baseline(self, valence, arousal):
        """Đổi baseline (khi núm tính cách thay đổi) — mood sẽ phai dần về mốc mới."""
        self.baseline_v = _clamp(valence, -1.0, 1.0)
        self.baseline_a = _clamp(arousal, 0.0, 1.0)

    def update(self, user_valence=0.0, outcome=0.0, familiarity=0.3):
        """Cập nhật tất định: phai về baseline rồi cộng tín hiệu (cảm xúc user + kết quả việc).

        user_valence: -1..1 (cảm xúc người dùng). outcome: +1 làm được / -1 hỏng / 0.
        familiarity: 0..1 (càng thân càng nhích hưng phấn nhẹ).
        """
        self.valence += (self.baseline_v - self.valence) * self.decay
        self.arousal += (self.baseline_a - self.arousal) * self.decay
        self.valence = _clamp(self.valence + 0.4 * user_valence + 0.35 * outcome, -1.0, 1.0)
        self.arousal = _clamp(self.arousal + 0.2 * abs(user_valence) + 0.1 * familiarity, 0.0, 1.0)
        return self

    def to_pose(self):
        """Ánh xạ tâm trạng -> pose avatar EVE (neutral/happy/sad)."""
        if self.valence >= 0.25:
            return "happy"
        if self.valence <= -0.25:
            return "sad"
        return "neutral"

    def label(self):
        """Mô tả tâm trạng bằng tiếng Việt để bơm vào prompt."""
        v = self.valence
        if v >= 0.5:
            vw = "rất vui"
        elif v >= 0.25:
            vw = "vui"
        elif v >= 0.1:
            vw = "hơi vui"
        elif v > -0.1:
            vw = "bình thản"
        elif v > -0.25:
            vw = "hơi trầm"
        elif v > -0.5:
            vw = "buồn"
        else:
            vw = "khá buồn"
        aw = "hào hứng" if self.arousal >= 0.66 else "thoải mái" if self.arousal >= 0.4 else "trầm lặng"
        return f"{vw}, {aw}"


# --------------------- chấm cảm xúc người dùng (thuần, không LLM) --------------------- #

_POS_WORDS = ("vui", "thich", "tuyet", "cam on", "cam onnn", "hay qua", "tot", "yeu",
              "gioi", "on", "haha", "hihi", "tuyet voi", "thich qua", "vui qua", "ok",
              "ngon", "dep", "man nguyen", "hai long", "cool", "qua tuyet")
# Tất cả phải BỎ DẤU + thường (khớp với token đã norm). Tránh từ đơn dễ trùng nghĩa khác
# ('do'↔đó, 'cau'↔câu, 'ngu'↔ngủ) — dùng cụm rõ nghĩa thay thế.
_NEG_WORDS = ("buon", "te", "ghet", "chan", "buc", "gian", "kem", "that vong",
              "met", "kho chiu", "tuc", "toi te", "khong thich", "chan qua", "buon qua",
              "vo dung", "bucminh", "buc minh")


def _count_hits(t, tokens, words):
    """Đếm từ khoá: cụm (có khoảng trắng) khớp chuỗi con; từ đơn khớp theo TOKEN để
    tránh dính nhầm (vd 'on' của 'ổn' nằm trong 'khong')."""
    n = 0
    for w in words:
        if " " in w:
            if w in t:
                n += 1
        elif w in tokens:
            n += 1
    return n


def score_user_valence(text):
    """Ước lượng cảm xúc câu người dùng -> [-1, 1] bằng đếm từ khoá (tất định)."""
    t = norm(text or "")
    if not t:
        return 0.0
    tokens = set(t.split())
    pos = _count_hits(t, tokens, _POS_WORDS)
    neg = _count_hits(t, tokens, _NEG_WORDS)
    if pos == neg:
        return 0.0
    return _clamp((pos - neg) / float(pos + neg), -1.0, 1.0)
