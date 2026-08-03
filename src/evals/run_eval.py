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
from agent.router import Router
from agent.tools import build_default_registry
from utils.config import config
from evals.cases import CASES
from evals.harness import run_case, summarize


class _StubDep:
    """Phụ thuộc giả cho scheduler/browser/screen — CHỈ để đăng ký đủ tool (specs);
    handler không bao giờ chạy thật vì RecordingRegistry không thực thi."""
    def __getattr__(self, _name):
        return lambda *a, **k: None


def _build_parts():
    llm = build_default_llm_client()
    # Truyền phụ thuộc giả để MỌI nhóm tool được đăng ký (web/system/screen/browser/
    # schedule/weather) -> LLM thấy đúng bộ tool như lúc chạy thật.
    registry = build_default_registry(AssistantActions(), scheduler=_StubDep(),
                                      browser=_StubDep(), screen=_StubDep(),
                                      tasks=_StubDep(), routines=_StubDep())
    router = Router(llm) if config.USE_ROUTER else None
    return llm, registry, router


def _select(prefixes):
    if not prefixes:
        return CASES
    return [c for c in CASES if any(c["id"].startswith(p) for p in prefixes)]


def _fmt_case(r):
    mark = "PASS" if r["tool_ok"] else "FAIL"
    line = f"{mark} [{r['id']:<10}] {r['text']}"
    detail = f"    mong đợi tool={r['expect']} | đã gọi={r['called']}"
    if r["expect_case"] is not None:
        cmark = "ok" if r["case_ok"] else "SAI"
        detail += f" | case: mong={r['expect_case']} được={r['got_case']} ({cmark})"
    if r["error"]:
        detail += f" | LỖI: {r['error']}"
    return line + "\n" + detail


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cases = _select(argv)
    llm, registry, router = _build_parts()

    provider = (config.LLM_PROVIDER or "ollama")
    model = config.OLLAMA_MODEL if provider == "ollama" else config.LLM_MODEL
    print(f"=== EVAL: provider={provider} model={model} router={'on' if router else 'off'} "
          f"| {len(cases)} ca ===\n")

    results = []
    t0 = time.time()
    for c in cases:
        r = run_case(llm, registry, router, c)
        results.append(r)
        print(_fmt_case(r))
    dt = time.time() - t0

    s = summarize(results)
    print("\n=== TỔNG KẾT ===")
    print(f"Gọi đúng tool : {s['tool_pass']}/{s['total']}  ({s['tool_acc']*100:.0f}%)")
    if s["case_acc"] is not None:
        print(f"Phân loại case: {s['case_pass']}/{s['case_total']}  ({s['case_acc']*100:.0f}%)")
    print(f"Thời gian     : {dt:.1f}s ({dt/max(1,len(cases)):.1f}s/ca)")
    # Không exit khác 0 — đây là ĐO LƯỜNG, không phải cổng CI.


if __name__ == "__main__":
    main()
