"""
Bề mặt tool — trả lời ĐÚNG MỘT câu hỏi: lượt này model được thấy prompt gì và tool nào.

Hợp đồng (duck-typing, không abstract class — cả codebase dùng lối này):

    select(user_text, registry) -> (system_prompt, tool_specs)

Vì sao tách ra thành một khái niệm riêng: chi phí input mỗi lượt tỉ lệ TUYẾN TÍNH với số
tool gửi đi. Ở 47 tool, gửi hết là chấp nhận được (19.257 ký tự ≈ 6.450 token). Ở 100–200
tool thì không, và cách chữa là đổi CÁCH CHIẾU tool vào prompt:

    all      O(N)   — gửi hết (lớp này)
    indexed  O(√N)  — mục lục nhóm + meta-tool mở nhóm theo yêu cầu
    code     O(1)   — một tool chạy code, tool thành hàm đọc theo yêu cầu

Ba thứ đó KHÔNG phải ba kiến trúc mà là ba cài đặt của cùng hợp đồng trên. Agent chỉ biết
hợp đồng, nên lên bậc = thêm một lớp ở đây + đổi config, KHÔNG sửa vòng lặp agent và không
sửa một định nghĩa tool nào. Xem `docs/tool_surface_spec.md`.

`agent/router.py::Router` là cài đặt thứ hai của cùng hợp đồng (thu hẹp theo case bằng một
lượt LLM phân loại) — nó không phải một khái niệm song song.
"""


class AllTools:
    """Gửi TOÀN BỘ tool + một prompt cố định. Hành vi mặc định khi không có router.

    Đúng lựa chọn ở quy mô hiện tại: provider mạnh chọn đúng tool giữa cả 47 tool mà không
    cần thu hẹp, và bỏ được lượt LLM phân loại (đo được: 2,86 -> 1,86 call/lượt).
    """

    def __init__(self, system: str):
        self.system = system

    def select(self, user_text, registry):
        # `user_text` không dùng tới — bề mặt này không phụ thuộc câu người dùng nói. Vẫn
        # nhận nó để đúng hợp đồng: các bề mặt khác (router, indexed) đều cần.
        return self.system, registry.specs()


MO_NHOM = "mo_nhom"

# Bộ lõi — tool được thấy ở MỌI lượt mà không phải mở nhóm.
#
# Chốt bằng 51 ca có nhãn trong `evals/cases.py`, KHÔNG phải bằng `logs/outcomes.jsonl`:
# log lệch theo việc đang phát triển lúc ghi (nhóm `system` xuất hiện 0 lần dù là nhóm lâu
# đời nhất), còn bộ ca eval được viết để phủ đều mọi feature — đúng thứ một BỘ LÕI cần.
#
# Cách chọn: tham lam theo "giảm tỉ lệ mở nhóm trên mỗi ký tự", dừng khi đạt tiêu chí
# `r <= 0,25` của `docs/indexed_tools_spec.md` §7. Chạy lại bộ tối ưu TỪ ĐẦU mỗi lần bộ ca
# đổi, không vá tay danh sách — vá tay là cách một hằng số dần thành mê tín.
# Kết quả 2026-09-12: r = 24%, 8.699 ký tự.
#
# HAI HẠN CHẾ phải nhớ khi đọc danh sách này:
#
# 1. Bộ ca eval cũng do người viết ra, không phải phân bố dùng thật. Lần chốt này bốn tool
#    quản trị vào lõi CHÍNH VÌ tôi vừa thêm bảy ca quản trị vào bộ — đó đúng là rủi ro
#    overfit, ghi ra để người sau đừng coi đây là số đo khách quan. Việc đo lại bằng ≥200
#    lượt thật vẫn còn trong backlog (§5) và nó mới là thứ chốt được.
# 2. `set_brightness` do TÔI thêm tay, bộ tối ưu không chọn. Lý do là NGỮ NGHĨA: nó cùng họ
#    với `set_volume` ("chỉnh to nhỏ cái gì đó"), để một cái trong lõi còn một cái phải mở
#    nhóm là bắt model phân biệt hai câu gần như đồng dạng — thứ 51 ca không nhìn thấy.
CORE = (
    "open_app", "close_app", "set_volume", "set_brightness", "system_info",
    "list_processes", "power", "kill_process", "keep_awake",
    "open_website", "play_youtube", "web_search_list", "get_weather",
    "schedule_reminder", "list_reminders", "browser_list_tabs", "take_screenshot",
    "list_tasks", "find_nearby", "find_place", "research_places", "open_place_result",
    "refine_places",
)

_HUONG_DAN = (
    "Bạn đang thấy các công cụ hay dùng nhất. Những công cụ còn lại được xếp theo NHÓM "
    "dưới đây; cần nhóm nào thì gọi `%s` với tên nhóm đó rồi dùng công cụ vừa mở.\n"
) % MO_NHOM


class IndexedTools:
    """Bộ lõi + mục lục nhóm + meta-tool mở nhóm. O(√N) thay cho O(N) của `AllTools`.

    Đo 2026-09-12 trên 52 tool: nền 18.996 ký tự (prompt + specs) thay cho 31.356 của
    `AllTools` — **−39%**. Cái đánh đổi là THỜI GIAN: lượt phải mở nhóm tốn thêm một vòng
    LLM, đo được 22% số lượt. Xem `docs/indexed_tools_spec.md`.

    Con số từng là −60% cho tới khi eval thật cho thấy nó mua bằng ĐỘ CHÍNH XÁC: chỉ dẫn
    riêng của nhóm CÓ tool trong lõi buộc phải gửi sẵn (§7e), và chúng tốn 5.673 ký tự.
    Đây là chỗ dễ "tối ưu" lại mà không biết mình đang mua lại đúng cái lỗi cũ.

    Mục lục dùng lại `router_hint` của từng feature, không viết mô tả nhóm mới: hai bản mô
    tả cho cùng một nhóm là hai chỗ để lệch nhau trong im lặng.

    `system` PHẢI là `prompts.base()`, KHÔNG phải `prompts.merged()` — lớp này TỰ ghép
    phần chỉ dẫn nó cần. Dễ làm sai vì `AllTools` thì bắt buộc dùng `merged()`. Đo
    2026-09-11: `merged()` = 10.396 ký tự vì nó gộp chỉ dẫn riêng của CẢ 10 feature.
    Ở đây chỉ dẫn chia làm hai đường, theo đúng câu hỏi "model có dùng được tool đó ngay
    không": nhóm có tool trong LÕI -> gửi SẴN trong prompt; nhóm còn lại -> gửi kèm KẾT
    QUẢ của `mo_nhom`, tới đúng lúc cần và nối vào cuối nên không động tới tiền tố.

    KHÔNG dùng cho Ollama. Mở nhóm giữa lượt làm nguội KV cache, và đo được trên máy này
    là 16–20 giây mỗi lượt (`tests/test_prefix_stability.py`) — nhiều hơn mọi thứ tiết
    kiệm được.
    """

    def __init__(self, system, report, core=None):
        self.system = system
        # Thứ tự lấy từ `report.loaded` (tức `features/catalog.py`) chứ không từ dict/set:
        # tiền tố phải cố định từng byte giữa các lượt.
        self._nhom = {f.name: tuple(f.tools) for f in report.loaded if f.tools}
        self._muc_luc = "\n".join(f.router_hint.strip() for f in report.loaded
                                  if f.tools and f.router_hint)
        self._chi_dan = {f.name: f.prompt.strip() for f in report.loaded
                         if f.tools and f.prompt.strip()}
        self.core = tuple(core if core is not None else CORE)
        # Nhóm CÓ tool trong lõi thì chỉ dẫn phải gửi NGAY, không đợi mở nhóm: model dùng
        # được tool của nhóm đó từ vòng đầu, nên chỉ dẫn đợi tới lúc mở là chỉ dẫn KHÔNG
        # BAO GIỜ TỚI. Đo bằng eval thật 2026-09-12 (`docs/indexed_tools_spec.md` §7e):
        # thiếu nó, tool-acc tụt 98% -> 94% theo đúng ba cách mà chỉ dẫn vắng mặt gây ra —
        # gọi `web_search_list` rồi DỪNG vì không biết phải `read_search_result` tiếp, và
        # gọi `list_tasks` ba lần vì không biết có `complete_task`.
        self._nhom_da_gui = {n for n, ts in self._nhom.items() if set(ts) & set(self.core)}
        self._chi_dan_san = "\n\n".join(self._chi_dan[n] for n in self._nhom
                                        if n in self._nhom_da_gui and n in self._chi_dan)
        # Nhóm đã mở TRONG LƯỢT NÀY. Trạng thái sống đúng một lượt, `select` xoá sạch ở
        # đầu mỗi lượt — nếu không, lượt sau sẽ thừa hưởng nhóm của lượt trước và tiền tố
        # hết cố định.
        self._da_mo = []

    # ------------------------- hợp đồng bề mặt ------------------------- #
    def select(self, user_text, registry):
        self._da_mo = []
        self._dam_bao_meta_tool(registry)
        specs = [registry.get(n).spec() for n in self.core if registry.has(n)]
        specs.append(registry.get(MO_NHOM).spec())
        phan = [self.system, self._chi_dan_san, _HUONG_DAN + self._muc_luc]
        return "\n\n".join(p for p in phan if p), specs

    def expand(self, tool_name, arguments, registry):
        """Spec của nhóm vừa được mở, hoặc None nếu lời gọi này không mở nhóm nào.

        Chỉ trả PHẦN NỐI THÊM chứ không trả mảng đầy đủ: bất biến "chỉ nối vào cuối" nhờ
        vậy nằm ở MỘT chỗ (vòng lặp agent), thay vì nằm trong tay từng bề mặt.
        """
        if tool_name != MO_NHOM:
            return None
        nhom = (arguments or {}).get("nhom")
        if nhom not in self._nhom or nhom in self._da_mo:
            return None                      # mở lại nhóm cũ -> không nối gì, tránh trùng
        self._da_mo.append(nhom)
        return [registry.get(n).spec() for n in self._nhom[nhom]
                if registry.has(n) and n not in self.core]

    # ------------------------- meta-tool ------------------------- #
    def _dam_bao_meta_tool(self, registry):
        """Đăng ký `mo_nhom` vào registry nếu chưa có.

        Nó là tool THẬT chứ không phải trường hợp đặc biệt trong vòng lặp agent — nhờ vậy
        nó đi qua `ToolRegistry.gate()` như mọi tool khác và không mở ra đường vòng nào
        quanh cổng duyệt. Đăng ký lười ở đây thay vì trong `features/catalog.py` để bề mặt
        `AllTools` không phải trả ký tự cho một tool nó không dùng.
        """
        if registry.has(MO_NHOM):
            return
        from agent.tools import Tool
        ten_nhom = sorted(self._nhom)
        registry.register(Tool(
            name=MO_NHOM,
            description="Mở một nhóm công cụ để dùng được các công cụ trong nhóm đó.",
            input_schema={
                "type": "object",
                "properties": {"nhom": {"type": "string", "enum": ten_nhom,
                                        "description": "tên nhóm cần mở"}},
                "required": ["nhom"],
            },
            handler=self._mo_nhom,
        ))

    def _mo_nhom(self, nhom=None):
        """Kết quả của meta-tool: xác nhận + CHỈ DẪN RIÊNG của nhóm vừa mở.

        Chỉ dẫn đi đường này thay vì nằm sẵn trong system prompt vì hai lẽ: nó chỉ tốn ký
        tự ở lượt thật sự cần, và nó nối vào CUỐI hội thoại nên tiền tố vẫn cố định (đổi
        system prompt giữa lượt là hỏng cache ngay từ ký tự đầu tiên).
        """
        xac_nhan = "Đã mở nhóm %s, giờ dùng được công cụ trong nhóm." % nhom
        # Nhóm đã gửi chỉ dẫn sẵn trong prompt thì đừng gửi lại: lặp một khối văn bản dài
        # vừa tốn ký tự vừa làm model tưởng đó là chỉ dẫn MỚI.
        chi_dan = None if nhom in self._nhom_da_gui else self._chi_dan.get(nhom)
        return xac_nhan + ("\n" + chi_dan if chi_dan else "")
