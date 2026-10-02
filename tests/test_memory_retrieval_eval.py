"""Regression gate cho Phase 4-lite memory retrieval."""

import json
from pathlib import Path

from evals.memory_cases import MEMORY_RETRIEVAL_CASES
from evals.memory_retrieval import analyze_traced_outcomes, evaluate_memory_retrieval


def test_benchmark_co_du_30_den_50_case_va_khong_trung_id():
    assert 30 <= len(MEMORY_RETRIEVAL_CASES) <= 50
    ids = [case["id"] for case in MEMORY_RETRIEVAL_CASES]
    assert len(ids) == len(set(ids))


def test_evaluator_tinh_dung_recall_precision_va_leakage():
    cases = [{
        "id": "tiny", "tag": "test", "query": "cà phê",
        "facts": [
            {"id": "right", "source": "notes", "text": "thích cà phê"},
            {"id": "wrong", "source": "notes", "text": "ghét cà phê"},
            {"id": "expired", "source": "notes", "text": "cà phê", "expired": True},
        ],
        "expected": ["right"], "forbidden": ["wrong"],
    }]
    report = evaluate_memory_retrieval(cases, k=5)
    assert report["recall_at_k"] == 1.0
    assert report["precision_at_k"] == 0.5
    assert report["forbidden_leakage_rate"] == 1.0
    assert report["ineligible_leakage_rate"] == 0.0


def test_production_retrieval_khong_thut_lui_so_voi_baseline():
    baseline_path = Path(__file__).parent / "fixtures" / "memory_retrieval_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    report = evaluate_memory_retrieval(k=baseline["k"])
    assert report["case_count"] == baseline["case_count"]
    assert report["recall_at_k"] >= baseline["recall_at_k"]
    assert report["precision_at_k"] >= baseline["precision_at_k"]
    assert report["case_pass_rate"] >= baseline["case_pass_rate"]
    assert report["forbidden_leakage_rate"] <= baseline["forbidden_leakage_rate"]
    assert report["ineligible_leakage_rate"] <= baseline["ineligible_leakage_rate"]


def test_outcome_analysis_khong_bien_tuong_quan_thanh_nhan_qua():
    records = [
        {"ket_qua": "xong", "memory_retrieval": {"selected_count": 2}},
        {"ket_qua": "loi_tool", "memory_retrieval": {"selected_count": 0}},
        {"ket_qua": "xong"},
    ]
    report = analyze_traced_outcomes(records)
    assert report["traced_outcomes"] == 2
    assert report["memory_used_outcomes"] == 1
    assert report["traced_success_rate"] == 0.5
    assert report["interpretation"] == "observational_only_not_causal"
