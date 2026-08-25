"""
Chạy eval với LLM THẬT (theo config.LLM_PROVIDER) + router + toàn bộ tool thật.

    cd src && python -m evals.run_eval          # chạy hết
    cd src && python -m evals.run_eval sys web  # chỉ ca có id bắt đầu bằng tiền tố

Tool KHÔNG thực thi (RecordingRegistry) nên chạy an toàn, không mở app/đổi âm lượng.
Để A/B model: đổi LLM_PROVIDER (ollama <-> claude) trong src/.env rồi chạy lại, so số.
"""

import sys
import time

from agent.actions_facade import AssistantActions
from llm.client import build_default_llm_client
from agent.router import Router, case_tools_from
from features.contract import FeatureContext
from features.registry import build_registry
from llm import prompts
from utils.config import config
from evals.cases import CASES
from evals.harness import run_case, summarize, CountingLLM


class _StubDep:
    """Phụ thuộc giả cho scheduler/browser/screen — CHỈ để đăng ký đủ tool (specs);
    handler không bao giờ chạy thật vì RecordingRegistry không thực thi."""
    def __getattr__(self, _name):
        return lambda *a, **k: None


def _build_parts():
    # Bọc CountingLLM MỘT lần rồi dùng CHUNG cho agent lẫn router -> số call đếm được gồm
    # cả lượt classify của router (nếu chỉ bọc cho agent sẽ đếm thiếu 1 call/lượt).
    llm = CountingLLM(build_default_llm_client())
    # Truyền phụ thuộc giả để MỌI nhóm tool được đăng ký (web/system/screen/browser/
    # schedule/weather) -> LLM thấy đúng bộ tool như lúc chạy thật.
    registry, report = build_registry(FeatureContext(
        actions=AssistantActions(), scheduler=_StubDep(), browser=_StubDep(),
        screen=_StubDep(), tasks=_StubDep(), routines=_StubDep(),
        places=_StubDep(), location=_StubDep(), profile=_StubDep(),
        contacts=_StubDep(), bus=_StubDep()))
    # Dùng CHUNG quyết định với app.py -> eval đo đúng cấu hình production sẽ chạy.
    router = Router(llm, case_tools_from(report)) if config.use_router() else None
    return llm, registry, router


def _select(prefixes):
    if not prefixes:
        return CASES
    return [c for c in CASES if any(c["id"].startswith(p) for p in prefixes)]


def _parse_args(argv):
    """Tách '--gap=N' khỏi các tiền tố id ca. Trả (gap_giây, [tiền tố]).

    `gap` = nghỉ giữa các ca để KHÔNG vượt hạn mức RPM của nhà cung cấp. Cần thiết vì mỗi
    ca bắn 2-3 call liên tiếp: chạy sát nhau sẽ dính 429 -> client xoay model -> vừa hỏng
    phép so sánh (khác model) vừa làm số liệu độ trễ sai.
    """
    gap, prefixes = 0.0, []
    for a in argv:
        if a.startswith("--gap="):
            try:
                gap = max(0.0, float(a.split("=", 1)[1]))
            except ValueError:
                print(f"Bỏ qua --gap không hợp lệ: {a}")
        else:
            prefixes.append(a)
    return gap, prefixes


def _fmt_case(r):
    mark = "PASS" if r["tool_ok"] else "FAIL"
    line = f"{mark} [{r['id']:<10}] {r['text']}"
    detail = f"    mong đợi tool={r['expect']} | đã gọi={r['called']}"
    if r.get("calls") is not None:
        detail += f" | {r['calls']} call ({r['seconds']:.1f}s)"
    if r["expect_case"] is not None:
        cmark = "ok" if r["case_ok"] else "SAI"
        detail += f" | case: mong={r['expect_case']} được={r['got_case']} ({cmark})"
    if r["error"]:
        detail += f" | LỖI: {r['error']}"
    return line + "\n" + detail


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    gap, prefixes = _parse_args(argv)
    cases = _select(prefixes)
    llm, registry, router = _build_parts()

    provider = (config.LLM_PROVIDER or "ollama")
    model = config.OLLAMA_MODEL if provider == "ollama" else config.LLM_MODEL
    print(f"=== EVAL: provider={provider} model={model} router={'on' if router else 'off'} "
          f"| {len(cases)} ca | nghỉ {gap:g}s/ca ===\n", flush=True)

    # Không router -> dùng prompt GỘP (base + mọi fragment case), KHÔNG phải base trần:
    # đo đúng thứ production sẽ chạy, nếu không sẽ chấm thiệt cho chế độ không-router.
    system = None if router else prompts.merged()

    results = []
    dt = 0.0                      # CHỈ cộng thời gian chạy ca, KHÔNG tính lúc nghỉ
    for i, c in enumerate(cases):
        t0 = time.time()
        r = run_case(llm, registry, router, c, system=system)
        dt += time.time() - t0
        results.append(r)
        print(_fmt_case(r), flush=True)
        if gap and i < len(cases) - 1:
            time.sleep(gap)

    s = summarize(results)
    print("\n=== TỔNG KẾT ===")
    print(f"Gọi đúng tool : {s['tool_pass']}/{s['total']}  ({s['tool_acc']*100:.0f}%)")
    if s["case_acc"] is not None:
        print(f"Phân loại case: {s['case_pass']}/{s['case_total']}  ({s['case_acc']*100:.0f}%)")
    # CHI PHÍ — con số cần theo dõi khi cắt bớt lượt LLM
    if s["avg_calls"] is not None:
        print(f"Số call LLM   : {s['total_calls']} tổng  ({s['avg_calls']:.2f} call/lượt)")
    if s["avg_seconds"] is not None:
        print(f"Chờ LLM       : {s['avg_seconds']:.1f}s/lượt")
    print(f"Thời gian     : {dt:.1f}s ({dt/max(1,len(cases)):.1f}s/ca)")
    # Không exit khác 0 — đây là ĐO LƯỜNG, không phải cổng CI.


if __name__ == "__main__":
    main()
