"""HUD quản trị: giọng nói ngắn, danh sách đầy đủ đi riêng lên màn hình."""

import types
from unittest.mock import MagicMock

from conftest import registry_with

from ui.panels import audio_device_blocks, process_blocks
from utils.events import AssistantBus


class ActionsWithReports:
    def process_report(self, sort_by="memory", limit=3):
        rows = [
            {"name": "chrome.exe", "value": 1200, "display": "1.2 GB"},
            {"name": "Code.exe", "value": 900, "display": "900 MB"},
            {"name": "python.exe", "value": 500, "display": "500 MB"},
            {"name": "explorer.exe", "value": 200, "display": "200 MB"},
        ]
        return "Ngốn RAM nhất: chrome.exe; Code.exe; python.exe.", rows

    def audio_device_report(self, action="list", name=None):
        return "Thiết bị phát: Loa; Tai nghe.", [
            {"name": "Loa", "selected": action == "switch"},
            {"name": "Tai nghe", "selected": False},
        ]


def test_process_report_giu_cau_noi_ngan_nhung_panel_nhan_day_du():
    bus = AssistantBus()
    reg = registry_with(actions=ActionsWithReports(), bus=bus)

    out = reg.run("list_processes", {"sort_by": "memory", "limit": 3})

    assert out.count(";") == 2
    event = [e for e in bus.drain() if e.system][0]
    assert event.system["kind"] == "processes"
    assert len(event.system["rows"]) == 4
    assert event.system["sort_by"] == "memory"


def test_audio_device_day_danh_sach_len_cung_panel_quan_tri():
    bus = AssistantBus()
    reg = registry_with(actions=ActionsWithReports(), bus=bus)

    reg.run("audio_device", {"action": "switch", "name": "Loa"})

    event = [e for e in bus.drain() if e.system][0]
    assert event.system["kind"] == "audio_devices"
    assert [r["name"] for r in event.system["rows"]] == ["Loa", "Tai nghe"]
    assert event.system["rows"][0]["selected"] is True


def test_bus_chup_ban_sao_de_thread_action_khong_sua_duoc_event():
    bus = AssistantBus()
    rows = [{"name": "Loa", "selected": False}]
    bus.emit_system("audio_devices", rows)
    rows[0]["selected"] = True

    assert bus.drain()[0].system["rows"][0]["selected"] is False


def test_process_blocks_khong_cat_danh_sach_day_du():
    rows = [{"name": f"app-{i}", "display": f"{i} MB"} for i in range(30)]

    cards = [b for b in process_blocks(rows, "memory") if b[0] == "card"]

    assert len(cards) == 30
    assert all(card[2] is None for card in cards)  # chỉ đọc, không sinh hành động


def test_audio_blocks_danh_dau_thiet_bi_vua_chuyen():
    blocks = audio_device_blocks([
        {"name": "Loa", "selected": True},
        {"name": "Tai nghe", "selected": False},
    ])
    cards = [b for b in blocks if b[0] == "card"]

    assert "vừa chuyển sang" in cards[0][1]["meta"]
    assert "sẵn sàng" in cards[1][1]["meta"]


def test_avatar_dispatch_dung_snapshot_sang_hud_ma_khong_can_tk_that():
    from ui.avatar import AvatarWindow

    win = object.__new__(AvatarWindow)
    panel = MagicMock()
    win._panel = MagicMock(return_value=panel)

    win._show_system({
        "kind": "processes",
        "sort_by": "cpu",
        "rows": [{"name": "python.exe", "display": "35%"}],
    })

    win._panel.assert_called_once_with("system", "TIẾN TRÌNH", None)
    assert panel.title == "TIẾN TRÌNH"
    blocks = panel.show.call_args.args[0]
    assert "python.exe" in str(blocks) and "35%" in str(blocks)


def _proc(name, rss=0):
    p = MagicMock()
    p.info = {"name": name, "memory_info": types.SimpleNamespace(rss=rss)}
    return p


def test_snapshot_hud_va_cau_noi_dung_chung_mot_lan_lay_mau():
    from actions.system import system_info

    fake = types.SimpleNamespace(
        process_iter=lambda attrs=None: [
            _proc("chrome.exe", 700 * 1024 ** 2),
            _proc("chrome.exe", 500 * 1024 ** 2),
            _proc("Code.exe", 900 * 1024 ** 2),
        ],
        cpu_count=lambda logical=True: 8,
    )
    old = system_info.psutil
    system_info.psutil = fake
    try:
        summary, rows = system_info.process_report("memory", 1)
    finally:
        system_info.psutil = old

    assert "chrome.exe 1.2 GB" in summary
    assert [row["name"] for row in rows] == ["chrome.exe", "Code.exe"]
    assert rows[0]["display"] == "1.2 GB"


def test_limit_rac_tu_llm_roi_ve_mac_dinh_thay_vi_lam_hong_tool():
    from actions.system import system_info

    fake = types.SimpleNamespace(
        process_iter=lambda attrs=None: [_proc("app.exe", 100 * 1024 ** 2)],
        cpu_count=lambda logical=True: 8,
    )
    old = system_info.psutil
    system_info.psutil = fake
    try:
        summary, rows = system_info.process_report("memory", "ba cái")
    finally:
        system_info.psutil = old

    assert "app.exe" in summary and len(rows) == 1
