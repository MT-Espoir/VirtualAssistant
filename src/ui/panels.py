"""
Nội dung của từng panel — hàm THUẦN, trả về danh sách KHỐI cho `ui/hud.py` vẽ.

Thêm một tính năng có panel = thêm MỘT hàm ở đây, không thêm file UI nào. Trước đây mỗi
tính năng là một file riêng và cả file đó chỉ khác nhau ở phần nội dung; phần dựng cửa
sổ thì chép lại y hệt.

Không import tkinter: mọi thứ ở đây test được mà không cần màn hình.
"""

from utils.units import say_distance

MAX_CARDS = 8


# ============================== ĐỊA ĐIỂM ==============================
#
# VÌ SAO CẦN PANEL, chứ không chỉ đọc bằng giọng: thuộc tính thẩm mỹ ("nhiều cây xanh",
# "phong cách cổ") không có hàm nào kiểm chứng được — khác hẳn khoảng cách (haversine)
# hay tên (khớp token). Đó là chỗ bịa đặt sẽ sống.
#
# Lời giải không phải làm trợ lý tự tin hơn, mà là TRƯNG BẰNG CHỨNG RA để mắt người dùng
# làm tầng kiểm chứng: biến một khẳng định không kiểm chứng được thành một trình bày
# kiểm chứng được.

def card_text(row, need=None):
    """Một ứng viên -> {title, meta, evidence, photos}. Hàm THUẦN.

    Giữ tên `evidence` chứ không đổi thành `lines` của khối HUD: đây là BẰNG CHỨNG, và
    cái tên đó chính là thứ nhắc người sửa sau rằng mỗi dòng ở đây phải lần ngược được
    về một nguồn. `places_blocks` mới là chỗ dịch sang từ vựng của HUD.

    Chỉ hiện trường CÓ dữ liệu thật; thiếu thì im lặng, không hiện ô trống, không đoán.
    """
    title = (row.get("name") or "").strip() or "(không rõ tên)"

    meta = []
    far = say_distance(row.get("distance_km"))
    if far:
        meta.append(far)
    if row.get("rating") is not None:
        # Điểm LUÔN kèm số lượt: 4,8 với 3 lượt khác hẳn 4,8 với vài trăm lượt.
        reviews = row.get("reviews")
        meta.append(f"★ {row['rating']}" + (f" ({reviews} lượt)" if reviews else ""))
    opening = (row.get("opening") or {}).get("state")
    if opening == "open_24h":
        meta.append("mở cả ngày")
    elif opening == "closing_soon":
        meta.append("sắp đóng cửa")
    elif opening == "closed":
        meta.append("đang đóng cửa")
    elif opening == "open":
        meta.append("đang mở cửa")

    evidence = []
    n = row.get("sources")
    if n:
        about = f" khi nói về {need}" if need else ""
        evidence.append(f"{n} nguồn nhắc tới{about}")
    if row.get("quote"):
        # Trích dẫn kèm TÊN NGUỒN: câu vô danh thì người dùng không lần lại được, mà cả
        # tấm thẻ này tồn tại để họ TỰ kiểm chứng chứ không phải để tin lời trợ lý.
        where = row.get("quote_source")
        evidence.append(f"“{row['quote']}”" + (f" — {where}" if where else ""))
    if not row.get("resolved", True):
        evidence.append("(chưa tra được trên bản đồ)")

    # Ưu tiên BYTES đã tải sẵn; URL chỉ là dự phòng (panel không được gọi mạng).
    return {"title": title, "meta": meta, "evidence": evidence,
            "photos": list(row.get("photo_data") or row.get("photos") or [])}


def panel_title(need, rows):
    """Tiêu đề panel. Nêu SỐ chỗ, không nêu nhận định về chất lượng."""
    what = " ".join(str(need or "").split())
    n = len(rows or [])
    if not n:
        return f"Không có chỗ nào cho: {what}" if what else "Không có kết quả"
    return f"{n} chỗ được nhiều nguồn nhắc tới" + (f" — {what}" if what else "")


def places_blocks(rows, need=None):
    """Danh sách ứng viên -> khối cho HudPanel. Rỗng -> [] (panel tự ẩn)."""
    if not rows:
        return []
    blocks = [("header", panel_title(need, rows))]
    for i, row in enumerate(rows[:MAX_CARDS], 1):
        card = card_text(row, need)
        blocks.append(("card", {
            "title": "%d. %s" % (i, card["title"]),
            "meta": card["meta"],
            "lines": card["evidence"],         # từ vựng miền -> từ vựng HUD
            "photos": card["photos"],
        }, i))                                 # khoá bấm = SỐ THỨ TỰ
    return blocks


# ============================== NHÁP EMAIL ==============================
#
# Gửi email là hành động KHÔNG rút lại được, mà thân thư do LLM viết thì lỗi nằm ở CHI
# TIẾT — sai tên, sai ngày, sai giọng văn với sếp. Nghe TTS đọc cả lá thư thì không soát
# được; liếc mắt thì thấy ngay.

def draft_header(draft):
    """Bản nháp -> danh sách (nhãn, giá trị) cho phần đầu thư. Hàm THUẦN.

    Chỉ trả trường CÓ dữ liệu thật — thiếu người nhận thì KHÔNG hiện ô 'Tới' trống, vì ô
    trống trông như đã điền mà rỗng, dễ khiến người dùng bấm Gửi mà không để ý.
    """
    draft = draft or {}
    rows = []
    if (draft.get("to") or "").strip():
        rows.append(("Tới", draft["to"].strip()))
    if (draft.get("subject") or "").strip():
        rows.append(("Tiêu đề", draft["subject"].strip()))
    return rows


def draft_blocks(draft):
    """Bản nháp -> khối cho HudPanel. Rỗng -> [] (panel tự ẩn).

    Thân thư hiện dạng văn bản CHỈ ĐỌC: panel này để soát, không phải trình soạn thảo.
    Cho sửa ở đây thì phần sửa sẽ KHÔNG đi vào lệnh gửi (lệnh đã chốt tham số lúc hoãn).
    """
    if not draft:
        return []
    blocks = [("header", "Xem lại trước khi gửi")]
    blocks.extend(("field", label, value) for label, value in draft_header(draft))
    body = (draft.get("body") or "").strip()
    if body:
        blocks.append(("body", body))
    blocks.append(("buttons", [("HUỶ", "no", "off"), ("GỬI", "yes", "go")]))
    return blocks


# ============================== THƯ ĐẾN ==============================
#
# Ngược chiều với panel nháp: nháp là thứ TA sắp gửi đi và phải soát; thư đến là thứ
# NGƯỜI KHÁC gửi tới và chỉ để đọc. Vì vậy panel này CỐ Ý KHÔNG CÓ NÚT nào — không có
# hành động nào phát sinh từ một màn hình đang hiển thị nội dung ta không kiểm soát.

def mail_blocks(mail):
    """Một lá thư -> khối cho HudPanel. Rỗng -> [] (panel tự ẩn).

    Tiêu đề lên `header` chứ không thành một dòng `field`: đó là thứ mắt tìm trước nhất
    khi liếc vào màn hình.
    """
    if not mail:
        return []
    blocks = [("header", (mail.get("tieu_de") or "(không tiêu đề)").strip())]
    for nhan, khoa in (("Từ", "tu"), ("Nhận lúc", "ngay")):
        gia_tri = (mail.get(khoa) or "").strip()
        if gia_tri:
            blocks.append(("field", nhan, gia_tri))
    than = (mail.get("than") or "").strip()
    # Thư chỉ có ảnh/HTML thì phần văn bản rỗng. Nói thẳng ra, đừng hiện khung trống —
    # khung trống trông như đang tải dở.
    blocks.append(("body", than or "(thư này không có phần văn bản thuần để hiện)"))
    return blocks


MAX_THU = 12        # trần số thư vẽ ra: panel để LƯỚT, không phải để cuộn cả hộp thư


def mail_list_title(rows, q=None):
    """Tiêu đề panel danh sách. Nêu SỐ thư và tiêu chí đã tìm, không nhận định gì thêm."""
    tieu_chi = " ".join(str(q or "").split())
    n = len(rows or [])
    if not n:
        return f"Không có thư nào khớp: {tieu_chi}" if tieu_chi else "Không có thư nào"
    return f"{n} thư" + (f" khớp: {tieu_chi}" if tieu_chi else "")


def mail_list_blocks(rows, q=None):
    """Danh sách thư -> khối cho HudPanel, mỗi thư một thẻ BẤM ĐƯỢC. Rỗng -> [].

    Khoá bấm là SỐ THỨ TỰ (1, 2, 3...) chứ không phải mã thư: số là thứ người dùng vừa
    nghe đọc và có thể nói ra ("mở cái thứ hai"), nên bấm và nói đi chung một đường.

    Vẫn KHÔNG có nút nào — xem ghi chú ở `mail_blocks`. Bấm một thẻ chỉ MỞ thư đó ra đọc.
    """
    if not rows:
        return []
    blocks = [("header", mail_list_title(rows, q))]
    for i, thu in enumerate(rows[:MAX_THU], 1):
        meta = [m for m in ((thu.get("tu") or "").strip(), (thu.get("ngay") or "").strip()) if m]
        blocks.append(("card", {
            "title": "%d. %s" % (i, (thu.get("tieu_de") or "(không tiêu đề)").strip()),
            "meta": meta,
            "lines": [],
            "photos": [],
        }, i))
    return blocks


# ============================== HÀNH ĐỘNG CHỜ DUYỆT ==============================

def outbound_blocks(payload):
    """Dữ liệu sắp RỜI MÁY -> khối cho HudPanel.

    MIỀN đứng riêng một dòng và đứng TRƯỚC URL đầy đủ. Đó là toàn bộ lý do panel này tồn
    tại: `https://google.com.evil.example/x` đọc lên nghe hệt google.com, và ngay cả khi
    nhìn cả chuỗi thì mắt cũng hay dừng ở phần đầu. Kéo miền thật ra đứng một mình thì
    không giấu vào đâu được.
    """
    blocks = [("header", "Sắp gửi dữ liệu RA NGOÀI máy")]
    if payload.get("url"):
        blocks.append(("field", "Miền", payload["mien"]))
        blocks.append(("body", payload["url"]))
    elif payload.get("truy_van"):
        blocks.append(("field", "Nội dung gửi đi", ""))
        blocks.append(("body", payload["truy_van"]))
    blocks.append(("buttons", [("HUỶ", "no", "off"), ("ĐỒNG Ý", "yes", "go")]))
    return blocks


def pending_blocks(payload):
    """Bất kỳ hành động nào đang CHỜ DUYỆT -> khối cho HudPanel. Rỗng -> [].

    Một bề mặt duyệt DUY NHẤT, phân nhánh theo hình dạng payload, thay vì mỗi loại một
    panel: nút HUỶ/ĐỒNG Ý đi chung một đường `agent.confirm_pending`, nên thêm loại hành
    động mới chỉ là thêm một cách VẼ, không phải thêm một đường thực thi.
    """
    if not payload:
        return []
    if payload.get("ra_ngoai"):
        return outbound_blocks(payload)
    return draft_blocks(payload)


def pending_title(payload):
    """Tiêu đề panel theo loại hành động đang chờ."""
    return "GỬI RA NGOÀI" if (payload or {}).get("ra_ngoai") else "NHÁP EMAIL"
