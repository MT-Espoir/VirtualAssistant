"""Benchmark tổng hợp cho retrieval memory.

Không dùng dữ liệu thật của người dùng. Mỗi case có nhãn expected/forbidden rõ ràng và
đủ nhiễu để chạy đúng top-K production thay vì kiểm tra một fact cô lập.
"""

_DISTRACTORS = [
    {"id": "d_ui", "source": "notes", "text": "Màu giao diện mặc định là tím"},
    {"id": "d_light", "source": "notes", "text": "Bàn làm việc cần ánh sáng ấm"},
    {"id": "d_docs", "source": "auto_facts", "text": "Đọc tài liệu kỹ thuật vào thứ hai"},
    {"id": "d_notify", "source": "notes", "text": "Tắt thông báo sau 22 giờ"},
    {"id": "d_keyboard", "source": "auto_facts", "text": "Ưu tiên bàn phím cơ yên tĩnh"},
    {"id": "d_japanese", "source": "notes", "text": "Mục tiêu năm nay là học tiếng Nhật"},
    {"id": "d_cat", "source": "notes", "text": "Đang nuôi một con mèo tên Mướp"},
]


def _case(case_id, query, fact, *, tag="lexical", forbidden=(), extra=()):
    target = {"id": f"{case_id}_target", "source": "notes", "text": fact}
    return {
        "id": case_id,
        "tag": tag,
        "query": query,
        "facts": [*_DISTRACTORS, target, *extra],
        "expected": [target["id"]],
        "forbidden": list(forbidden),
    }


_LEXICAL = [
    ("coffee", "pha cà phê thế nào", "Thích cà phê sữa ít đường"),
    ("running", "lịch chạy bộ", "Chạy bộ vào sáng chủ nhật"),
    ("python", "dự án Python", "Đang học lập trình Python"),
    ("allergy", "dị ứng món gì", "Dị ứng với đậu phộng"),
    ("music", "mở nhạc jazz", "Thích nghe nhạc jazz khi làm việc"),
    ("movie", "gợi ý phim khoa học", "Thích phim khoa học viễn tưởng"),
    ("breakfast", "bữa sáng yến mạch", "Thường ăn yến mạch vào bữa sáng"),
    ("meeting", "cuộc họp thiết kế", "Có họp thiết kế vào chiều thứ tư"),
    ("language", "tiếp tục học tiếng Hàn", "Đang học tiếng Hàn sơ cấp"),
    ("travel", "chuyến đi Đà Lạt", "Muốn đi Đà Lạt vào mùa khô"),
    ("book", "cuốn sách lịch sử", "Đang đọc sách lịch sử Việt Nam"),
    ("tea", "pha trà ô long", "Thích trà ô long nóng"),
    ("sleep", "giờ đi ngủ", "Thường đi ngủ lúc 23 giờ"),
    ("lunch", "đặt cơm trưa chay", "Ưu tiên món chay cho bữa trưa"),
    ("design", "công việc thiết kế", "Làm công việc thiết kế sản phẩm"),
    ("swimming", "lịch bơi tối", "Đi bơi vào tối thứ ba"),
    ("podcast", "podcast kinh doanh", "Hay nghe podcast về kinh doanh"),
    ("camera", "mang máy ảnh", "Dùng máy ảnh Fujifilm khi du lịch"),
    ("doctor", "lịch khám nha sĩ", "Có lịch khám nha sĩ vào tháng mười"),
    ("dog", "thức ăn cho chó Bông", "Con chó ở nhà tên Bông"),
]

_ACCENT = [
    ("accent_cafe", "toi thich ca phe", "Tôi thích cà phê rang vừa"),
    ("accent_hue", "chuyen di hue", "Muốn du lịch Huế vào tháng sáu"),
    ("accent_yoga", "tap yoga buoi sang", "Tập yoga vào buổi sáng"),
    ("accent_com", "com tam sai gon", "Thích cơm tấm Sài Gòn"),
    ("accent_bong", "choi cau long", "Chơi cầu lông cuối tuần"),
    ("accent_sach", "doc sach tam ly", "Đang đọc sách tâm lý học"),
]

_SEMANTIC = [
    ("semantic_jog", "lịch jogging cuối tuần", "Chạy bộ vào sáng chủ nhật"),
    ("semantic_coffee", "tôi hay uống coffee gì", "Thích cà phê sữa ít đường"),
    ("semantic_cinema", "gợi ý cinema tối nay", "Thích xem phim tài liệu"),
    ("semantic_job", "occupation của tôi", "Làm nghề thiết kế sản phẩm"),
    ("semantic_pet", "tên pet trong nhà", "Con mèo ở nhà tên Mướp"),
    ("semantic_vehicle", "phương tiện commute", "Đi làm bằng xe buýt"),
]


MEMORY_RETRIEVAL_CASES = [
    *[_case(case_id, query, fact) for case_id, query, fact in _LEXICAL],
    *[_case(case_id, query, fact, tag="accent") for case_id, query, fact in _ACCENT],
    *[_case(case_id, query, fact, tag="semantic") for case_id, query, fact in _SEMANTIC],
]

# Hai fact mâu thuẫn cùng khớp lexical: benchmark đo rò rỉ, chưa giả vờ rằng ranker hiện
# tại hiểu phủ định. Đây là tín hiệu để chỉ nâng cấp retrieval khi dữ liệu thật xác nhận.
for suffix, query, current, stale in [
    ("coffee_time", "cà phê sau 15 giờ", "Không uống cà phê sau 15 giờ",
     "Thường uống cà phê sau 15 giờ"),
    ("notifications", "thông báo ban đêm", "Không nhận thông báo ban đêm",
     "Muốn nhận thông báo ban đêm"),
    ("diet", "ăn thịt bò", "Không ăn thịt bò", "Thích ăn thịt bò"),
    ("meeting", "họp sáng thứ hai", "Không họp sáng thứ hai", "Có họp sáng thứ hai"),
]:
    forbidden_id = f"contradiction_{suffix}_stale"
    MEMORY_RETRIEVAL_CASES.append(_case(
        f"contradiction_{suffix}", query, current, tag="contradiction",
        forbidden=[forbidden_id],
        extra=[{"id": forbidden_id, "source": "auto_facts", "text": stale}],
    ))

# Candidate không đủ điều kiện phải bị lọc trước ranker, dù lexical match hoàn hảo.
MEMORY_RETRIEVAL_CASES.append(_case(
    "eligibility_expired", "chạy marathon tháng mười", "Chạy marathon tháng mười một",
    tag="eligibility",
    extra=[{"id": "expired_marathon", "source": "auto_facts",
            "text": "Chạy marathon tháng mười", "expired": True}],
))
MEMORY_RETRIEVAL_CASES.append(_case(
    "eligibility_rejected", "dị ứng hải sản", "Dị ứng với tôm",
    tag="eligibility",
    extra=[{"id": "rejected_seafood", "source": "auto_facts",
            "text": "Dị ứng hải sản", "status": "rejected"}],
))
