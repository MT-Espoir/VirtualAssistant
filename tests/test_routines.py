"""Test RoutineStore (store thuần + I/O) và bộ tool quản lý routine (create/list/delete)."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.routines import RoutineStore

from conftest import registry_with


def _tmp():
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd); os.unlink(path)
    return RoutineStore(path=path), path


# --------------------------- RoutineStore --------------------------- #

def test_create_and_get_accent_insensitive():
    s, path = _tmp()
    try:
        s.create("Buổi Sáng", ["mở chrome", "đọc thời tiết"])
        r = s.get("buoi sang")                       # bỏ dấu + thường vẫn khớp
        assert r is not None and r["steps"] == ["mở chrome", "đọc thời tiết"]
    finally:
        if os.path.exists(path): os.unlink(path)


def test_create_rejects_empty_name_or_steps():
    s, path = _tmp()
    try:
        assert s.create("", ["x"]) is None
        assert s.create("x", []) is None
        assert s.create("x", ["  ", ""]) is None      # step toàn rỗng -> loại hết -> None
    finally:
        if os.path.exists(path): os.unlink(path)


def test_create_overwrites_and_flags_replaced():
    s, path = _tmp()
    try:
        assert s.create("sáng", ["a"])["replaced"] is False
        r2 = s.create("sáng", ["a", "b"])            # trùng tên -> ghi đè
        assert r2["replaced"] is True and len(s.get("sáng")["steps"]) == 2
    finally:
        if os.path.exists(path): os.unlink(path)


def test_delete_and_list():
    s, path = _tmp()
    try:
        s.create("sáng", ["a"]); s.create("tối", ["b"])
        assert {r["name"] for r in s.list()} == {"sáng", "tối"}
        assert s.delete("sáng") is True and s.delete("sáng") is False
        assert {r["name"] for r in s.list()} == {"tối"}
    finally:
        if os.path.exists(path): os.unlink(path)


def test_roundtrip_and_degrade():
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd); os.unlink(path)
    try:
        RoutineStore(path=path).create("sáng", ["mở chrome"])
        assert RoutineStore(path=path).get("sáng")["steps"] == ["mở chrome"]
        with open(path, "w", encoding="utf-8") as f:
            f.write("hỏng")
        assert RoutineStore(path=path).list() == []   # degrade an toàn
    finally:
        if os.path.exists(path): os.unlink(path)


# --------------------------- Tool routine --------------------------- #

def _reg(store):
    return registry_with(routines=store)


def test_tool_create_and_list():
    s, path = _tmp()
    try:
        reg = _reg(s)
        out = reg.run("create_routine", {"name": "buổi sáng",
                                         "steps": ["mở chrome", "đọc thời tiết"]})
        assert "tạo" in out and "2 bước" in out
        assert "buổi sáng" in reg.run("list_routines", {})
    finally:
        if os.path.exists(path): os.unlink(path)


def test_tool_create_rejects_no_steps():
    s, path = _tmp()
    try:
        assert "ít nhất một bước" in _reg(s).run("create_routine", {"name": "x", "steps": []})
    finally:
        if os.path.exists(path): os.unlink(path)


def test_delete_routine_is_destructive():
    s, path = _tmp()
    try:
        reg = _reg(s)
        assert reg.get("delete_routine").destructive is True
        assert "xoá routine" in reg.get("delete_routine").confirm_message(name="buổi sáng")
    finally:
        if os.path.exists(path): os.unlink(path)
