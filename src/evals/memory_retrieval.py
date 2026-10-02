"""Đánh giá retrieval memory và phân tích outcome có trace (Phase 4-lite).

Chạy: ``cd src`` rồi ``python -m evals.memory_retrieval``.
"""

import json
from collections import defaultdict

from memory.profile import rank_memory_entries
from evals.memory_cases import MEMORY_RETRIEVAL_CASES


def _eligible(fact):
    return (fact.get("eligible", True) is not False
            and fact.get("expired", False) is not True
            and fact.get("status", "active") == "active")


def evaluate_memory_retrieval(cases=None, k=5):
    """Chạy benchmark, trả metrics micro và chẩn đoán từng case."""
    cases = list(cases if cases is not None else MEMORY_RETRIEVAL_CASES)
    totals = defaultdict(int)
    by_tag = defaultdict(lambda: {"cases": 0, "passed": 0})
    details = []

    for case in cases:
        allowed = [fact for fact in case["facts"] if _eligible(fact)]
        excluded_ids = {str(fact["id"]) for fact in case["facts"] if not _eligible(fact)}
        selected = rank_memory_entries(allowed, case["query"], k)
        selected_ids = [str(item["id"]) for item in selected]
        expected = set(map(str, case.get("expected") or []))
        forbidden = set(map(str, case.get("forbidden") or []))
        found = expected.intersection(selected_ids)
        leaked = forbidden.intersection(selected_ids)
        ineligible = excluded_ids.intersection(selected_ids)
        passed = found == expected and not leaked and not ineligible
        tag = case.get("tag", "other")

        totals["expected"] += len(expected)
        totals["selected"] += len(selected_ids)
        totals["relevant_selected"] += len(found)
        totals["forbidden_total"] += len(forbidden)
        totals["forbidden_leaked"] += len(leaked)
        totals["ineligible_total"] += len(excluded_ids)
        totals["ineligible_leaked"] += len(ineligible)
        totals["passed"] += int(passed)
        by_tag[tag]["cases"] += 1
        by_tag[tag]["passed"] += int(passed)
        details.append({
            "id": case["id"], "tag": tag, "passed": passed,
            "expected": sorted(expected), "selected": selected_ids,
            "missing": sorted(expected - found), "forbidden_leaked": sorted(leaked),
            "ineligible_leaked": sorted(ineligible),
        })

    count = len(cases)
    recall = totals["relevant_selected"] / totals["expected"] if totals["expected"] else 1.0
    precision = (totals["relevant_selected"] / totals["selected"]
                 if totals["selected"] else 1.0)
    forbidden_rate = (totals["forbidden_leaked"] / totals["forbidden_total"]
                      if totals["forbidden_total"] else 0.0)
    ineligible_rate = (totals["ineligible_leaked"] / totals["ineligible_total"]
                       if totals["ineligible_total"] else 0.0)
    return {
        "benchmark_version": 1,
        "k": k,
        "case_count": count,
        "recall_at_k": round(recall, 4),
        "precision_at_k": round(precision, 4),
        "case_pass_rate": round(totals["passed"] / count, 4) if count else 1.0,
        "forbidden_leakage_rate": round(forbidden_rate, 4),
        "ineligible_leakage_rate": round(ineligible_rate, 4),
        "counts": dict(totals),
        "by_tag": dict(by_tag),
        "details": details,
    }


def analyze_traced_outcomes(records):
    """Tóm tắt outcome có trace; chỉ là tương quan, không tuyên bố quan hệ nhân quả."""
    traced = []
    for record in records or []:
        trace = record.get("memory_retrieval")
        if isinstance(trace, dict):
            traced.append(record)
    used = [r for r in traced if r["memory_retrieval"].get("selected_count", 0) > 0]

    def _success_rate(rows):
        if not rows:
            return None
        successful = sum(r.get("ket_qua") == "xong" for r in rows)
        return round(successful / len(rows), 4)

    return {
        "total_outcomes": len(records or []),
        "traced_outcomes": len(traced),
        "memory_used_outcomes": len(used),
        "traced_success_rate": _success_rate(traced),
        "memory_used_success_rate": _success_rate(used),
        "interpretation": "observational_only_not_causal",
    }


def main():
    print(json.dumps(evaluate_memory_retrieval(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
