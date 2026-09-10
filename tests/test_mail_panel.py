"""
Panel THƯ ĐẾN — hiện nội dung email cho MẮT đọc, không đổ vào tai và không đổ vào LLM.

Tính chất trung tâm của cả file: **nội dung thư không đi qua ngữ cảnh LLM.** Thư là do
người ngoài soạn; `untrusted.boc()` chỉ là giảm thiểu, còn không-đưa-vào là triệt tiêu.
Đường panel là đường duy nhất có được tính chất đó, nên nó phải được canh bằng test chứ
không phải bằng thiện chí.

Ba đường cho ba ý định, đừng lẫn:
    "có mail nào về X không"  -> gws_gmail_search  (chỉ tiêu đề)
    "cho tôi xem thư đó"      -> show_email        (panel; KHÔNG qua LLM)  <- file này
    "tóm tắt thư đó"          -> gws_gmail_read    (nội dung VÀO ngữ cảnh)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from conftest import registry_with
from features.pim.tools import tach_danh_sach, tach_thu
from ui.panels import mail_blocks, mail_list_blocks
from utils.events import AssistantBus

from test_mcp_bridge import FakeMCP, _tool


_THU_THAT = ("Từ: Phòng Đào tạo <daotao@hcmut.edu.vn>\n"
             "Tiêu đề: Đăng ký tốt nghiệp đợt 3\n\n"
             "Sinh viên nộp hồ sơ trước 17h ngày 30/09.")


# --------------------------- tách thư --------------------------- #

def test_tach_dung_dinh_dang_cua_gws_gmail_read():
    thu = tach_thu(_THU_THAT)
    assert thu["tu"] == "Phòng Đào tạo <daotao@hcmut.edu.vn>"
    assert thu["tieu_de"] == "Đăng ký tốt nghiệp đợt 3"
    assert thu["than"].startswith("Sinh viên nộp hồ sơ")


def test_khong_khop_dinh_dang_thi_don_het_vao_than():
    """Hiện thừa vài dòng đầu vẫn hơn hiện panel trống khi người dùng vừa bảo 'cho xem'."""
    thu = tach_thu("một chuỗi lạ không có dòng trống")
    assert thu["than"] == "một chuỗi lạ không có dòng trống"
    assert thu["tu"] == "" and thu["tieu_de"] == ""


def test_tach_thu_rong_khong_no():
    assert tach_thu("")["than"] == ""
    assert tach_thu(None)["than"] == ""


def test_dau_hai_cham_trong_tieu_de_khong_lam_hong_viec_tach():
    thu = tach_thu("Từ: a@b.com\nTiêu đề: Nhắc: hạn 30/09\n\nnội dung")
    assert thu["tieu_de"] == "Nhắc: hạn 30/09"


# --------------------------- khối hiển thị --------------------------- #

def test_tieu_de_len_header_con_lai_thanh_dong():
    khoi = mail_blocks({"tu": "A <a@b.com>", "tieu_de": "Tốt nghiệp",
                        "ngay": "25/08 09:12", "than": "nội dung"})
    assert khoi[0] == ("header", "Tốt nghiệp")
    assert ("field", "Từ", "A <a@b.com>") in khoi
    assert ("field", "Nhận lúc", "25/08 09:12") in khoi
    assert ("body", "nội dung") in khoi


def test_panel_thu_KHONG_CO_NUT_NAO():
    """Không hành động nào được phát sinh từ màn hình đang hiện nội dung ta không kiểm
    soát. Panel nháp có nút GỬI/HUỶ vì đó là thư TA sắp gửi; thư đến thì không."""
    khoi = mail_blocks({"tieu_de": "x", "than": "y"})
    assert not [b for b in khoi if b[0] == "buttons"]


def test_thieu_truong_thi_bo_dong_do_di():
    khoi = mail_blocks({"tieu_de": "Chỉ có tiêu đề", "than": "z"})
    assert not [b for b in khoi if b[0] == "field"]


def test_thu_khong_co_van_ban_thuan_thi_noi_thang():
    """Khung trống trông như đang tải dở."""
    khoi = mail_blocks({"tieu_de": "Thư ảnh", "than": "   "})
    assert [b for b in khoi if b[0] == "body"][0][1].startswith("(thư này không có")


def test_rong_thi_khong_co_khoi_nao():
    assert mail_blocks({}) == [] and mail_blocks(None) == []


# --------------------------- tool show_email --------------------------- #

_DANH_SACH = ("Tìm thấy 2 email khớp 'from:hcmut.edu.vn':\n"
              "- [m1] Phòng Đào tạo <daotao@hcmut.edu.vn> — Đăng ký tốt nghiệp đợt 3 (25/08 09:12)\n"
              "- [m2] Thư viện <lib@hcmut.edu.vn> — Nhắc trả sách (24/08 15:03)")


def _reg_va_bus(noi_dung=_THU_THAT, danh_sach=_DANH_SACH, thieu=None):
    """Registry có đủ hai tool MCP mà `show_email*` cần. `thieu` = bỏ bớt một tool."""
    ten = [t for t in ("gws_gmail_read", "gws_gmail_search") if t != thieu]
    mcp = FakeMCP([_tool(t) for t in ten],
                  results={"gws_gmail_read": noi_dung, "gws_gmail_search": danh_sach})
    bus = AssistantBus()
    return registry_with(mcp=mcp, bus=bus), mcp, bus


def test_noi_dung_thu_KHONG_lot_vao_ket_qua_tra_ve_LLM():
    """Tính chất trung tâm. Vỡ cái này là mất sạch lý do panel tồn tại."""
    reg, _, _ = _reg_va_bus()
    out = reg.run("show_email", {"message_id": "m1"})
    assert "Sinh viên nộp hồ sơ" not in out
    assert "daotao@hcmut.edu.vn" not in out
    assert "Đăng ký tốt nghiệp" not in out          # cả tiêu đề cũng không
    assert out == "Đã hiện thư lên màn hình cho bạn xem."


def test_noi_dung_thu_di_thang_len_panel():
    reg, _, bus = _reg_va_bus()
    reg.run("show_email", {"message_id": "m1"})
    su_kien = [e for e in bus.drain() if getattr(e, "mail", None)]
    assert len(su_kien) == 1
    assert su_kien[0].mail["tieu_de"] == "Đăng ký tốt nghiệp đợt 3"
    assert "Sinh viên nộp hồ sơ" in su_kien[0].mail["than"]


def test_goi_dung_tool_MCP_voi_dung_ma_thu():
    reg, mcp, _ = _reg_va_bus()
    reg.run("show_email", {"message_id": "abc123"})
    assert mcp.calls == [("gws_gmail_read", {"message_id": "abc123"})]


def test_MCP_hong_thi_NEM_va_KHONG_mo_panel():
    """Phải NÉM chứ không nuốt thành chuỗi thân thiện: nuốt là `_run_tool` xem lượt này
    thành công và nhật ký ghi "xong" cho một lượt hỏng. Model vẫn tự soạn lời xin lỗi tử
    tế từ `ToolResult(is_error=True)` — không mất gì về phía người dùng."""
    reg, mcp, bus = _reg_va_bus()
    mcp.call_tool = MagicMock(side_effect=RuntimeError("mất mạng"))
    with pytest.raises(RuntimeError):
        reg.run("show_email", {"message_id": "m1"})
    assert not [e for e in bus.drain() if getattr(e, "mail", None)]


def test_tim_thu_hong_cung_NEM():
    reg, mcp, bus = _reg_va_bus()
    mcp.call_tool = MagicMock(side_effect=RuntimeError("OAuth hết hạn"))
    with pytest.raises(RuntimeError):
        reg.run("show_email_list", {"q": "x"})
    assert not [e for e in bus.drain() if getattr(e, "mails", None)]


def test_doc_thang_khong_can_xac_nhan():
    """Chỉ ĐỌC, không đổi gì -> cổng duyệt không được chặn (chặn thì hỏng trải nghiệm)."""
    reg, _, _ = _reg_va_bus()
    assert reg.gate("show_email", {"message_id": "m1"}) is None


# --------------------------- danh sách kết quả --------------------------- #

def test_tach_danh_sach_bo_qua_dong_dan_nhap():
    """Dòng "Tìm thấy N email..." không phải một lá thư."""
    rows = tach_danh_sach(_DANH_SACH)
    assert [r["id"] for r in rows] == ["m1", "m2"]
    assert rows[0]["tu"] == "Phòng Đào tạo <daotao@hcmut.edu.vn>"
    assert rows[0]["tieu_de"] == "Đăng ký tốt nghiệp đợt 3"
    assert rows[0]["ngay"] == "25/08 09:12"


def test_tach_danh_sach_thu_khong_co_ngay():
    rows = tach_danh_sach("- [m9] A <a@b.com> — Không có ngày")
    assert rows[0]["ngay"] == "" and rows[0]["tieu_de"] == "Không có ngày"


def test_tach_danh_sach_rong_va_rac():
    assert tach_danh_sach("") == []
    assert tach_danh_sach("Không tìm thấy email nào khớp 'x'.") == []


def test_danh_sach_moi_thu_mot_the_bam_duoc():
    khoi = mail_list_blocks(tach_danh_sach(_DANH_SACH), q="from:hcmut.edu.vn")
    the = [b for b in khoi if b[0] == "card"]
    assert len(the) == 2
    assert the[0][1]["title"].startswith("1. Đăng ký tốt nghiệp")
    assert the[0][2] == 1 and the[1][2] == 2      # khoá bấm = SỐ THỨ TỰ
    assert "25/08 09:12" in the[0][1]["meta"]


def test_panel_danh_sach_cung_KHONG_CO_NUT_NAO():
    khoi = mail_list_blocks(tach_danh_sach(_DANH_SACH))
    assert not [b for b in khoi if b[0] == "buttons"]


def test_danh_sach_rong_thi_khong_co_khoi_nao():
    assert mail_list_blocks([]) == [] and mail_list_blocks(None) == []


def test_tim_xong_thi_day_danh_sach_len_panel():
    reg, _, bus = _reg_va_bus()
    out = reg.run("show_email_list", {"q": "from:hcmut.edu.vn"})
    su_kien = [e for e in bus.drain() if getattr(e, "mails", None)]
    assert len(su_kien) == 1
    assert [r["id"] for r in su_kien[0].mails["rows"]] == ["m1", "m2"]
    assert su_kien[0].mails["q"] == "from:hcmut.edu.vn"
    assert "2 thư" in out


def test_tieu_de_thu_KHONG_lot_vao_ket_qua_tra_ve_LLM():
    """Cùng lý do với `show_email`: tiêu đề do người ngoài soạn. Nó nằm trên panel."""
    reg, _, _ = _reg_va_bus()
    out = reg.run("show_email_list", {"q": "from:hcmut.edu.vn"})
    assert "Đăng ký tốt nghiệp" not in out and "Nhắc trả sách" not in out


def test_mo_thu_theo_SO_THU_TU_sau_khi_da_hien_danh_sach():
    """Bấm thẻ trên panel và nói 'mở thư thứ hai' đi CHUNG một đường."""
    reg, mcp, _ = _reg_va_bus()
    reg.run("show_email_list", {"q": "x"})
    reg.run("show_email", {"index": 2})
    assert ("gws_gmail_read", {"message_id": "m2"}) in mcp.calls


def test_so_thu_tu_ngoai_khoang_thi_noi_ro():
    reg, _, _ = _reg_va_bus()
    reg.run("show_email_list", {"q": "x"})
    assert "chỉ có 2 thư" in reg.run("show_email", {"index": 9}).lower()


def test_chua_tim_ma_doi_mo_theo_so_thi_nhac_tim_truoc():
    reg, _, _ = _reg_va_bus()
    assert "tìm thư trước" in reg.run("show_email", {"index": 1}).lower()


def test_khong_cho_ma_lan_so_thu_tu():
    reg, _, _ = _reg_va_bus()
    assert "mã thư" in reg.run("show_email", {}).lower()


def test_tieu_chi_rong_thi_khong_goi_MCP():
    reg, mcp, _ = _reg_va_bus()
    assert "tiêu chí" in reg.run("show_email_list", {"q": "  "}).lower()
    assert mcp.calls == []


def test_tim_khong_ra_thi_noi_thang_va_van_don_panel():
    """Panel phải được dọn, nếu không danh sách CŨ còn nằm đó trông như kết quả mới."""
    reg, _, bus = _reg_va_bus(danh_sach="Không tìm thấy email nào khớp 'x'.")
    out = reg.run("show_email_list", {"q": "x"})
    assert "không tìm thấy" in out.lower()
    su_kien = [e for e in bus.drain() if getattr(e, "mails", None)]
    assert su_kien[0].mails["rows"] == []


# --------------------------- điều kiện đăng ký --------------------------- #

def test_khong_co_man_hinh_thi_khong_co_tool():
    """Chạy không avatar (chỉ terminal) -> hiện lên panel là vô nghĩa."""
    reg = registry_with(mcp=FakeMCP([_tool("gws_gmail_read"), _tool("gws_gmail_search")]))
    assert not reg.has("show_email") and not reg.has("show_email_list")


def test_server_MCP_thieu_mot_tool_thi_khong_dang_ky_gi():
    """Đổi sang server MCP khác -> tool tự vắng mặt, thay vì đăng ký rồi nổ lúc chạy."""
    for thieu in ("gws_gmail_read", "gws_gmail_search"):
        reg, _, _ = _reg_va_bus(thieu=thieu)
        assert not reg.has("show_email"), thieu
        assert not reg.has("show_email_list"), thieu


def test_khong_co_MCP_thi_khong_co_tool():
    assert not registry_with(bus=AssistantBus()).has("show_email")
