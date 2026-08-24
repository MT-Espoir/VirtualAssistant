"""
Nhận dạng "một lời gọi tool ĐANG ĐỊNH GỬI EMAIL" -> bản nháp {to, subject, body}.

VÌ SAO CẦN: email là hành động KHÔNG HOÀN TÁC ĐƯỢC, và nội dung do LLM viết ra thì
người dùng phải ĐỌC BẰNG MẮT mới kiểm được — đọc một lá thư dài qua TTS vừa mất cả
phút vừa không nhớ nổi câu nào sai. Panel nháp (ui/draft_panel.py) là tầng kiểm chứng
bằng mắt, cùng lý lẽ với panel địa điểm ở `docs/research_lane_spec.md` §12.

Hàm ở đây THUẦN và KHÔNG biết gì về Tk: `tools.py` gọi để dựng payload lúc hoãn hành
động, `ui/` chỉ nhận dict rồi vẽ. Giữ đúng ranh giới của repo (core không import UI).

KHÔNG dò theo TÊN TOOL: server MCP do người dùng tự chọn nên tên tool không đoán được
(`gws_gmail_send`, `send_email`, `gmail.messages.send`...). Dò theo HÌNH DẠNG THAM SỐ
thì server nào cũng nhận đúng.
"""

# Tên trường mỗi server MCP đặt một kiểu -> gom về ba khoá chuẩn.
_TO_KEYS = ("to", "recipient", "recipients", "to_email", "email_to")
_SUBJECT_KEYS = ("subject", "title", "tieu_de")
_BODY_KEYS = ("body", "content", "message", "text", "noi_dung")


def _first(arguments, keys):
    """Giá trị đầu tiên khác rỗng trong `keys`. Trả chuỗi đã strip ('' nếu không có)."""
    for key in keys:
        value = arguments.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def email_draft(arguments):
    """Tham số một lời gọi tool -> {to, subject, body}, hoặc None nếu KHÔNG phải email.

    Điều kiện nhận: có phần THÂN THƯ, và có ít nhất một trong hai (người nhận, tiêu đề).
    Đòi thêm điều kiện thứ hai để 'message' của schedule_reminder / add_task (chỉ có
    thân, không người nhận không tiêu đề) không bị nhầm thành email.
    """
    if not isinstance(arguments, dict):
        return None
    body = _first(arguments, _BODY_KEYS)
    if not body:
        return None
    to = _first(arguments, _TO_KEYS)
    subject = _first(arguments, _SUBJECT_KEYS)
    if not to and not subject:
        return None
    return {"to": to, "subject": subject, "body": body}


def say_draft(draft, action="send"):
    """Bản nháp -> cụm mô tả NGẮN để hỏi xác nhận bằng giọng.

    Cố ý KHÔNG đọc thân thư: thân thư đã hiện trên panel cho người dùng ĐỌC. Đọc lại
    bằng giọng vừa thừa vừa dài, mà cái cần nghe chỉ là "gửi cho ai, chuyện gì".

    `action`: 'send' (thư đi ra ngoài) hay 'draft' (chỉ lưu vào mục Nháp). Hai việc này
    KHÁC HẲN nhau về hậu quả nên câu hỏi phải nói đúng cái nào — người dùng đồng ý
    "lưu nháp" mà hệ thống gửi thật là kiểu phản bội tin cậy tệ nhất.
    """
    draft = draft or {}
    who = f" tới {draft['to']}" if draft.get("to") else ""
    what = f" với tiêu đề {draft['subject']}" if draft.get("subject") else ""
    verb = "lưu nháp email" if action == "draft" else "gửi email"
    return f"{verb}{who}{what}"
