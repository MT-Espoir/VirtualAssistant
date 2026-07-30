"""
Lõi eval — logic THUẦN (không mạng, không LLM thật), test được.

- RecordingRegistry: bọc một registry thật, GHI LẠI tool nào được gọi nhưng KHÔNG thực
  thi (trả stub) -> chạy agent mà không gây tác dụng phụ.
- RecordingRouter: bọc router thật, ghi lại case đã phân loại (chỉ classify 1 lần/lượt).
- run_case / score_case / summarize: chạy một ca, chấm điểm, tổng hợp.

Agent + LLM được TIÊM vào nên test được bằng LLM giả; run_eval.py mới ráp LLM thật.
"""

from agent.agent import Agent


class RecordingRegistry:
    """Bọc registry: giữ nguyên specs() để LLM thấy đúng bộ tool, nhưng run() chỉ GHI
    LẠI (name, args) rồi trả stub — tool KHÔNG chạy thật (không mở app/đổi âm lượng...)."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []                 # danh sách (tool_name, args) theo thứ tự

    def specs(self):
        return self._inner.specs()

    def has(self, name):
        return self._inner.has(name)

    def run(self, name, arguments):
        self.calls.append((name, dict(arguments or {})))
        # Trả câu NHƯ THỂ thành công để model coi bước đã xong (giảm gọi lặp vô ích —
        # production tool trả xác nhận thật; stub "trống nghĩa" khiến model tưởng chưa xong).
        return f"Đã thực hiện {name} thành công."


class RecordingRouter:
    """Bọc router: ghi lại case đã phân loại; chỉ gọi classify 1 lần mỗi lượt."""

    def __init__(self, inner):
        self._inner = inner
        self.cases = []

    def select(self, text, registry):
        case = self._inner.classify(text)
        self.cases.append(case)
        return self._inner.select_for_case(case, registry)


def score_case(case, called, got_case, error=None):
    """Chấm một ca. `called`: list tên tool đã gọi. `got_case`: case router chọn.

    tool_ok: nếu ca kỳ vọng tool -> mọi tool kỳ vọng phải nằm trong danh sách đã gọi;
    nếu kỳ vọng KHÔNG gọi tool (expect rỗng) -> không được gọi tool nào.
    """
    expected = list(case.get("expect", []))
    exp_set, called_set = set(expected), set(called)
    tool_ok = exp_set.issubset(called_set) if expected else (len(called_set) == 0)

    case_ok = None
    if case.get("case") is not None and got_case is not None:
        case_ok = (got_case == case["case"])

    return {
        "id": case.get("id"),
        "text": case["text"],
        "expect": expected,
        "called": list(called),
        "tool_ok": bool(tool_ok) and error is None,
        "expect_case": case.get("case"),
        "got_case": got_case,
        "case_ok": case_ok,
        "error": error,
    }


def run_case(llm, registry, router, case, max_iterations=4):
    """Chạy một ca qua agent thật (LLM tiêm vào) với registry/ router ghi-lại.

    Trả dict kết quả đã chấm điểm. Không gây tác dụng phụ (tool không thực thi).
    """
    rec_reg = RecordingRegistry(registry)
    rec_router = RecordingRouter(router) if router is not None else None
    agent = Agent(llm=llm, registry=rec_reg, router=rec_router,
                  max_history_turns=0, max_iterations=max_iterations)

    error = None
    try:
        agent.run(case["text"])
    except Exception as e:                      # ca lỗi -> ghi nhận, không làm vỡ cả eval
        error = f"{type(e).__name__}: {e}"

    called = [name for name, _ in rec_reg.calls]
    got_case = rec_router.cases[-1] if (rec_router and rec_router.cases) else None
    return score_case(case, called, got_case, error)


def summarize(results):
    """Tổng hợp: tỉ lệ gọi đúng tool + tỉ lệ phân loại đúng case."""
    n = len(results)
    tool_pass = sum(1 for r in results if r["tool_ok"])
    case_scored = [r for r in results if r["case_ok"] is not None]
    case_pass = sum(1 for r in case_scored if r["case_ok"])
    return {
        "total": n,
        "tool_pass": tool_pass,
        "tool_acc": tool_pass / n if n else 0.0,
        "case_total": len(case_scored),
        "case_pass": case_pass,
        "case_acc": (case_pass / len(case_scored)) if case_scored else None,
    }
