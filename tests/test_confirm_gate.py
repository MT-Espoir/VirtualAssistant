"""
Cổng duyệt hành động khó hoàn tác, ở TẦNG REGISTRY.

Trước bản này cổng chỉ nằm trong vòng lặp agent (`Agent._find_destructive` soi
`turn.tool_calls`), nên mọi đường KHÔNG đi qua vòng lặp đó đều lách được: fast-path và nút
trên panel gọi thẳng `registry.run()`, và các bề mặt tool tương lai (meta-tool, sinh code)
không có `tool_calls` để soi. Xem `docs/tool_surface_spec.md` §5.

Tính chất phải giữ: **handler của tool cần duyệt không bao giờ chạy nếu chưa được duyệt**,
bất kể ai gọi. `confirmed=True` là cách DUY NHẤT mở cổng, và chỉ agent dùng nó sau khi
người dùng đã nói "có" / bấm nút.

Luồng xác nhận nhìn từ phía agent (hỏi, "có"/"không", panel) đã có test ở `test_agent.py`.
"""

from conftest import registry_with

from unittest.mock import MagicMock

try:
    import pytest
except ImportError:
    pytest = None

from agent.tools import ActionRefused, NeedsConfirmation, Tool, ToolRegistry


def _actions():
    a = MagicMock()
    a.close_application.return_value = "Đã đóng Chrome."
    return a


# --------------------------- chặn / cho qua --------------------------- #

def test_tool_destructive_bi_chan_khi_chua_duyet():
    """Tính chất lõi: gọi thẳng registry cũng không chạy được `close_app`."""
    actions = _actions()
    reg = registry_with(actions=actions)
    with pytest.raises(NeedsConfirmation) as err:
        reg.run("close_app", {"app_name": "chrome"})
    actions.close_application.assert_not_called()          # handler KHÔNG chạy
    assert err.value.name == "close_app"
    assert "chrome" in err.value.phrase.lower()


def test_tool_destructive_chay_khi_da_duyet():
    actions = _actions()
    reg = registry_with(actions=actions)
    assert reg.run("close_app", {"app_name": "chrome"}, confirmed=True) == "Đã đóng Chrome."
    actions.close_application.assert_called_once_with("chrome")


def test_tool_khong_destructive_van_chay_binh_thuong():
    """Cổng không được đụng vào đường thường — tool chỉ đọc vẫn chạy không cần cờ gì."""
    actions = _actions()
    actions.system_info.return_value = "CPU 10%"
    assert registry_with(actions=actions).run("system_info", {}) == "CPU 10%"


def test_tool_co_ban_xem_truoc_cung_bi_chan_du_khong_destructive():
    """Lý do duyệt thứ hai: có nội dung LLM viết ra mà người dùng phải đọc bằng mắt.

    `gws_gmail_draft` chỉ lưu vào mục Nháp nên heuristic tên xếp là "chỉ đọc"; nhưng viết
    mail chính là lúc cần nhìn bản nháp nhất.
    """
    from actions.email_draft import email_draft

    saved = []
    reg = ToolRegistry()
    reg.register(Tool(
        name="luu_nhap",
        description="lưu nháp",
        input_schema={"type": "object", "properties": {}},
        handler=lambda **kw: saved.append(kw) or "Đã lưu nháp.",
        destructive=False,                     # <- heuristic tên xếp là "chỉ đọc"
        preview=lambda **a: email_draft(a),
    ))
    with pytest.raises(NeedsConfirmation):
        reg.run("luu_nhap", {"to": "sep@x.com", "subject": "Xin nghỉ", "body": "Kính gửi..."})
    assert saved == []


def test_tool_co_preview_nhung_tham_so_khong_phai_email_thi_khong_chan():
    """`preview` gắn cho MỌI tool MCP; tham số không mang hình dạng email -> không cổng."""
    reg = ToolRegistry()
    reg.register(Tool(
        name="doc_lich",
        description="đọc lịch",
        input_schema={"type": "object", "properties": {}},
        handler=lambda **kw: "Hôm nay trống.",
        preview=lambda **a: __import__("actions.email_draft", fromlist=["x"]).email_draft(a),
    ))
    assert reg.run("doc_lich", {"ngay": "hom nay"}) == "Hôm nay trống."


# --------------------------- `gate()` là nguồn chính sách --------------------------- #

def test_gate_tra_ve_du_thu_de_di_hoi():
    g = registry_with(actions=_actions()).gate("close_app", {"app_name": "chrome"})
    assert set(g) == {"name", "arguments", "phrase", "preview"}
    assert g["name"] == "close_app" and g["arguments"] == {"app_name": "chrome"}


def test_gate_tra_none_cho_tool_chi_doc_va_tool_khong_ton_tai():
    reg = registry_with(actions=_actions())
    assert reg.gate("system_info", {}) is None
    assert reg.gate("khong_co_tool_nay", {}) is None       # không phải việc của cổng


def test_tool_khong_ton_tai_van_nem_KeyError_nhu_cu():
    """Cổng không được nuốt mất lỗi gọi sai tên — Agent phân biệt hai ca này."""
    with pytest.raises(KeyError):
        registry_with(actions=_actions()).run("khong_co_tool_nay", {})


def test_preview_hong_thi_van_chan_bang_co_destructive():
    """Dựng bản xem trước lỗi -> coi như không có preview, nhưng `destructive` vẫn chặn."""
    chay = []
    reg = ToolRegistry()
    reg.register(Tool(
        name="xoa_het",
        description="xoá hết",
        input_schema={"type": "object", "properties": {}},
        handler=lambda **kw: chay.append(kw) or "xong",
        destructive=True,
        preview=lambda **a: 1 / 0,             # nổ
        confirm_message=lambda **a: 1 / 0,     # nổ nốt
    ))
    with pytest.raises(NeedsConfirmation) as err:
        reg.run("xoa_het", {})
    assert chay == []
    assert err.value.phrase == "xoa_het"       # hỏng câu chữ -> lùi về tên tool, VẪN hỏi


# --------------------------- fast-path không lách được cổng --------------------------- #

def _fast_registry(chay):
    reg = registry_with(actions=_actions())
    reg.register(Tool(
        name="tool_nguy_hiem",
        description="giả lập một fast-path trỏ vào tool khó hoàn tác",
        input_schema={"type": "object", "properties": {}},
        handler=lambda **kw: chay.append(kw) or "đã làm",
        destructive=True,
        confirm_message=lambda **a: "làm việc nguy hiểm",
    ))
    return reg


def test_fast_path_khong_chay_duoc_tool_can_duyet():
    """Hôm nay chưa luật fast-path nào trỏ vào tool `destructive`, nên đây là test CHẶN
    TRƯỚC: thêm một luật khớp ra `close_app` cũng không thành lỗ hổng."""
    import app

    chay = []
    agent = MagicMock()
    agent.registry = _fast_registry(chay)
    assert app._run_fast(agent, ("tool_nguy_hiem", {})) is None
    assert chay == []


def test_dispatch_nhuong_luot_cho_agent_khi_fast_path_bi_chan():
    """Bị chặn thì phải RƠI XUỐNG đường LLM để agent đi hỏi, không phải im lặng bỏ lượt."""
    import app

    chay = []
    agent = MagicMock()
    agent.registry = _fast_registry(chay)
    agent.run.return_value = type("R", (), {"text": "Bạn có chắc không?",
                                            "emotion": "neutral"})()
    text, _ = app._dispatch(agent, "làm việc nguy hiểm", MagicMock(),
                            fast_match=lambda _t: ("tool_nguy_hiem", {}))
    assert text == "Bạn có chắc không?"
    agent.run.assert_called_once()
    assert chay == []


def test_fast_path_thuong_van_chay_thang_nhu_cu():
    """Cổng không được làm chậm đường fast-path thật (âm lượng, media)."""
    import app

    actions = _actions()
    actions.control_volume.return_value = "Đã đặt âm lượng 35%."
    agent = MagicMock()
    agent.registry = registry_with(actions=actions)
    assert app._run_fast(agent, ("set_volume", {"level": 35})) == "Đã đặt âm lượng 35%."


# --------------------------- cờ destructive là HÀM --------------------------- #
#
# Ngân sách spec đẩy về phía gom nhiều hành động vào một tool theo enum
# (`docs/system_admin_spec.md` §2–3). Cờ tĩnh khi đó chỉ có hai kết cục và cả hai đều sai:
# hoặc hành động nguy hiểm chạy không hỏi, hoặc hành động vô hại cũng phải xác nhận —
# mà hỏi thường xuyên thì người dùng bấm "có" theo phản xạ, cổng mất hết giá trị.

def _reg_power(chay):
    """Registry một tool `power(action)` gom hành động vô hại lẫn khó hoàn tác."""
    reg = ToolRegistry()
    reg.register(Tool(
        name="power", description="nguồn máy",
        input_schema={"type": "object", "properties": {"action": {"type": "string"}}},
        handler=lambda action=None: chay(action) or f"đã {action}",
        destructive=lambda action=None, **_: action in ("shutdown", "restart"),
        confirm_message=lambda action=None: f"{action} máy",
    ))
    return reg


def test_co_destructive_la_ham_chi_chan_dung_hanh_dong_nguy_hiem():
    chay = MagicMock(return_value=None)   # trả None để `or` trong handler rơi xuống chuỗi
    reg = _reg_power(chay)
    assert reg.run("power", {"action": "lock"}) == "đã lock"    # vô hại -> chạy thẳng
    chay.assert_called_once_with("lock")

    with pytest.raises(NeedsConfirmation):
        reg.run("power", {"action": "shutdown"})
    assert chay.call_count == 1                                  # handler KHÔNG chạy thêm


def test_co_destructive_la_ham_van_mo_duoc_bang_confirmed():
    chay = MagicMock(return_value=None)   # trả None để `or` trong handler rơi xuống chuỗi
    reg = _reg_power(chay)
    assert reg.run("power", {"action": "shutdown"}, confirmed=True) == "đã shutdown"
    chay.assert_called_once_with("shutdown")


def test_co_destructive_la_ham_bi_loi_thi_chan_chu_khong_tha():
    """Cờ rủi ro hỏng -> hỏi thừa một câu là phiền; đoán 'không nguy hiểm' mới là hỏng."""
    reg = ToolRegistry()
    reg.register(Tool(
        name="power", description="nguồn máy", input_schema={"type": "object"},
        handler=lambda **_: "chạy rồi",
        destructive=lambda **_: 1 / 0,          # nổ
        confirm_message=lambda **_: "làm việc đó",
    ))
    with pytest.raises(NeedsConfirmation):
        reg.run("power", {"action": "lock"})


def test_co_destructive_bool_van_chay_y_nhu_cu():
    """Tương thích ngược: 47 tool đang có đều dùng bool, không được đổi hành vi."""
    reg = registry_with(actions=_actions())
    assert reg.gate("close_app", {"app_name": "chrome"}) is not None
    assert reg.gate("list_windows", {}) is None


# --------------------------- tool `admin` + lượt nhiễm --------------------------- #
#
# `docs/system_admin_spec.md` §7 lớp 1: tool quản trị gặp lượt đã chạm nội dung ngoài thì
# TỪ CHỐI THẲNG, không hỏi thêm. Xác nhận bằng giọng là lớp phòng thủ chính của hệ này, và
# nó dựa vào việc người dùng tỉnh táo đúng lúc — không nên để nó là thứ duy nhất đứng
# trước một lệnh tắt máy do trang web mớm vào.

def _reg_admin(chay):
    reg = ToolRegistry()
    reg.register(Tool(
        name="kill_process", description="kết thúc tiến trình",
        input_schema={"type": "object", "properties": {"ten": {"type": "string"}}},
        handler=lambda ten=None: chay(ten) or f"đã tắt {ten}",
        destructive=True, admin=True,
        confirm_message=lambda ten=None: f"tắt {ten}",
    ))
    return reg


def test_tool_admin_bi_tu_choi_khi_luot_nhiem():
    chay = MagicMock(return_value=None)   # trả None để `or` trong handler rơi xuống chuỗi
    reg = _reg_admin(chay)
    with pytest.raises(ActionRefused) as err:
        reg.run("kill_process", {"ten": "chrome"}, nhiem=True)
    chay.assert_not_called()
    assert err.value.name == "kill_process"
    assert err.value.ly_do                                   # có câu nói được cho người dùng


def test_tu_choi_khong_mo_duoc_bang_nguoi_dung_dong_y():
    """Khác `NeedsConfirmation` ở chỗ này: một câu 'có' cũng không mở được."""
    chay = MagicMock(return_value=None)   # trả None để `or` trong handler rơi xuống chuỗi
    reg = _reg_admin(chay)
    with pytest.raises(ActionRefused):
        reg.run("kill_process", {"ten": "chrome"}, nhiem=True, confirmed=True)
    chay.assert_not_called()


def test_tool_admin_o_luot_sach_thi_chi_phai_xac_nhan_nhu_thuong():
    chay = MagicMock(return_value=None)   # trả None để `or` trong handler rơi xuống chuỗi
    reg = _reg_admin(chay)
    with pytest.raises(NeedsConfirmation):               # hỏi, chứ không từ chối
        reg.run("kill_process", {"ten": "chrome"}, nhiem=False)
    assert reg.run("kill_process", {"ten": "chrome"}, confirmed=True) == "đã tắt chrome"
    chay.assert_called_once_with("chrome")


def test_tool_thuong_khong_bi_luot_nhiem_tu_choi():
    """Luật chỉ nhắm tool `admin`. Tool đọc vẫn chạy được sau khi đọc web."""
    reg = registry_with(actions=_actions())
    assert reg.tu_choi("list_windows", {}, nhiem=True) is None


def test_tu_choi_tra_none_cho_tool_khong_ton_tai():
    reg = _reg_admin(MagicMock())
    assert reg.tu_choi("khong_co_tool_nay", {}, nhiem=True) is None
