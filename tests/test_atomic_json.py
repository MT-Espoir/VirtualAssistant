"""
Ghi JSON nguyên tử — tính chất: KHÔNG BAO GIỜ có trạng thái nửa chừng trên đĩa.

Lỗi được vá: mọi `_save()` trước đây làm `open(path, "w")`, tức CẮT TRẮNG file rồi mới
ghi. Chết giữa hai bước đó (bấm Esc, tắt cửa sổ avatar, mất điện) là mất trắng nội dung
cũ — với `profile.json`, đó là trí nhớ dài hạn tích luỹ nhiều tháng và không có bản sao.

Test quan trọng nhất ở đây là `test_ghi_hong_giua_chung_khong_lam_mat_ban_cu`: nó mô tả
đúng tình huống đã có thể xảy ra, và trước bản vá thì nó đỏ.
"""

import io
import json
import os

try:
    import pytest
except ImportError:
    pytest = None

from utils import atomic_json
from utils.atomic_json import write_json


def _doc(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


# --------------------------- đường thường --------------------------- #

def test_ghi_roi_doc_lai_dung_noi_dung(tmp_path):
    p = tmp_path / "kho.json"
    write_json(str(p), {"ten": "Minh", "ghi_chu": ["thích cà phê sữa"]})
    assert _doc(p) == {"ten": "Minh", "ghi_chu": ["thích cà phê sữa"]}


def test_giu_nguyen_tieng_viet_co_dau(tmp_path):
    """`ensure_ascii=False` — nhãn thói quen rồi sẽ được TTS ĐỌC LÊN, mất dấu là đọc sai."""
    p = tmp_path / "kho.json"
    write_json(str(p), {"nhan": "nghe 'Chúng ta của hiện tại'"})
    assert "Chúng ta của hiện tại" in io.open(p, encoding="utf-8").read()


def test_tu_tao_thu_muc_cha(tmp_path):
    p = tmp_path / "chua" / "co" / "kho.json"
    write_json(str(p), {"a": 1})
    assert _doc(p) == {"a": 1}


def test_khong_de_lai_file_tam_khi_thanh_cong(tmp_path):
    p = tmp_path / "kho.json"
    write_json(str(p), {"a": 1})
    assert os.listdir(tmp_path) == ["kho.json"]


def test_indent_None_cho_ban_gon(tmp_path):
    """`claim_cache` ghi bản gọn — không ai đọc file cache bằng mắt."""
    p = tmp_path / "cache.json"
    write_json(str(p), {"a": [1, 2]}, indent=None)
    assert "\n" not in io.open(p, encoding="utf-8").read()


def test_xuong_dong_LF_khong_phai_CRLF(tmp_path):
    """Ép `newline='\\n'`: trên Windows chế độ text mặc định đổi \\n thành \\r\\n, làm file
    phình và khác byte giữa hai máy mà nội dung y hệt."""
    p = tmp_path / "kho.json"
    write_json(str(p), {"a": 1, "b": 2})
    assert b"\r\n" not in io.open(p, "rb").read()


# --------------------------- tính chất nguyên tử --------------------------- #

def test_ghi_hong_giua_chung_khong_lam_mat_ban_cu(tmp_path, monkeypatch):
    """LỖI ĐÃ VÁ: ghi thẳng thì bản cũ mất trắng; ghi qua file tạm thì còn nguyên."""
    p = tmp_path / "profile.json"
    write_json(str(p), {"ten": "Minh", "ghi_chu": ["nhiều tháng tích luỹ"]})

    def dump_hong(data, f, **kwargs):
        f.write('{"mot_nu')                       # ghi được một nửa...
        raise OSError("đĩa đầy")                  # ...rồi chết

    monkeypatch.setattr(atomic_json.json, "dump", dump_hong)
    with pytest.raises(OSError):
        write_json(str(p), {"ten": "Minh", "ghi_chu": ["thêm điều mới"]})

    assert _doc(p) == {"ten": "Minh", "ghi_chu": ["nhiều tháng tích luỹ"]}


def test_ghi_de_len_file_da_co(tmp_path):
    """`os.replace` phải đè được lên file đang tồn tại (trên Windows `os.rename` thì không)."""
    p = tmp_path / "kho.json"
    write_json(str(p), {"lan": 1})
    write_json(str(p), {"lan": 2})
    assert _doc(p) == {"lan": 2}


def test_file_tam_nam_cung_thu_muc_voi_dich(tmp_path, monkeypatch):
    """`os.replace` chỉ nguyên tử khi hai đường dẫn CÙNG Ổ ĐĨA — nên file tạm không được
    nằm ở thư mục tạm của hệ thống."""
    thay = {}
    that = atomic_json.os.replace

    def ghi_lai(src, dst):
        thay["src"], thay["dst"] = src, dst
        return that(src, dst)

    monkeypatch.setattr(atomic_json.os, "replace", ghi_lai)
    p = tmp_path / "sau" / "kho.json"
    write_json(str(p), {"a": 1})
    assert os.path.dirname(thay["src"]) == os.path.dirname(thay["dst"])


def test_nem_OSError_de_noi_goi_giu_cau_bao_loi_rieng(tmp_path):
    """Mỗi kho có câu báo lỗi riêng ("không lưu được sổ danh bạ" vs "...hồ sơ") nên helper
    phải NÉM chứ không nuốt."""
    ke_chan = tmp_path / "la_mot_file"
    ke_chan.write_text("x", encoding="utf-8")
    with pytest.raises(OSError):
        write_json(str(ke_chan / "kho.json"), {"a": 1})


# --------------------------- các kho thật đã dùng helper --------------------------- #

def test_moi_kho_that_deu_ghi_qua_helper():
    """Chặn hồi quy: thêm kho mới mà quên dùng helper là lại có chỗ mất dữ liệu.

    Bắt theo dấu vết `open(..., "w")` trong các module kho — thứ helper sinh ra để thay.
    """
    import re
    from pathlib import Path

    goc = Path(__file__).resolve().parents[1] / "src"
    kho = ["agent/persona.py", "memory/habits.py", "memory/profile.py",
           "memory/short_term.py", "research/claim_cache.py", "services/contacts.py",
           "services/location.py", "services/routines.py", "services/scheduler.py",
           "services/tasks.py"]
    ghi_thang = re.compile(r"""open\([^)]*["']w["']""")
    vi_pham = [f for f in kho
               if ghi_thang.search((goc / f).read_text(encoding="utf-8"))]
    assert not vi_pham, f"còn ghi thẳng (cắt trắng file) thay vì write_json: {vi_pham}"
