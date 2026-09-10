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

# Tham số nào của một lời gọi tool thì mang dữ liệu RA NGOÀI. Không dò bừa mọi chuỗi:
# đoán sai thì panel hiện nhầm thứ, mà panel hiện nhầm còn tệ hơn không hiện — người dùng
# soát cái sai rồi yên tâm.
_THAM_SO_URL = ("url", "website", "link")
_THAM_SO_TRUY_VAN = ("query", "q", "need", "topic", "keyword")

_MIEN = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#@]*@)?([^/?#:]+)")


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
