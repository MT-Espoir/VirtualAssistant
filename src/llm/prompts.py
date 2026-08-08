"""Truy cập system prompt (DRY: một nguồn duy nhất là llm/prompt_texts.py).

Nội dung prompt trước đây nằm trong components/data/system_prompt.json; đã chuyển sang
module Python để git diff đọc được từng dòng và ghi chú được ngay cạnh nội dung — xem
`prompt_texts.py`. Lớp này giữ nguyên chữ ký `load()/base()` nên nơi gọi không đổi.

Cấu trúc: {"base": ..., "router": ..., "cases": {tên_case: prompt_bổ_sung}}.
"""

from llm import prompt_texts


def load():
    """Trả dict {base, router, cases}. Trả BẢN SAO của `cases` để nơi gọi (vd Router giữ
    `self.data`) không sửa nhầm hằng dùng chung."""
    return {"base": prompt_texts.BASE,
            "router": prompt_texts.ROUTER,
            "cases": dict(prompt_texts.CASES)}


def base():
    return prompt_texts.BASE


def merged():
    """Prompt GỘP cho chế độ chạy KHÔNG router: base + mọi fragment case, có nhãn nhóm.

    Không router thì không ai chọn fragment theo case nữa; nếu chỉ dùng base trần thì mất
    sạch chỉ dẫn riêng (đọc nguyên văn kết quả tìm web, tra danh bạ trước khi soạn mail,
    phân biệt nhắc-giờ vs tự-làm...). Gộp hết vào một prompt: dài hơn nhưng CỐ ĐỊNH nên
    đổi lại được một round-trip LLM mỗi lượt.
    """
    parts = [prompt_texts.BASE, "", "## Hướng dẫn theo từng nhóm yêu cầu"]
    for name, fragment in prompt_texts.CASES.items():
        if fragment.strip():
            parts.append(f"[{name}] {fragment}")
    return "\n".join(parts)
