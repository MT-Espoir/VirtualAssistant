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
