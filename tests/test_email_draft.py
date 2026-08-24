"""Test nhận dạng bản nháp email (thuần) + phần THUẦN của panel nháp.

Không đụng Tk: `draft_header` tách riêng đúng để test được mà không cần màn hình.
"""

try:
    import pytest
except ImportError:
    pytest = None

from actions.email_draft import email_draft, say_draft
from ui.draft_panel import draft_header


# --------------------------- nhận dạng --------------------------- #

def test_recognizes_standard_gmail_arguments():
    draft = email_draft({"to": "sep@x.com", "subject": "Xin nghỉ phép",
                         "body": "Kính gửi anh,\n\nEm xin nghỉ..."})
    assert draft == {"to": "sep@x.com", "subject": "Xin nghỉ phép",
                     "body": "Kính gửi anh,\n\nEm xin nghỉ..."}


def test_recognizes_alias_field_names():
    # Server MCP do người dùng tự chọn -> tên trường không đoán được theo một server.
    draft = email_draft({"recipient": "a@b.com", "title": "Chào", "content": "Nội dung."})
    assert draft["to"] == "a@b.com" and draft["subject"] == "Chào"
    assert draft["body"] == "Nội dung."


def test_extra_arguments_are_ignored():
    draft = email_draft({"to": "a@b.com", "subject": "S", "body": "B",
                         "user_email": "me@gmail.com"})
    assert set(draft) == {"to", "subject", "body"}


def test_missing_body_is_not_a_draft():
    assert email_draft({"to": "a@b.com", "subject": "S"}) is None
    assert email_draft({"to": "a@b.com", "subject": "S", "body": "   "}) is None


def test_body_only_is_not_a_draft():
    # BẪY: 'message' cũng là tham số của schedule_reminder / add_task. Chỉ có thân mà
    # không người nhận không tiêu đề thì KHÔNG được nhận nhầm thành email.
    assert email_draft({"message": "mua sữa"}) is None


def test_subject_without_recipient_still_a_draft():
    # Nháp chưa điền người nhận vẫn đáng hiện ra để người dùng thấy mà bổ sung.
    draft = email_draft({"subject": "Báo cáo tuần", "body": "Nội dung."})
    assert draft is not None and draft["to"] == ""


def test_non_dict_arguments_safe():
    assert email_draft(None) is None and email_draft("body") is None


# --------------------------- câu hỏi xác nhận --------------------------- #

def test_say_draft_names_recipient_and_subject_but_not_body():
    phrase = say_draft({"to": "sep@x.com", "subject": "Xin nghỉ phép",
                        "body": "Kính gửi anh, em xin nghỉ ngày mai vì lý do sức khoẻ."})
    assert "sep@x.com" in phrase and "Xin nghỉ phép" in phrase
    # Thân thư đã hiện trên panel -> KHÔNG đọc lại bằng giọng.
    assert "sức khoẻ" not in phrase


def test_say_draft_omits_missing_fields():
    assert say_draft({"to": "", "subject": "", "body": "x"}) == "gửi email"
    assert "tiêu đề" not in say_draft({"to": "a@b.com", "subject": "", "body": "x"})


def test_say_draft_distinguishes_save_from_send():
    # Đồng ý "lưu nháp" mà hệ thống gửi thật ra ngoài là hậu quả KHÁC HẲN.
    d = {"to": "thay@edu.vn", "subject": "Xin hướng dẫn đồ án", "body": "..."}
    assert say_draft(d, action="draft").startswith("lưu nháp email")
    assert say_draft(d, action="send").startswith("gửi email")
    assert say_draft(d).startswith("gửi email")          # mặc định: giả định xấu nhất


# --------------------------- phần thuần của panel --------------------------- #

def test_draft_header_lists_present_fields():
    rows = draft_header({"to": "a@b.com", "subject": "Chào", "body": "x"})
    assert rows == [("Tới", "a@b.com"), ("Tiêu đề", "Chào")]


def test_draft_header_hides_empty_fields():
    # Ô trống trông như đã điền mà rỗng -> dễ bấm Gửi mà không để ý.
    assert draft_header({"to": "", "subject": "Chào", "body": "x"}) == [("Tiêu đề", "Chào")]
    assert draft_header({}) == [] and draft_header(None) == []


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
