"""
Lõi eval — logic THUẦN (không mạng, không LLM thật), test được.

- RecordingRegistry: bọc một registry thật, GHI LẠI tool nào được gọi nhưng KHÔNG thực
  thi (trả stub) -> chạy agent mà không gây tác dụng phụ.
- RecordingRouter: bọc router thật, ghi lại case đã phân loại (chỉ classify 1 lần/lượt).
- CountingLLM: bọc LLM, ĐẾM số lần gọi + cộng dồn thời gian -> đo chi phí mỗi lượt.
- run_case / score_case / summarize: chạy một ca, chấm điểm, tổng hợp.

Agent + LLM được TIÊM vào nên test được bằng LLM giả; run_eval.py mới ráp LLM thật.
"""

import time

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

    def get(self, name):
        return self._inner.get(name)          # để Agent đọc metadata tool (vd cờ destructive)

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


class CountingLLM:
    """Bọc LLM: đếm SỐ LẦN gọi `generate` + cộng dồn thời gian. Dùng để đo chi phí thật
    mỗi lượt (router classify + decide + respond đều tính) — cơ sở so sánh A/B khi cắt bớt
    lượt. Không đổi hành vi, chỉ quan sát."""

    def __init__(self, inner):
        self._inner = inner
        self.calls = 0
        self.seconds = 0.0

    def reset(self):
        self.calls = 0
        self.seconds = 0.0

    def generate(self, **kwargs):
        self.calls += 1
        t0 = time.time()
        try:
            return self._inner.generate(**kwargs)
        finally:                       # lỗi vẫn tính thời gian đã tiêu
            self.seconds += time.time() - t0


def score_case(case, called, got_case, error=None, calls=None, seconds=None):
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
        "calls": calls,          # số lần gọi LLM cho ca này (None = không đo)
        "seconds": seconds,      # tổng thời gian chờ LLM (giây)
    }


def run_case(llm, registry, router, case, max_iterations=4, system=None):
    """Chạy một ca qua agent thật (LLM tiêm vào) với registry/ router ghi-lại.

    `system`: prompt dùng khi KHÔNG có router (vd prompts.merged()). None -> mặc định của
    Agent. Có tham số này để eval đo ĐÚNG cấu hình production sẽ chạy, không phải base trần.

    Trả dict kết quả đã chấm điểm. Không gây tác dụng phụ (tool không thực thi).
    """
    rec_reg = RecordingRegistry(registry)
    rec_router = RecordingRouter(router) if router is not None else None
    # Đếm lần gọi LLM. Nếu nơi gọi đã bọc sẵn CountingLLM và đưa CHUNG cho router thì tái
    # dùng -> đếm được CẢ lượt classify; chưa bọc thì tự bọc (chỉ đếm lượt của agent).
    counting = llm if isinstance(llm, CountingLLM) else CountingLLM(llm)
    counting.reset()
    kwargs = {"system": system} if system is not None else {}
    agent = Agent(llm=counting, registry=rec_reg, router=rec_router,
                  max_history_turns=0, max_iterations=max_iterations, **kwargs)

    error = None
    try:
        agent.run(case["text"])
    except Exception as e:                      # ca lỗi -> ghi nhận, không làm vỡ cả eval
        error = f"{type(e).__name__}: {e}"

    called = [name for name, _ in rec_reg.calls]
    # Tool khó hoàn tác bị agent HOÃN để hỏi xác nhận (không chạy) -> vẫn tính là model ĐÃ
    # CHỌN đúng tool, vì eval đo độ tin cậy CHỌN tool, không đo việc thực thi.
    if agent.pending is not None:
        called.append(agent.pending["name"])
    got_case = rec_router.cases[-1] if (rec_router and rec_router.cases) else None
    return score_case(case, called, got_case, error,
                      calls=counting.calls, seconds=round(counting.seconds, 2))


def summarize(results):
    """Tổng hợp: độ chính xác (tool/case) + CHI PHÍ trung bình (số call LLM, giây) mỗi lượt.

    Chi phí là thước đo chính khi cắt bớt lượt LLM: tối ưu chỉ được chấp nhận nếu call/giây
    giảm mà độ chính xác KHÔNG tụt.
    """
    n = len(results)
    tool_pass = sum(1 for r in results if r["tool_ok"])
    case_scored = [r for r in results if r["case_ok"] is not None]
    case_pass = sum(1 for r in case_scored if r["case_ok"])
    counted = [r for r in results if r.get("calls") is not None]
    timed = [r for r in results if r.get("seconds") is not None]
    return {
        "total": n,
        "tool_pass": tool_pass,
        "tool_acc": tool_pass / n if n else 0.0,
        "case_total": len(case_scored),
        "case_pass": case_pass,
        "case_acc": (case_pass / len(case_scored)) if case_scored else None,
        "total_calls": sum(r["calls"] for r in counted) if counted else None,
        "avg_calls": (sum(r["calls"] for r in counted) / len(counted)) if counted else None,
        "avg_seconds": (sum(r["seconds"] for r in timed) / len(timed)) if timed else None,
    }
