"""Hai lớp eval: mẫu đại diện để đo hiệu năng + mẫu phủ để không bỏ quên tool hiếm."""

from conftest import full_registry

from evals.cases import ALL_CASES, CASES, COVERAGE_CASES
from evals.run_eval import _select


def test_hai_bo_khong_trung_id():
    ids = [case["id"] for case in ALL_CASES]
    assert len(ids) == len(set(ids))


def test_tat_ca_tool_catalog_deu_co_it_nhat_mot_ca_eval():
    """Tần suất thật có thể bằng 0; độ phủ hồi quy thì không được phép bằng 0."""
    catalog = set(full_registry().names())
    covered = {tool for case in ALL_CASES for tool in case.get("expect", [])}
    assert covered == catalog, (
        f"thiếu ca={sorted(catalog - covered)}; tên lạ={sorted(covered - catalog)}")


def test_chay_mac_dinh_van_giu_bo_dai_dien_de_so_sanh_so_do_cu():
    assert _select([]) is CASES
    assert _select(["cov"]) == COVERAGE_CASES
    assert _select(["all"]) == ALL_CASES
