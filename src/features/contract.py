"""
Hợp đồng cho một "feature" (tính năng) và bộ nạp chúng.

Một feature gom TOÀN BỘ mảnh của một tính năng vào một chỗ: service, tool, đoạn
prompt riêng, panel giao diện. Trước đây các mảnh này nằm rải ở `agent/tools.py`,
`agent/router.py`, `llm/prompt_texts.py` và `app.py` — thêm một tính năng phải sờ
5-6 file ở 5 thư mục, và bảng `CASE_TOOLS` chép lại tên tool đã khai trong registry
(hai nguồn sự thật, đã sinh lỗi thứ tự substring "weather trước web").

Xem `docs/module_refactor_sprint.md`.
"""

import json
from dataclasses import dataclass, field, fields
from typing import Callable, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)

# Trần tổng payload tool specs gửi lên LLM mỗi lượt, tính bằng ký tự JSON.
# Đo 2026-08-25: 47 tool = 19.351 chars (~6.450 token) — ĐỌC LẠI MỖI LƯỢT.
# Trần đặt sát baseline có chủ đích: thêm feature mà vượt thì test đỏ NGAY tại đó,
# buộc phải nén mô tả hoặc nâng trần có cân nhắc, thay vì để chi phí trôi âm thầm.
SPEC_CHARS_BUDGET = 20_000


@dataclass
class FeatureContext:
    """Các dịch vụ dùng chung mà feature có thể xin. Feature KHÔNG tự dựng chúng.

    Trường nào cũng có thể là None: tính năng tương ứng bị tắt bằng config, hoặc
    không dựng được (Chrome chưa chạy, MCP chưa OAuth). Feature khai `requires` để
    tự tắt khi thiếu — xem `Feature.requires`.
    """
    actions: object = None       # AssistantActions — điều khiển máy (app, âm lượng, web)
    bus: object = None           # AssistantBus — kênh sự kiện sang UI
    browser: object = None       # BrowserBridge — cầu nối Chrome extension
    contacts: object = None      # ContactStore
    location: object = None      # LocationStore — toạ độ chính xác, tách khỏi hồ sơ
    mcp: object = None           # MCPClient — lịch/email qua server ngoài
    places: object = None        # PlacesService
    profile: object = None       # UserProfile
    routines: object = None      # RoutineStore
    scheduler: object = None     # ReminderScheduler
    screen: object = None        # ScreenController
    tasks: object = None         # TaskStore


_CONTEXT_FIELDS = frozenset(f.name for f in fields(FeatureContext))


@dataclass
class Feature:
    """Khai báo một tính năng. Mỗi feature là MỘT package dưới `features/`."""

    # Tên feature — DÙNG LUÔN làm tên router case, nên `CASE_TOOLS` suy ra được từ
    # registry thay vì chép tay (việc 5 của sprint).
    name: str

    # Đăng ký tool vào registry: (registry, ctx) -> None. Đây là phần bắt buộc duy nhất
    # ngoài `name`; feature không có tool (chỉ góp prompt hoặc panel) truyền None.
    register: Optional[Callable] = None

    # Tên các trường của FeatureContext mà feature CẦN. Thiếu bất kỳ cái nào (None) thì
    # feature tự tắt kèm log, KHÔNG crash. Tránh ảo tưởng "mọi module đều độc lập":
    # places thật sự cần browser + location, khai ra thì lúc thiếu còn biết đường lần.
    requires: Tuple[str, ...] = ()

    # Cổng bật/tắt bằng config: () -> bool. None = luôn bật (khi đủ `requires`).
    enabled: Optional[Callable] = None

    # Đoạn prompt riêng của feature, thay cho `llm/prompt_texts.CASES[name]`.
    prompt: str = ""

    # Trần ký tự cho phần tool specs của RIÊNG feature này. Cộng dồn phải nằm trong
    # SPEC_CHARS_BUDGET. Đặt sát mức thật để một tool phình ra là thấy ngay.
    max_spec_chars: int = 2_000

    # Chỗ dành sẵn cho việc 9 và 10 của sprint (dựng service lười, fast-path theo
    # feature). Khai trong hợp đồng từ đầu để hai việc đó không phải sửa lại chữ ký.
    build: Optional[Callable] = None          # (ctx) -> service, gọi ở lần dùng đầu
    fast_paths: Tuple = ()                    # regex 0-call LLM
    panel: Optional[Callable] = None          # hook dựng panel UI

    def __post_init__(self):
        # `requires` gõ sai tên trường sẽ làm feature TẮT VĨNH VIỄN trong im lặng —
        # lỗi lập trình, không phải tình huống chạy máy, nên ném ngay lúc nạp.
        unknown = set(self.requires) - _CONTEXT_FIELDS
        if unknown:
            raise ValueError(
                f"Feature {self.name!r} khai requires không có trong FeatureContext: "
                f"{sorted(unknown)}. Trường hợp lệ: {sorted(_CONTEXT_FIELDS)}")

    def missing(self, ctx: FeatureContext) -> List[str]:
        """Các dependency đang thiếu trong ctx. Rỗng = đủ điều kiện chạy."""
        return [name for name in self.requires if getattr(ctx, name, None) is None]


@dataclass
class LoadedFeature:
    """Kết quả nạp một feature — nguồn dữ liệu cho CASE_TOOLS và cho các test ngân sách."""
    name: str
    tools: Tuple[str, ...] = ()      # tên tool feature này đăng ký, THEO THỨ TỰ đăng ký
    spec_chars: int = 0
    prompt: str = ""


@dataclass
class LoadReport:
    """Toàn cảnh một lần nạp. Thay cho `CASE_TOOLS` viết tay."""
    loaded: List[LoadedFeature] = field(default_factory=list)
    skipped: List[Tuple[str, str]] = field(default_factory=list)   # (tên, lý do)

    @property
    def spec_chars(self) -> int:
        return sum(f.spec_chars for f in self.loaded)

    def case_tools(self) -> dict:
        """{tên case -> [tên tool]} suy ra từ ĐÚNG thứ đã đăng ký.

        Đây là điểm chính của cả đợt refactor: router không còn bảng chép tay lệch pha
        với registry được nữa. Feature không có tool bị bỏ qua (case rỗng vô nghĩa).
        """
        return {f.name: list(f.tools) for f in self.loaded if f.tools}

    def prompt_fragments(self) -> List[Tuple[str, str]]:
        """[(tên case, đoạn prompt)] theo thứ tự nạp — thứ tự này phải ỔN ĐỊNH."""
        return [(f.name, f.prompt) for f in self.loaded if f.prompt.strip()]


def load_features(registry, ctx: FeatureContext, features) -> LoadReport:
    """Nạp `features` vào `registry` THEO ĐÚNG THỨ TỰ danh sách truyền vào.

    THỨ TỰ LÀ MỘT RÀNG BUỘC HIỆU SUẤT, không phải chuyện thẩm mỹ. Tool specs được
    nối vào prompt gửi lên model; Ollama tái dùng KV cache theo TIỀN TỐ, nên chỉ cần
    thứ tự đổi giữa hai lần chạy là tiền tố lệch và mất sạch cache — đo được ~16-20s
    mỗi lượt (`docs/latency_optimization_spec.md`). Vì vậy nơi gọi phải truyền một
    DANH SÁCH tường minh; tuyệt đối không quét thư mục hay duyệt set ở đây.
    """
    report = LoadReport()

    for feature in features:
        if feature.enabled is not None and not feature.enabled():
            report.skipped.append((feature.name, "tắt bằng config"))
            logger.info("feature %s: bỏ qua (tắt bằng config)", feature.name)
            continue

        missing = feature.missing(ctx)
        if missing:
            reason = "thiếu " + ", ".join(missing)
            report.skipped.append((feature.name, reason))
            logger.info("feature %s: bỏ qua (%s)", feature.name, reason)
            continue

        before = set(registry.names())
        if feature.register is not None:
            feature.register(registry, ctx)
        added = tuple(n for n in registry.names() if n not in before)

        spec_chars = sum(len(json.dumps(registry.get(n).spec(), ensure_ascii=False))
                         for n in added)
        if spec_chars > feature.max_spec_chars:
            # Cảnh báo chứ KHÔNG ném: vượt trần làm prompt đắt lên, không làm sai chức
            # năng — ném ở đây là bắt người dùng cuối chịu một lỗi thuộc về lúc phát
            # triển. Cổng cứng nằm ở test (việc 7 của sprint).
            logger.warning("feature %s vượt trần specs: %d/%d chars",
                           feature.name, spec_chars, feature.max_spec_chars)

        report.loaded.append(LoadedFeature(name=feature.name, tools=added,
                                           spec_chars=spec_chars, prompt=feature.prompt))
        logger.debug("feature %s: %d tool, %d chars", feature.name, len(added), spec_chars)

    if report.spec_chars > SPEC_CHARS_BUDGET:
        logger.warning("TỔNG specs vượt ngân sách: %d/%d chars — mỗi lượt LLM đọc lại "
                       "toàn bộ chỗ này", report.spec_chars, SPEC_CHARS_BUDGET)

    logger.info("đã nạp %d feature (%d bỏ qua), specs %d chars",
                len(report.loaded), len(report.skipped), report.spec_chars)
    return report
