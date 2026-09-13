"""
Seam BỀ MẶT TOOL: `select(user_text, registry) -> (system_prompt, tool_specs)`.

Điều seam này hứa, và là điều các test dưới đây canh: **đổi cách chiếu tool vào prompt
không phải sửa `Agent`**. Chi phí input tỉ lệ tuyến tính với số tool gửi đi, nên khi số
tool lên 100–200 ta sẽ phải đổi từ "gửi hết" sang "mục lục + mở nhóm" rồi sang "một tool
chạy code". Nếu vòng lặp agent còn biết `registry.specs()` hay biết router là gì thì mỗi
lần đổi là một lần mổ vào chỗ nguy hiểm nhất. Xem `docs/tool_surface_spec.md`.

`test_router.py` test riêng cách Router thu hẹp; ở đây chỉ quan tâm nó CẮM VỪA seam.
"""

from conftest import full_router, registry_with

try:
    import pytest
except ImportError:
    pytest = None

from agent.agent import Agent
from agent.surface import AllTools
from llm.client import AssistantTurn


class _CapturingLLM:
    """Ghi lại ĐÚNG thứ agent gửi lên (system + tools), rồi trả lời không gọi tool."""

    def __init__(self, text="Xong."):
        self.text = text
        self.seen_tools = None
        self.seen_system = None

    def generate(self, *, system, messages, tools):
        self.seen_system, self.seen_tools = system, tools
        return AssistantTurn(text=self.text)


class _FakeActions:
    def __getattr__(self, name):
        return lambda *a, **k: "noop"


def _names(specs):
    return {s["name"] for s in specs}


# --------------------------- AllTools --------------------------- #

def test_alltools_gui_toan_bo_tool_va_prompt_co_dinh():
    reg = registry_with(actions=_FakeActions())
    system, specs = AllTools("PROMPT").select("câu gì cũng được", reg)
    assert system == "PROMPT"
    assert _names(specs) == set(reg.names())


def test_alltools_khong_phu_thuoc_cau_nguoi_dung():
    """Bề mặt này chiếu cố định -> hai câu khác nhau phải ra cùng một payload.

    Không phải chi tiết vặt: payload cố định chính là điều kiện để cache tiền tố của
    Gemini/Ollama dùng lại được giữa các lượt.
    """
    reg = registry_with(actions=_FakeActions())
    be_mat = AllTools("PROMPT")
    assert be_mat.select("tăng âm lượng", reg) == be_mat.select("thời tiết", reg)


# --------------------------- Agent chỉ biết seam --------------------------- #

def test_agent_khong_khai_be_mat_thi_gui_het_tool():
    """Mặc định = hành vi cũ (router tắt): toàn bộ tool + prompt truyền vào."""
    reg = registry_with(actions=_FakeActions())
    llm = _CapturingLLM()
    Agent(llm, reg, system="PROMPT GỘP").run("làm gì đó")
    assert _names(llm.seen_tools) == set(reg.names())
    assert llm.seen_system.startswith("PROMPT GỘP")     # _compose_system nối thêm phía sau


def test_agent_dung_be_mat_duoc_tiem_ma_khong_can_sua_agent():
    """Lời hứa của seam: một bề mặt LẠ HOẮC (không phải Router) vẫn cắm vào chạy được.

    Đây là bản nháp thu nhỏ của `IndexedTools` sau này — chỉ hé đúng một tool.
    """
    class ChiMotTool:
        def select(self, user_text, registry):
            return "PROMPT HẸP", [s for s in registry.specs() if s["name"] == "set_volume"]

    llm = _CapturingLLM()
    Agent(llm, registry_with(actions=_FakeActions()), surface=ChiMotTool()).run("gì đó")
    assert _names(llm.seen_tools) == {"set_volume"}
    assert llm.seen_system.startswith("PROMPT HẸP")


def test_be_mat_nhan_dung_cau_nguoi_dung():
    """Router và `indexed` đều chiếu THEO câu người dùng -> seam phải chuyển câu đó xuống."""
    thay = []

    class GhiLai:
        def select(self, user_text, registry):
            thay.append(user_text)
            return "P", []

    Agent(_CapturingLLM(), registry_with(actions=_FakeActions()),
          surface=GhiLai()).run("mở youtube giúp tôi")
    assert thay == ["mở youtube giúp tôi"]


# --------------------------- Router cắm vừa cùng seam --------------------------- #

def test_router_cam_vua_seam_va_thu_hep_that():
    """Router không phải khái niệm song song — nó là cài đặt thứ hai của cùng hợp đồng."""
    class _PhanLoai:
        def generate(self, **k):
            return AssistantTurn(text="system")

    reg = registry_with(actions=_FakeActions())
    llm = _CapturingLLM()
    Agent(llm, reg, surface=full_router(_PhanLoai())).run("tăng âm lượng")
    thay = _names(llm.seen_tools)
    assert "set_volume" in thay
    assert thay < set(reg.names())                      # ĐÃ hẹp lại, không gửi hết


# --------------------------- IndexedTools --------------------------- #
#
# Cài đặt thứ ba của cùng seam. Điều đáng canh không phải "nó chạy được" mà là **agent
# không phải biết nó tồn tại**: vòng lặp chỉ gọi `getattr(surface, "expand", None)`.
# Xem `docs/indexed_tools_spec.md`.

class _ScriptedLLM:
    """Đọc kịch bản turn, ghi lại tool THẤY ĐƯỢC ở mỗi vòng."""

    def __init__(self, script):
        self.script = list(script)
        self.i = 0
        self.tools_moi_vong = []

    def generate(self, *, system, messages, tools):
        self.tools_moi_vong.append({s["name"] for s in tools})
        turn = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return turn


# Bộ lõi GIẢ cho các test CƠ CHẾ bên dưới. Cố ý không dùng `surface.CORE` thật: test cơ
# chế không được đỏ lên mỗi lần bộ lõi được chỉnh lại theo số đo mới — đó là hằng số tinh
# chỉnh, không phải hành vi. Tính chất của bộ lõi THẬT có test riêng ở `test_bo_loi.py`.
LOI_GIA = ("open_app", "get_weather")


def _indexed(core=LOI_GIA):
    """(registry đầy đủ, IndexedTools). Dựng tại chỗ vì `conftest.full_registry` chỉ trả
    registry, mà bề mặt này cần cả `report` để biết tool nào thuộc nhóm nào."""
    import dataclasses
    from unittest.mock import MagicMock

    from agent.surface import IndexedTools
    from features.contract import FeatureContext
    from features.registry import build_registry

    ctx = {f.name: MagicMock() for f in dataclasses.fields(FeatureContext)}
    ctx["mcp"] = None          # cùng lý do với conftest: tool MCP sinh động, làm lệch phép đếm
    reg, report = build_registry(FeatureContext(**ctx))
    return reg, IndexedTools("SYS", report, core=core)


def test_indexed_chi_gui_bo_loi_va_meta_tool():
    reg, ix = _indexed()
    system, specs = ix.select("mở chrome", reg)
    ten = _names(specs)
    assert "mo_nhom" in ten
    assert len(specs) < 12                       # bộ lõi, không phải cả catalog
    assert "close_app" not in ten                # tool ngoài lõi phải ẩn


def test_indexed_muc_luc_nam_trong_PROMPT_khong_phai_trong_specs():
    """Mục lục là chữ cho model đọc, không phải tool. Nhét vào specs là trả giá hai lần."""
    reg, ix = _indexed()
    system, specs = ix.select("x", reg)
    assert "system:" in system and "place:" in system
    assert all("mục lục" not in s["name"] for s in specs)


def test_indexed_re_hon_alltools_ke_ca_khi_da_mo_mot_nhom():
    """Tính chất quyết định: xấu nhất vẫn phải rẻ hơn gửi hết, nếu không thì đổi làm gì."""
    import json
    reg, ix = _indexed()
    sys_all, specs_all = AllTools("SYS").select("x", reg)
    sys_ix, specs_ix = ix.select("x", reg)
    specs_ix = specs_ix + ix.expand("mo_nhom", {"nhom": "place"}, reg)
    ca = lambda s, sp: len(s) + len(json.dumps(sp, ensure_ascii=False))   # noqa: E731
    assert ca(sys_ix, specs_ix) < ca(sys_all, specs_all)


def test_expand_chi_phan_hoi_dung_meta_tool():
    reg, ix = _indexed()
    ix.select("x", reg)
    assert ix.expand("open_app", {"app_name": "chrome"}, reg) is None
    assert ix.expand("mo_nhom", {"nhom": "khong_ton_tai"}, reg) is None


def test_expand_khong_tra_trung_khi_mo_lai_cung_mot_nhom():
    """Model gọi lặp thì không được nối trùng spec — LLM thấy hai tool cùng tên là hỏng."""
    reg, ix = _indexed()
    ix.select("x", reg)
    assert ix.expand("mo_nhom", {"nhom": "place"}, reg)
    assert ix.expand("mo_nhom", {"nhom": "place"}, reg) is None


def test_moi_luot_bat_dau_lai_tu_bo_loi():
    """Trạng thái 'đã mở' chỉ sống một lượt; không thì tiền tố hết cố định."""
    reg, ix = _indexed()
    ix.select("x", reg)
    ix.expand("mo_nhom", {"nhom": "place"}, reg)
    ix.select("lượt sau", reg)
    assert ix.expand("mo_nhom", {"nhom": "place"}, reg)      # mở lại được


def test_AGENT_thay_them_tool_sau_khi_mo_nhom_ma_khong_phai_sua_agent():
    """Điều seam hứa: agent không biết `IndexedTools` là gì, chỉ gọi `expand` nếu có."""
    from llm.client import ToolCall
    reg, ix = _indexed()
    llm = _ScriptedLLM([
        AssistantTurn(tool_calls=[ToolCall("t1", "mo_nhom", {"nhom": "place"})]),
        AssistantTurn(text="Xong."),
    ])
    Agent(llm, reg, surface=ix).run("tìm quán cà phê yên tĩnh")
    vong1, vong2 = llm.tools_moi_vong[0], llm.tools_moi_vong[1]
    assert "find_place" not in vong1                  # vòng đầu chưa thấy
    assert "find_place" in vong2                      # mở nhóm xong thì thấy
    assert vong1 <= vong2                             # chỉ NỐI THÊM, không bỏ đi cái nào


def test_alltools_khong_co_expand_va_agent_van_chay():
    """`AllTools` không có `expand`; `getattr` phải nuốt êm chứ không nổ."""
    reg = registry_with(actions=_FakeActions())
    assert not hasattr(AllTools("SYS"), "expand")
    llm = _CapturingLLM()
    Agent(llm, reg, surface=AllTools("SYS")).run("mấy giờ rồi")
    assert llm.seen_tools is not None
