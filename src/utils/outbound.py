"""
Mô tả thứ SẮP RỜI MÁY, để trưng lên panel trước khi hỏi người dùng.

Vì sao phải NHÌN chứ không chỉ NGHE: đây là trợ lý dùng bằng giọng nói, mà tai không
phân biệt được `https://google.com.evil.example/x` với `google.com` — đọc lên nghe y hệt.
Mắt thì thấy ngay. Đợt soi bảo mật 2026-08-29 xếp đây là điểm yếu #3, và nó nghiêm trọng
vì xác nhận bằng giọng lại đang là lớp phòng thủ CHÍNH.

Cách chữa nằm ở chỗ TÁCH MIỀN RA RIÊNG và đặt lên trước: kẻ tấn công giấu miền thật ở
cuối một chuỗi dài, còn panel kéo nó ra đứng một mình.

Hàm THUẦN, không I/O — nên `agent/tools.py` gọi được mà không kéo theo tầng nào.
"""

import re

from utils.text_norm import strip_accents

# Tham số nào của một lời gọi tool thì mang dữ liệu RA NGOÀI. Không dò bừa mọi chuỗi:
# đoán sai thì panel hiện nhầm thứ, mà panel hiện nhầm còn tệ hơn không hiện — người dùng
# soát cái sai rồi yên tâm.
_THAM_SO_URL = ("url", "website", "link")
_THAM_SO_TRUY_VAN = ("query", "q", "need", "topic", "keyword")

_MIEN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#@]*@)?([^/?#:]+)")

# Từ model thường thêm để biến câu tự nhiên thành truy vấn. Chúng không mang dữ liệu
# riêng và được phép vắng trong câu gốc. Danh sách cố ý hẹp: token lạ thì vẫn phải duyệt.
_TU_MO_RONG_CONG_KHAI = frozenset({
    "su", "ve", "thong", "tin", "tim", "kiem", "tra", "cuu", "hien", "tai",
    "moi", "nhat", "khai", "niem", "dinh", "nghia", "phan", "biet", "so", "sanh",
    "tai", "sao", "vi", "nhu", "the", "nao", "la", "gi", "cua", "cho",
    "https", "http", "www", "com", "net", "org", "vn", "html", "htm",
})


def _tokens(value):
    return re.findall(r"[a-z0-9]+", strip_accents(str(value or "")).lower())


def duoc_nguoi_dung_cung_cap(args, user_text):
    """True nếu dữ liệu outbound chỉ là cách viết lại điều user VỪA nói.

    Đây là kiểm tra provenance, không phải đoán nội dung có "nhạy cảm" hay không. Một token
    có nghĩa do model/web/ký ức tự thêm làm kết quả False; cổng xác nhận vẫn giữ nguyên.
    URL đầy đủ người dùng vừa đọc được chấp nhận; URL model tự ghép query/path lạ thì không.
    """
    if not isinstance(user_text, str) or not user_text.strip():
        return False
    user_tokens = set(_tokens(user_text))
    if not user_tokens:
        return False
    outbound = None
    for name in _THAM_SO_URL + _THAM_SO_TRUY_VAN:
        value = (args or {}).get(name)
        if isinstance(value, str) and value.strip():
            outbound = value.strip()
            break
    if outbound is None:
        return False
    meaningful = set(_tokens(outbound)) - _TU_MO_RONG_CONG_KHAI
    return bool(meaningful) and meaningful.issubset(user_tokens)


def lay_mien(url):
    """URL -> miền (không có cổng, không userinfo). '' nếu không phải URL.

    Bỏ phần `user@` trước miền: `https://google.com@evil.example/` là URL hợp lệ mà mắt
    thường đọc thành "google.com". Trình duyệt đi tới evil.example.
    """
    khop = _MIEN.match((url or "").strip())
    if not khop:
        return ""
    return khop.group(2).strip().lower()


def mo_ta_ra_ngoai(args):
    """Tham số một lời gọi -> dict cho panel, hoặc None nếu không có gì đi ra ngoài.

    Trả `{"ra_ngoai": True, "mien": ..., "url": ...}` cho URL, hoặc
    `{"ra_ngoai": True, "truy_van": ...}` cho chuỗi tìm kiếm.
    """
    args = args or {}
    for ten in _THAM_SO_URL:
        gia_tri = args.get(ten)
        if isinstance(gia_tri, str) and gia_tri.strip():
            mien = lay_mien(gia_tri)
            return {"ra_ngoai": True, "url": gia_tri.strip(),
                    # Không phải URL đầy đủ (vd "youtube") thì không bịa ra miền.
                    "mien": mien or "(không rõ miền)"}
    for ten in _THAM_SO_TRUY_VAN:
        gia_tri = args.get(ten)
        if isinstance(gia_tri, str) and gia_tri.strip():
            return {"ra_ngoai": True, "truy_van": gia_tri.strip()}
    return None
