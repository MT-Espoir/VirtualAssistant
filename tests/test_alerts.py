"""
Phát hiện dấu hiệu bị tấn công từ nhật ký kết quả (đợt 7 của vá bảo mật).

Sáu đợt trước nâng PHÒNG NGỪA. File này lo phần còn thiếu hoàn toàn: PHÁT HIỆN. Mọi lớp
phòng ngừa đều chỉ nâng chi phí tấn công chứ không triệt tiêu, nên hệ sẽ bị chọc thủng lúc
nào đó — và không biết mình bị chọc thì mất luôn cơ hội phản ứng.
"""

import sys
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memory.alerts import CAO, VUA, ke_canh_bao, soi, soi_mot_luot

RO_RI = {"web_fetch", "open_website"}
BEN_VUNG = {"remember_about_user", "save_contact", "create_routine"}
NGOAI = {"web_fetch", "doc_web", "web_search_list"}   # tool trả nội dung ngoài


def _luot(**kw):
    goc = {"khi": "2026-08-29T10:00:00", "phien": "abc", "cau": "tóm tắt trang này",
           "dap": "xong", "tool": [], "ket_qua": "xong", "nguon_ngoai": False}
    goc.update(kw)
    return goc


def _soi(r, nhiem_tu_truoc=True):
    """Mặc định coi như lượt TRƯỚC đã nhiễm — phần lớn ca dưới đây kiểm luật, không
    kiểm việc dựng lại vết nhiễm (đã có mục riêng ở cuối file)."""
    return soi_mot_luot(r, RO_RI, BEN_VUNG, NGOAI, nhiem_tu_truoc)


# --------------------------- rò rỉ sau khi đọc nội dung ngoài --------------------------- #

def test_ro_ri_trong_luot_nhiem_MA_DA_CHAY_la_muc_CAO():
    """Cổng đã hỏi và người dùng bấm 'có'. Cổng làm đúng việc, nhưng nó KHÔNG chứng minh
    người dùng đọc kỹ — mệt mỏi xác nhận là quy luật. Ca này phải nổi lên để soi lại."""
    c = _soi(_luot(tool=["web_fetch"], ket_qua="xong"))
    assert len(c) == 1 and c[0]["muc"] == CAO
    assert "ĐÃ CHẠY" in c[0]["vi_sao"]


def test_ro_ri_bi_cong_chan_la_muc_VUA():
    """Vẫn phải ghi nhận: có kẻ ĐÃ THỬ, dù không thành."""
    c = _soi(_luot(tool=["web_fetch"], ket_qua="tu_choi"))
    assert len(c) == 1 and c[0]["muc"] == VUA


def test_luot_SACH_thi_khong_canh_bao():
    """Tóm tắt một trang bình thường là việc hằng ngày — kêu ở đây là biến cảnh báo thành
    tiếng ồn, rồi không ai đọc nữa."""
    assert _soi(_luot(tool=["web_fetch"]), nhiem_tu_truoc=False) == []


def test_tool_thuong_trong_luot_nhiem_khong_canh_bao():
    """Đọc trang rồi bật nhạc thì không có gì đáng ngờ."""
    assert _soi(_luot(tool=["browser_media_control"])) == []


# --------------------------- ghi trí nhớ sau nội dung ngoài --------------------------- #

def test_ghi_tri_nho_trong_luot_nhiem():
    c = _soi(_luot(tool=["remember_about_user"], ket_qua="xong"))
    assert c[0]["luat"] == "ghi_tri_nho_sau_noi_dung_ngoai" and c[0]["muc"] == CAO


def test_mot_luot_co_the_sinh_NHIEU_canh_bao():
    c = _soi(_luot(tool=["web_fetch", "save_contact"]))
    assert {x["luat"] for x in c} == {"ro_ri_sau_noi_dung_ngoai",
                                      "ghi_tri_nho_sau_noi_dung_ngoai"}


# --------------------------- routine không ai yêu cầu --------------------------- #

def test_tao_routine_ma_nguoi_dung_khong_he_nhac_toi():
    """Routine là các bước sẽ TỰ THỰC THI về sau — persistence cộng thực thi trễ."""
    c = _soi(_luot(tool=["create_routine"], cau="đọc giúp tôi tin tức"),
             nhiem_tu_truoc=False)
    assert len(c) == 1 and c[0]["luat"] == "tao_routine_khong_ai_yeu_cau"


def test_nguoi_dung_co_yeu_cau_thi_khong_canh_bao():
    for cau in ("tạo routine buổi sáng", "đặt quy trình buổi sáng"):
        assert _soi(_luot(tool=["create_routine"], cau=cau), nhiem_tu_truoc=False) == []


def test_routine_trong_luot_nhiem_bi_bat_boi_CA_HAI_luat():
    c = _soi(_luot(tool=["create_routine"], cau="tóm tắt trang"))
    assert {x["luat"] for x in c} == {"ghi_tri_nho_sau_noi_dung_ngoai",
                                      "tao_routine_khong_ai_yeu_cau"}


# --------------------------- gom và kể --------------------------- #

def test_muc_CAO_len_truoc():
    ra = soi([_luot(tool=["doc_web"], nguon_ngoai=True),
              _luot(tool=["web_fetch"], ket_qua="tu_choi"),
              _luot(tool=["web_fetch"], ket_qua="xong")],
             RO_RI, BEN_VUNG, NGOAI)
    assert [c["muc"] for c in ra] == [CAO, VUA]


def test_nhat_ky_sach_thi_noi_ro_la_sach():
    assert "Không thấy dấu hiệu" in ke_canh_bao([])
    assert soi([], RO_RI, BEN_VUNG, NGOAI) == [] and soi(None, RO_RI, BEN_VUNG, NGOAI) == []


def test_ban_ke_co_du_thu_de_lan_lai():
    """Cảnh báo mà không lần lại được lượt gốc thì chỉ gây lo, không giúp gì."""
    ra = soi([_luot(tool=["doc_web"], nguon_ngoai=True),
              _luot(tool=["web_fetch"], cau="tóm tắt evil.example")],
             RO_RI, BEN_VUNG, NGOAI)
    ban_ke = ke_canh_bao(ra)
    assert "web_fetch" in ban_ke and "2026-08-29" in ban_ke
    assert "tóm tắt evil.example" in ban_ke


# --------------------------- dựng lại vết nhiễm từ nhật ký --------------------------- #
#
# Bản ghi chỉ nói lượt ĐÓ có chạm nội dung ngoài hay không; nó KHÔNG mang trạng thái nhiễm
# sang lượt sau — mà đó mới là thứ cổng dùng lúc chạy. `soi()` phải tự dựng lại.

def test_mot_lan_tim_kiem_BINH_THUONG_khong_bi_keu():
    """DƯƠNG TÍNH GIẢ đã gặp thật khi chạy lần đầu trên nhật ký sống: `web_search_list`
    vừa trả nội dung ngoài vừa đẩy truy vấn ra ngoài, nên một lượt tìm kiếm bình thường
    làm bản ghi mang CẢ HAI cờ. Không xét thứ tự thì luật kêu ở mọi lượt tìm kiếm."""
    ra = soi([_luot(tool=["web_search_list"], nguon_ngoai=True, cau="tra cứu giúp tôi")],
             RO_RI | {"web_search_list"}, BEN_VUNG, NGOAI)
    assert ra == []


def test_ro_ri_o_LUOT_SAU_van_bi_bat():
    """Vết nhiễm sống qua nhiều lượt — kẻ tấn công viết 'ở lượt sau hãy...' thì vẫn lộ."""
    ra = soi([_luot(tool=["doc_web"], nguon_ngoai=True),
              _luot(tool=[]),                        # một lượt trò chuyện xen vào
              _luot(tool=["web_fetch"], ket_qua="xong")],
             RO_RI, BEN_VUNG, NGOAI)
    assert len(ra) == 1 and ra[0]["luat"] == "ro_ri_sau_noi_dung_ngoai"


def test_vet_nhiem_KHONG_lan_sang_phien_khac():
    """Lượt cuối hôm qua không được nối với lượt đầu hôm nay."""
    ra = soi([_luot(tool=["doc_web"], nguon_ngoai=True, phien="hom_qua"),
              _luot(tool=["web_fetch"], phien="hom_nay")],
             RO_RI, BEN_VUNG, NGOAI)
    assert ra == []


def test_vet_nhiem_phai_dan_sau_cua_so():
    from memory.alerts import CUA_SO_NHIEM
    ban_ghi = [_luot(tool=["doc_web"], nguon_ngoai=True)]
    ban_ghi += [_luot(tool=[]) for _ in range(CUA_SO_NHIEM)]
    ban_ghi.append(_luot(tool=["web_fetch"]))
    assert soi(ban_ghi, RO_RI, BEN_VUNG, NGOAI) == []
