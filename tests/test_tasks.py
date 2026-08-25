"""Test TaskStore (store thuần + I/O) và bộ tool việc cần làm (add/list/complete/remove)."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from services.tasks import TaskStore

from conftest import registry_with


def _store(tmp=True):
    if not tmp:
        return TaskStore(path="__none__.json")
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd); os.unlink(path)
    return TaskStore(path=path), path


# --------------------------- TaskStore --------------------------- #

def test_add_and_list_only_undone():
    s = TaskStore(path="__mem__.json")  # sẽ không tồn tại -> rỗng; ta không save thật ở test này
    s.path = os.path.join(tempfile.gettempdir(), "t_add.json")
    if os.path.exists(s.path): os.remove(s.path)
    s.add("mua sữa"); s.add("nộp báo cáo")
    assert [t["text"] for t in s.list()] == ["mua sữa", "nộp báo cáo"]
    os.remove(s.path)


def test_add_rejects_empty():
    s = TaskStore(path=os.path.join(tempfile.gettempdir(), "t_empty.json"))
    if os.path.exists(s.path): os.remove(s.path)
    assert s.add("   ") is None and s.list() == []
    if os.path.exists(s.path): os.remove(s.path)


def test_complete_hides_from_default_list():
    s = TaskStore(path=os.path.join(tempfile.gettempdir(), "t_comp.json"))
    if os.path.exists(s.path): os.remove(s.path)
    t = s.add("mua sữa"); s.complete(t["id"])
    assert s.list() == []                              # mặc định ẩn việc xong
    assert len(s.list(include_done=True)) == 1
    os.remove(s.path)


def test_find_by_keyword_accent_insensitive_and_id():
    s = TaskStore(path=os.path.join(tempfile.gettempdir(), "t_find.json"))
    if os.path.exists(s.path): os.remove(s.path)
    t = s.add("Nộp báo cáo tuần")
    assert s.find("bao cao")[0]["id"] == t["id"]       # bỏ dấu vẫn khớp
    assert s.find(t["id"])[0]["id"] == t["id"]         # khớp theo id
    assert s.find("không có") == []
    os.remove(s.path)


def test_remove_by_id():
    s = TaskStore(path=os.path.join(tempfile.gettempdir(), "t_rm.json"))
    if os.path.exists(s.path): os.remove(s.path)
    t = s.add("việc x")
    assert s.remove(t["id"])["text"] == "việc x"
    assert s.remove(t["id"]) is None and s.list() == []
    os.remove(s.path)


def test_roundtrip_persists():
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd); os.unlink(path)
    try:
        TaskStore(path=path).add("mua sữa")
        assert [t["text"] for t in TaskStore(path=path).list()] == ["mua sữa"]
    finally:
        if os.path.exists(path): os.unlink(path)


def test_corrupt_file_degrades():
    fd, path = tempfile.mkstemp(suffix=".json"); os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ hỏng")
        assert TaskStore(path=path).list() == []        # không ném lỗi
    finally:
        os.unlink(path)


# --------------------------- Tool việc cần làm --------------------------- #

def _reg(store):
    return registry_with(tasks=store)


def test_tool_add_and_list():
    s, path = _store()
    try:
        reg = _reg(s)
        assert "mua sữa" in reg.run("add_task", {"text": "mua sữa"})
        out = reg.run("list_tasks", {})
        assert "mua sữa" in out and "1 việc" in out
    finally:
        if os.path.exists(path): os.unlink(path)


def test_tool_complete_ambiguous_asks():
    s, path = _store()
    try:
        s.add("mua sữa"); s.add("mua bánh")
        reg = _reg(s)
        out = reg.run("complete_task", {"keyword": "mua"})   # khớp 2 -> hỏi
        assert "2 việc" in out and "muốn hoàn thành việc nào" in out
    finally:
        if os.path.exists(path): os.unlink(path)


def test_tool_complete_single():
    s, path = _store()
    try:
        s.add("mua sữa")
        reg = _reg(s)
        assert "xong" in reg.run("complete_task", {"keyword": "sữa"}).lower()
        assert s.list() == []                              # đã xong -> ẩn
    finally:
        if os.path.exists(path): os.unlink(path)


def test_remove_task_is_destructive():
    s, path = _store()
    try:
        reg = _reg(s)
        assert reg.get("remove_task").destructive is True
        assert "xoá việc" in reg.get("remove_task").confirm_message(keyword="mua sữa")
    finally:
        if os.path.exists(path): os.unlink(path)


def test_tools_absent_without_store():
    reg = registry_with(actions=MagicMock())
    assert not reg.has("add_task")
