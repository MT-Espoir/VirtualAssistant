"""Test ContactStore (store thuần + I/O) và bộ tool danh bạ (save/find/list/remove)."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.contacts import ContactStore

from conftest import registry_with


def _store():
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd); os.unlink(path)
    return ContactStore(path=path), path


def _rm(path):
    if os.path.exists(path):
        os.remove(path)


# --------------------------- ContactStore --------------------------- #

def test_add_and_list():
    s, path = _store()
    s.add("Sếp", "boss@x.com"); s.add("Mẹ", "mom@x.com")
    assert [(c["name"], c["email"]) for c in s.list()] == \
        [("Sếp", "boss@x.com"), ("Mẹ", "mom@x.com")]
    _rm(path)


def test_add_rejects_missing_field():
    s, path = _store()
    assert s.add("", "a@x.com") is None
    assert s.add("Tên", "") is None
    assert s.list() == []
    _rm(path)


def test_add_same_name_updates_email():
    s, path = _store()
    s.add("Sếp", "old@x.com")
    s.add("sep", "new@x.com")          # bỏ dấu + thường -> cùng người
    assert len(s.list()) == 1
    assert s.find("sếp")[0]["email"] == "new@x.com"
    _rm(path)


def test_find_accent_insensitive_substring():
    s, path = _store()
    s.add("Nguyễn Văn A", "a@x.com")
    assert s.find("nguyen")[0]["email"] == "a@x.com"
    assert s.find("van a")[0]["name"] == "Nguyễn Văn A"
    assert s.find("khong-co") == []
    _rm(path)


def test_remove_by_id():
    s, path = _store()
    c = s.add("X", "x@x.com")
    assert s.remove(c["id"])["name"] == "X"
    assert s.list() == []
    assert s.remove("khongton") is None
    _rm(path)


def test_persist_across_instances():
    s, path = _store()
    s.add("Sếp", "boss@x.com")
    again = ContactStore(path=path)
    assert again.find("sếp")[0]["email"] == "boss@x.com"
    _rm(path)


# --------------------------- Tool danh bạ --------------------------- #

def _registry_with_contacts():
    s, path = _store()
    reg = registry_with(contacts=s)
    return reg, s, path


def test_tools_registered():
    reg, _, path = _registry_with_contacts()
    for name in ("save_contact", "find_contact", "list_contacts", "remove_contact"):
        assert reg.has(name)
    assert reg.get("remove_contact").destructive is True
    _rm(path)


def test_find_tra_THAM_CHIEU_chu_khong_tra_dia_chi():
    """Email của NGƯỜI KHÁC là dữ liệu bên thứ ba — họ chưa từng đồng ý cho nó đi sang
    nhà cung cấp LLM. Model nhận tham chiếu; địa chỉ hiện hình ở tầng runtime."""
    reg, _, path = _registry_with_contacts()
    assert "Đã lưu" in reg.run("save_contact", {"name": "Sếp", "email": "boss@x.com"})
    out = reg.run("find_contact", {"name": "sếp"})
    assert "boss@x.com" not in out
    assert "@lienhe:Sếp" in out
    _rm(path)


def test_save_tool_rejects_missing():
    reg, _, path = _registry_with_contacts()
    assert "Cần" in reg.run("save_contact", {"name": "Sếp", "email": ""})
    _rm(path)


def test_find_tool_not_found():
    reg, _, path = _registry_with_contacts()
    assert "Không thấy" in reg.run("find_contact", {"name": "ai-do"})
    _rm(path)


def test_list_chi_tra_TEN_khong_tra_dia_chi():
    """"Danh bạ có ai" không đáng giá bằng việc đổ email của MỌI người quen vào ngữ cảnh."""
    reg, _, path = _registry_with_contacts()
    reg.run("save_contact", {"name": "X", "email": "x@x.com"})
    danh_sach = reg.run("list_contacts", {})
    assert "x@x.com" not in danh_sach and "X" in danh_sach
    # `remove_contact` là destructive -> registry chặn nếu không nói rõ đã được duyệt.
    # Test này kiểm HANDLER, không kiểm cổng duyệt (cổng có test riêng ở test_agent.py).
    assert "Đã xoá" in reg.run("remove_contact", {"name": "X"}, confirmed=True)
    assert "trống" in reg.run("list_contacts", {})
    _rm(path)


# --------------------------- giải tham chiếu ở tầng runtime --------------------------- #
#
# Model thấy `@lienhe:Sếp`; địa chỉ thật chỉ hiện hình ngay trước khi gọi tool gửi mail,
# và trên panel để người dùng kiểm bằng mắt. Đây là chỗ tham chiếu biến thành sự thật.

def test_giai_tham_chieu_thanh_dia_chi_that():
    from features.pim.tools import giai_lien_he
    from services.contacts import ContactStore
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "c.json")
    kho = ContactStore(path=path)
    kho.add("Sếp", "boss@x.com")
    assert giai_lien_he("@lienhe:Sếp", kho) == "boss@x.com"
    _rm(path)


def test_khong_phai_tham_chieu_thi_giu_nguyen():
    from features.pim.tools import giai_lien_he
    assert giai_lien_he("ai-do@x.com", None) == "ai-do@x.com"
    assert giai_lien_he(None, None) is None


def test_tra_khong_ra_thi_KHONG_doan_bua():
    """Hư theo chiều AN TOÀN: chuỗi tham chiếu không phải địa chỉ hợp lệ nên lệnh gửi
    hỏng rõ ràng, còn hơn đoán bừa rồi gửi nhầm người."""
    from features.pim.tools import giai_lien_he
    from services.contacts import ContactStore
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "c.json")
    assert giai_lien_he("@lienhe:KhongCoAi", ContactStore(path=path)) == "@lienhe:KhongCoAi"
    _rm(path)


def test_giai_ca_lo_tham_so():
    from features.pim.tools import giai_tham_chieu
    from services.contacts import ContactStore
    import tempfile, os
    path = os.path.join(tempfile.mkdtemp(), "c.json")
    kho = ContactStore(path=path)
    kho.add("Sếp", "boss@x.com")
    ra = giai_tham_chieu({"to": "@lienhe:Sếp", "subject": "Xin nghỉ"}, kho)
    assert ra == {"to": "boss@x.com", "subject": "Xin nghỉ"}
    _rm(path)
