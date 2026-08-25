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


def test_save_and_find_tool():
    reg, _, path = _registry_with_contacts()
    assert "Đã lưu" in reg.run("save_contact", {"name": "Sếp", "email": "boss@x.com"})
    out = reg.run("find_contact", {"name": "sếp"})
    assert "boss@x.com" in out
    _rm(path)


def test_save_tool_rejects_missing():
    reg, _, path = _registry_with_contacts()
    assert "Cần" in reg.run("save_contact", {"name": "Sếp", "email": ""})
    _rm(path)


def test_find_tool_not_found():
    reg, _, path = _registry_with_contacts()
    assert "Không thấy" in reg.run("find_contact", {"name": "ai-do"})
    _rm(path)


def test_list_and_remove_tool():
    reg, _, path = _registry_with_contacts()
    reg.run("save_contact", {"name": "X", "email": "x@x.com"})
    assert "x@x.com" in reg.run("list_contacts", {})
    assert "Đã xoá" in reg.run("remove_contact", {"name": "X"})
    assert "trống" in reg.run("list_contacts", {})
    _rm(path)
