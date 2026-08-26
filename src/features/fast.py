"""
Gom fast-path của các feature đã nạp.

Fast-path là tầng 0 — đường DUY NHẤT không tốn lượt LLM nào. Trước đây mọi luật nằm
tập trung ở `voice/fast_commands.py`, nên thêm một tính năng có lệnh trực tiếp lại phải
sửa một file ở tầng khác. Nay mỗi feature mang luật của mình trong `fast.py` và khai qua
`Feature.fast_paths`.

Chỉ dành cho lệnh TẤT ĐỊNH, đơn giản (âm lượng, media, cuộn, chụp). Yêu cầu phức tạp
(tìm YouTube, tra web...) để router + LLM lo — luật cứng mà "hijack" mất câu phức tạp
thì hại nhiều hơn lợi.
"""


def match(text, report):
    """Trả (tool_name, args) nếu `text` khớp một fast-path của feature ĐÃ NẠP; None nếu không.

    Duyệt theo thứ tự `FEATURES`, mỗi feature theo thứ tự `fast_paths` của nó. Feature bị
    bỏ qua (thiếu dependency / tắt bằng config) thì luật của nó không tham gia — trước đây
    luật vẫn khớp rồi mới phát hiện tool không tồn tại.
    """
    for rule in report.fast_paths():
        hit = rule(text)
        if hit is not None:
            return hit
    return None
