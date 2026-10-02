"""Cầu nối giọng chung giữa persona toàn hệ thống và các lane phát lời SALM.

SALM vẫn giữ system contract riêng để bảo vệ privacy/factual/safety; module này chỉ bảo
đảm nó không vô tình tạo ra một nhân cách thứ hai khi gọi LLM ngoài Agent loop.
"""


def compose_speech_system(contract, persona_context_provider=None):
    """Ghép persona động với contract của lane; provider lỗi thì giữ đường cũ an toàn."""
    context = ""
    if persona_context_provider is not None:
        try:
            supplied = persona_context_provider()
            context = supplied.strip() if isinstance(supplied, str) else ""
        except Exception:
            context = ""
    if not context:
        return contract
    return (
        "NHÂN CÁCH CHUNG CỦA TRỢ LÝ (giữ nhất quán với mọi hội thoại):\n"
        f"{context}\n\n"
        "HỢP ĐỒNG RIÊNG CỦA LANE SALM:\n"
        "Các giới hạn an toàn, dữ kiện được phép nói và định dạng trong hợp đồng dưới "
        "đây luôn được ưu tiên. Trong phần còn lại, phải diễn đạt đúng nhân cách chung; "
        "không tự thay bằng một giọng generic khác.\n"
        f"{contract}"
    )
