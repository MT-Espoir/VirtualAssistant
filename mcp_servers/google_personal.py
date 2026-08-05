"""MCP server CÁ NHÂN cho Google Calendar + Gmail, chạy LOCAL.
Calendar CHỈ ĐỌC; Gmail ĐỌC + SOẠN NHÁP + GỬI (không xoá thư).

Ưu tiên BẢO MẬT:
- Scope TỐI THIỂU: calendar.readonly + gmail.readonly + gmail.compose (soạn nháp/gửi) — xem SCOPES.
- GỬI mail đi qua CỔNG XÁC NHẬN của trợ lý (tên tool chứa 'send' -> destructive).
- LƯU NHÁP (gws_gmail_draft) KHÔNG gửi ra ngoài -> không cần xác nhận (xem lại/sửa trên Gmail).
- OAuth client của CHÍNH bạn (credentials.json bạn tự tạo trong Google Cloud).
- Token lưu LOCAL cạnh file này (token.json) — ĐÃ gitignore, không rời máy.
- Server chạy stdio, không mở cổng mạng; dữ liệu chỉ đi giữa máy bạn và Google API.

Chạy lần đầu: `python google_personal.py` -> mở browser xin quyền -> tạo token.json.
Nối vào trợ lý: đặt trong src/.env
    MCP_ENABLED=true
    MCP_COMMAND=<python của ml_env>
    MCP_ARGS=<đường dẫn tuyệt đối tới file này>
    MCP_TOOL_PREFIX=gws_

Cần: pip install -U mcp google-api-python-client google-auth-oauthlib
"""

import base64
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastmcp import FastMCP

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Calendar CHỈ ĐỌC; Gmail đọc + soạn/gửi. gmail.compose = tạo nháp + GỬI (không đọc/xoá
# thư đến — việc đọc do gmail.readonly lo). Đổi SCOPES thì PHẢI cấp lại OAuth:
# `python google_personal.py --setup` (tự xoá token cũ).
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/contacts.readonly",
]

_HERE = os.path.dirname(os.path.abspath(__file__))
_CREDS_FILE = os.path.join(_HERE, "credentials.json")   # BẠN tải từ Google Cloud

mcp = FastMCP("google-personal")


def _token_path(user_email=None, token_file=None):
    """Đường dẫn token cho một tài khoản. Ưu tiên `token_file` (đường dẫn tuỳ ý); nếu không
    thì suy từ `user_email` (vd work@gmail.com -> token_work_gmail_com.json); rỗng -> mặc định.
    Nhờ MỖI tài khoản một file token riêng nên thao tác nhiều Gmail độc lập, không đè nhau."""
    if token_file:
        return token_file if os.path.isabs(token_file) else os.path.join(_HERE, token_file)
    if user_email:
        safe = re.sub(r"[^a-z0-9]+", "_", user_email.strip().lower()).strip("_")
        return os.path.join(_HERE, f"token_{safe}.json")
    return os.path.join(_HERE, "token.json")


def _creds(user_email=None, token_file=None, allow_interactive=False):
    """Credentials cho một tài khoản. Tái dùng/làm mới token có sẵn. OAuth tương tác (mở
    browser) CHỈ khi allow_interactive=True (bước --setup) — KHÔNG bao giờ giữa lúc gọi tool."""
    path = _token_path(user_email, token_file)
    creds = Credentials.from_authorized_user_file(path, SCOPES) if os.path.exists(path) else None

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save(creds, path)
        return creds

    if not allow_interactive:
        label = user_email or "mặc định"
        raise RuntimeError(
            f"Chưa cấp OAuth cho tài khoản '{label}'. Chạy setup trước:\n"
            f"    python google_personal.py --setup {user_email or ''}".rstrip())

    if not os.path.exists(_CREDS_FILE):
        raise RuntimeError("Thiếu credentials.json — tạo OAuth client (Desktop) trong Google "
                           "Cloud Console rồi tải về đặt cạnh file này.")
    creds = InstalledAppFlow.from_client_secrets_file(_CREDS_FILE, SCOPES).run_local_server(port=0)
    _save(creds, path)
    return creds


def _save(creds, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def _calendar(user_email=None):
    return build("calendar", "v3", credentials=_creds(user_email), cache_discovery=False)


def _gmail(user_email=None):
    return build("gmail", "v1", credentials=_creds(user_email), cache_discovery=False)


def _people(user_email=None):
    return build("people", "v1", credentials=_creds(user_email), cache_discovery=False)


def _strip_accents(s):
    """Bỏ dấu tiếng Việt để khớp tên không phân biệt dấu (server độc lập, không import src)."""
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn").lower()


def _fmt_event(e):
    start = e["start"].get("dateTime", e["start"].get("date", "?"))
    return f"- {start}: {e.get('summary', '(không tiêu đề)')}"


# --------------------------- Calendar (read-only) --------------------------- #

@mcp.tool()
def gws_calendar_today(user_email: str = "") -> str:
    """Liệt kê sự kiện Google Calendar HÔM NAY. user_email: tài khoản cần dùng (rỗng = mặc định)."""
    now = datetime.now(timezone.utc)
    end = now.replace(hour=23, minute=59, second=59)
    items = _calendar(user_email or None).events().list(
        calendarId="primary", timeMin=now.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=20).execute().get("items", [])
    if not items:
        return "Hôm nay không có sự kiện nào trên lịch."
    return "Sự kiện hôm nay:\n" + "\n".join(_fmt_event(e) for e in items)


@mcp.tool()
def gws_calendar_upcoming(days: int = 7, user_email: str = "") -> str:
    """Sự kiện Google Calendar trong `days` ngày tới. user_email: tài khoản (rỗng = mặc định)."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=max(1, days))
    items = _calendar(user_email or None).events().list(
        calendarId="primary", timeMin=now.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime", maxResults=30).execute().get("items", [])
    if not items:
        return f"Không có sự kiện nào trong {days} ngày tới."
    return f"Sự kiện {days} ngày tới:\n" + "\n".join(_fmt_event(e) for e in items)


# --------------------------- Gmail (read-only) --------------------------- #

def _header(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


@mcp.tool()
def gws_gmail_unread(max_results: int = 10, user_email: str = "") -> str:
    """Liệt kê email CHƯA ĐỌC (người gửi, tiêu đề, mã) — tối đa `max_results`.
    user_email: tài khoản Gmail cần dùng (rỗng = mặc định; vd 'work@gmail.com')."""
    svc = _gmail(user_email or None)
    ids = svc.users().messages().list(
        userId="me", q="is:unread", maxResults=max(1, min(max_results, 25))
    ).execute().get("messages", [])
    if not ids:
        return "Không có email chưa đọc."
    lines = []
    for m in ids:
        msg = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject"]).execute()
        lines.append(f"- [{m['id']}] {_header(msg, 'From')} — {_header(msg, 'Subject') or '(không tiêu đề)'}")
    return f"Có {len(lines)} email chưa đọc:\n" + "\n".join(lines)


def _plain_body(payload):
    """Rút phần text/plain của email (đệ quy qua các part). '' nếu không có."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []):
        body = _plain_body(part)
        if body:
            return body
    return ""


@mcp.tool()
def gws_gmail_read(message_id: str, user_email: str = "") -> str:
    """Đọc nội dung một email theo MÃ (lấy từ gws_gmail_unread). user_email: cùng tài khoản
    đã liệt kê (rỗng = mặc định)."""
    msg = _gmail(user_email or None).users().messages().get(
        userId="me", id=message_id, format="full").execute()
    frm = _header(msg, "From")
    subj = _header(msg, "Subject") or "(không tiêu đề)"
    body = _plain_body(msg.get("payload", {})).strip() or msg.get("snippet", "")
    return f"Từ: {frm}\nTiêu đề: {subj}\n\n{body[:4000]}"


# --------------------------- Gmail (soạn/gửi) --------------------------- #

def _build_raw(to, subject, body):
    """Dựng email văn bản thuần -> chuỗi base64url cho Gmail API. Trả (raw, tiêu_đề_đã_chuẩn)."""
    mail = EmailMessage()
    mail["To"] = to
    mail["Subject"] = subject or "(không tiêu đề)"
    mail.set_content(body or "")
    return base64.urlsafe_b64encode(mail.as_bytes()).decode(), mail["Subject"]


@mcp.tool()
def gws_gmail_send(to: str, subject: str, body: str, user_email: str = "") -> str:
    """GỬI một email (đi ra ngoài NGAY). `to` = người nhận (nhiều người ngăn bằng dấu phẩy),
    `subject` = tiêu đề, `body` = nội dung văn bản thuần. user_email: tài khoản gửi (rỗng =
    mặc định). Trợ lý sẽ đọc lại nội dung và HỎI XÁC NHẬN trước khi gọi công cụ này. Nếu người
    dùng muốn xem/sửa lại trước khi gửi thì dùng gws_gmail_draft (lưu nháp) thay vì gửi ngay."""
    to = (to or "").strip()
    if not to:
        return "Chưa có người nhận — cần địa chỉ email của người nhận."
    raw, subj = _build_raw(to, subject, body)
    sent = _gmail(user_email or None).users().messages().send(
        userId="me", body={"raw": raw}).execute()
    return f"Đã gửi email tới {to} (tiêu đề: {subj}, mã: {sent.get('id', '?')})."


@mcp.tool()
def gws_gmail_draft(to: str, subject: str, body: str, user_email: str = "") -> str:
    """SOẠN & LƯU NHÁP một email vào mục Nháp của Gmail — KHÔNG gửi đi. Dùng khi người dùng
    muốn tự xem lại/chỉnh sửa rồi mới gửi bằng tay trên Gmail. Tham số như gws_gmail_send;
    `to` có thể để trống nếu chưa rõ người nhận. user_email: tài khoản (rỗng = mặc định)."""
    raw, subj = _build_raw((to or "").strip(), subject, body)
    draft = _gmail(user_email or None).users().drafts().create(
        userId="me", body={"message": {"raw": raw}}).execute()
    dest = f" cho {to}" if to else ""
    return (f"Đã lưu nháp email{dest} (tiêu đề: {subj}, mã nháp: {draft.get('id', '?')}). "
            f"Bạn mở mục Nháp trong Gmail để xem lại, chỉnh sửa rồi gửi.")


# --------------------------- Contacts (read-only) --------------------------- #

@mcp.tool()
def gws_contacts_search(query: str, user_email: str = "") -> str:
    """Tìm LIÊN HỆ trong Google Contacts theo tên (trả tên + (các) email). Dùng để lấy địa
    chỉ email khi người dùng chỉ nói TÊN người nhận. `query` = tên/chuỗi cần tìm (rỗng = liệt
    kê tất cả). user_email: tài khoản (rỗng = mặc định)."""
    q = _strip_accents(query).strip()
    conns = _people(user_email or None).people().connections().list(
        resourceName="people/me", personFields="names,emailAddresses",
        pageSize=1000, sortOrder="FIRST_NAME_ASCENDING").execute().get("connections", [])
    lines = []
    for p in conns:
        names = p.get("names", [])
        name = names[0].get("displayName", "") if names else ""
        emails = [e.get("value", "") for e in p.get("emailAddresses", []) if e.get("value")]
        if not emails:
            continue
        if not q or q in _strip_accents(name):
            lines.append(f"- {name or '(không tên)'}: {', '.join(emails)}")
    if not lines:
        return f"Không thấy liên hệ nào khớp '{query}' trong Google Contacts."
    return f"Tìm thấy {len(lines)} liên hệ:\n" + "\n".join(lines[:15])


if __name__ == "__main__":
    import sys
    # Cấp OAuth cho MỘT tài khoản (mở browser) — làm TRƯỚC khi chạy server:
    #   python google_personal.py --setup                 # tài khoản mặc định (token.json)
    #   python google_personal.py --setup work@gmail.com   # tài khoản khác (token_work_gmail_com.json)
    if len(sys.argv) >= 2 and sys.argv[1] == "--setup":
        acct = sys.argv[2] if len(sys.argv) > 2 else None
        # Xoá token cũ để LUÔN đồng ý lại — cần khi SCOPES đổi (vd vừa thêm gmail.send),
        # nếu không token cũ vẫn "valid" nhưng thiếu quyền -> API 403 khó hiểu.
        old = _token_path(acct)
        if os.path.exists(old):
            os.remove(old)
        _creds(user_email=acct, allow_interactive=True)
        print(f"Đã cấp OAuth cho '{acct or 'mặc định'}'. Token lưu: {_token_path(acct)}")
    else:
        mcp.run()      # transport stdio (chạy như MCP server)
