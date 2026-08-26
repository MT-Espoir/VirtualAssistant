"""
Lắp ráp system prompt từ các mảnh feature góp vào.

Trước đây nội dung prompt nằm gọn trong `llm/prompt_texts.py`: một `BASE`, một `ROUTER`
viết liền, và dict `CASES` liệt kê từng nhóm. Nghĩa là thêm một tính năng phải sửa hai
chỗ nữa ngoài thư mục feature — và bảng liệt kê đã lệch thật (`ROUTER` bảo model chỉ
được trả về một trong 10 từ khoá, nhưng thiếu `pim` dù `pim` được mô tả ngay bên dưới).

Nay `prompt_texts` chỉ giữ những mảnh KHÔNG thuộc feature nào — `BASE`, phần đầu và
phần đuôi của prompt phân loại — còn mỗi feature mang theo `prompt` (dạy model LÀM) và
`router_hint` (dạy model NHẬN RA). Hàm ở đây ghép chúng lại từ `LoadReport`.
"""

from features.contract import GENERAL_CASE
from llm import prompt_texts


def base():
    return prompt_texts.BASE


def load(report):
    """Trả dict {base, router, cases} dựng từ các feature đã nạp.

    Chữ ký đổi so với bản cũ (`load()` không tham số): dữ liệu prompt nay phụ thuộc
    feature nào THỰC SỰ nạp được, mà điều đó chỉ biết sau khi nạp xong. Tắt một feature
    bằng config giờ cũng gỡ luôn nó khỏi prompt phân loại — trước đây prompt vẫn mô tả
    một nhóm không còn tool nào.
    """
    return {"base": prompt_texts.BASE,
            "router": router(report),
            "cases": cases(report)}


def cases(report):
    """{tên case -> đoạn prompt}, kèm 'general' (rỗng: không có chỉ dẫn riêng)."""
    data = report.cases()
    data[GENERAL_CASE] = ""
    return data


def router(report):
    """Prompt cho lượt PHÂN LOẠI: đầu + một dòng mỗi case + đuôi.

    Danh sách từ khoá ở phần đầu sinh từ chính các case đang có, nên không thể lệch với
    phần mô tả bên dưới như bản viết tay trước đây.
    """
    ten_case = report.case_names() + [GENERAL_CASE]
    dong = [prompt_texts.ROUTER_HEADER.format(cases="/".join(ten_case))]
    dong += report.router_hints()
    dong.append(prompt_texts.GENERAL_HINT)
    dong.append(prompt_texts.ROUTER_TAIL)
    return "\n".join(dong)


def merged(report):
    """Prompt GỘP cho chế độ chạy KHÔNG router: base + mọi fragment case, có nhãn nhóm.

    Không router thì không ai chọn fragment theo case nữa; nếu chỉ dùng base trần thì mất
    sạch chỉ dẫn riêng (đọc nguyên văn kết quả tìm web, tra danh bạ, phân biệt nhắc-giờ vs
    tự-làm...). Gộp hết vào một prompt: dài hơn nhưng CỐ ĐỊNH nên đổi lại được một
    round-trip LLM mỗi lượt.
    """
    parts = [prompt_texts.BASE, "", "## Hướng dẫn theo từng nhóm yêu cầu"]
    for name, fragment in report.prompt_fragments():
        parts.append(f"[{name}] {fragment}")
    return "\n".join(parts)
