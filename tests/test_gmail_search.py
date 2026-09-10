"""
Tìm email theo tiêu chí (`gws_gmail_search`) + liệt kê CHỈ metadata.

Hai tính chất phải giữ:
  1. Tìm được thư theo người gửi / nội dung / thời gian — trước đây chỉ liệt kê được thư
     chưa đọc, nên "mail của phòng đào tạo" là câu không trả lời nổi.
  2. Danh sách KHÔNG BAO GIỜ chứa thân thư. Vừa để khỏi đổ cả mớ vào ngữ cảnh LLM (và đọc
     lên bằng giọng), vừa vì thân thư là nội dung do người khác soạn — kéo vào hội thoại
     chỉ để liệt kê là mở rộng bề mặt prompt injection không cần thiết.

Server MCP cần `fastmcp` + thư viện Google; môi trường không có thì BỎ QUA cả file thay vì
làm đỏ suite (xem `docs/` — bộ chạy chuẩn là ml_env).
"""

import os
import sys

try:
    import pytest
except ImportError:
    pytest = None

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "mcp_servers"))

gp = pytest.importorskip("google_personal",
                         reason="cần fastmcp + google-api-python-client (dùng ml_env)")


# --------------------------- Gmail API giả --------------------------- #

class _Exec:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return self._data


class _Messages:
    def __init__(self, thu, ghi):
        self._thu = thu               # {id: message dict}
        self.ghi = ghi                # ghi lại tham số đã gọi, để test soi

    def list(self, **kw):
        self.ghi["list"] = kw
        return _Exec({"messages": [{"id": i} for i in self._thu]})

    def get(self, **kw):
        self.ghi.setdefault("get", []).append(kw)
        return _Exec(self._thu[kw["id"]])


class _Svc:
    def __init__(self, thu):
        self.ghi = {}
        self._m = _Messages(thu, self.ghi)

    def users(self):
        return self

    def messages(self):
        return self._m


def _thu(id_, tu, tieu_de, ngay="Mon, 25 Aug 2026 09:12:33 +0700", than="THÂN THƯ BÍ MẬT"):
    return {"payload": {"headers": [{"name": "From", "value": tu},
                                    {"name": "Subject", "value": tieu_de},
                                    {"name": "Date", "value": ngay}],
                        "body": {"data": than}}}


_MOT_THU = {"m1": _thu("m1", "Phòng Đào tạo <daotao@hcmut.edu.vn>", "Đăng ký tốt nghiệp đợt 3")}


# --------------------------- mốc thời gian --------------------------- #

def test_ngay_rut_gon_cho_de_doc():
    """Chuỗi RFC 2822 gốc vừa dài vừa không đọc lên được bằng giọng."""
    assert gp._ngay_goc(_thu("m", "a", "b")) == "25/08 09:12"


def test_ngay_hong_hoac_thieu_thi_bo_qua_chu_khong_no():
    assert gp._ngay_goc(_thu("m", "a", "b", ngay="hôm nào đó")) == ""
    assert gp._ngay_goc({"payload": {"headers": []}}) == ""


# --------------------------- liệt kê --------------------------- #

def test_truyen_dung_tieu_chi_xuong_gmail():
    svc = _Svc(_MOT_THU)
    gp._liet_ke(svc, 'from:hcmut.edu.vn "tốt nghiệp"', 10)
    assert svc.ghi["list"]["q"] == 'from:hcmut.edu.vn "tốt nghiệp"'


def test_chi_xin_METADATA_khong_bao_gio_xin_than_thu():
    """Tính chất số 2 của file này, canh ở đúng chỗ nó có thể vỡ."""
    svc = _Svc(_MOT_THU)
    gp._liet_ke(svc, "is:unread", 10)
    for goi in svc.ghi["get"]:
        assert goi["format"] == "metadata"
        assert "Date" in goi["metadataHeaders"]


def test_chan_tran_so_luong():
    """Gmail API vẫn nhận maxResults lớn, nhưng 100 thư đổ vào prompt là một lượt hỏng."""
    svc = _Svc(_MOT_THU)
    gp._liet_ke(svc, "is:unread", 500)
    assert svc.ghi["list"]["maxResults"] == 25
    gp._liet_ke(svc, "is:unread", 0)
    assert svc.ghi["list"]["maxResults"] == 1


def test_khong_co_thu_thi_tra_danh_sach_rong():
    assert gp._liet_ke(_Svc({}), "is:unread", 10) == []


def test_ke_thu_moi_thu_mot_dong_co_ma_va_ngay():
    dong = gp._ke_thu([{"id": "m1", "tu": "Phòng Đào tạo", "tieu_de": "Tốt nghiệp",
                        "ngay": "25/08 09:12"}])
    assert dong == "- [m1] Phòng Đào tạo — Tốt nghiệp (25/08 09:12)"


def test_ke_thu_thieu_ngay_thi_khong_de_ngoac_rong():
    dong = gp._ke_thu([{"id": "m1", "tu": "A", "tieu_de": "B", "ngay": ""}])
    assert dong == "- [m1] A — B"


# --------------------------- tool tìm kiếm --------------------------- #

def _dung_svc_gia(monkeypatch, thu):
    svc = _Svc(thu)
    monkeypatch.setattr(gp, "_gmail", lambda *a, **k: svc)
    return svc


def test_tim_thay_thi_liet_ke_tieu_de_KHONG_kem_than_thu(monkeypatch):
    _dung_svc_gia(monkeypatch, _MOT_THU)
    out = gp.gws_gmail_search(q="from:hcmut.edu.vn")
    assert "Đăng ký tốt nghiệp đợt 3" in out and "[m1]" in out
    assert "THÂN THƯ BÍ MẬT" not in out          # <- tính chất số 2


def test_khong_tim_thay_thi_noi_ro_da_tim_gi(monkeypatch):
    """Nhắc lại tiêu chí để người dùng biết nên sửa từ khoá, thay vì tưởng không có thư."""
    _dung_svc_gia(monkeypatch, {})
    assert "from:khongcoai" in gp.gws_gmail_search(q="from:khongcoai")


def test_tieu_chi_rong_thi_khong_goi_API(monkeypatch):
    """q rỗng mà cứ gọi là đổ NGUYÊN hộp thư ra — vừa vô nghĩa vừa tốn."""
    svc = _dung_svc_gia(monkeypatch, _MOT_THU)
    out = gp.gws_gmail_search(q="   ")
    assert "Cần cho biết tiêu chí" in out
    assert svc.ghi == {}                        # chưa hề chạm tới Gmail


def test_unread_van_chay_nhu_cu_va_dung_is_unread(monkeypatch):
    svc = _dung_svc_gia(monkeypatch, _MOT_THU)
    out = gp.gws_gmail_unread()
    assert svc.ghi["list"]["q"] == "is:unread"
    assert "1 email chưa đọc" in out and "THÂN THƯ BÍ MẬT" not in out


def test_unread_rong_thi_noi_khong_co(monkeypatch):
    _dung_svc_gia(monkeypatch, {})
    assert gp.gws_gmail_unread() == "Không có email chưa đọc."
