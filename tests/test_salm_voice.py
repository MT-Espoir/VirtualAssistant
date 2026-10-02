"""Contract ghép persona chung vào lane lời nói SALM."""

from features.salm.voice import compose_speech_system


def test_compose_speech_system_keeps_persona_and_lane_contract():
    result = compose_speech_system(
        "Không được chẩn đoán sức khỏe.",
        lambda: "Bạn là một quản gia hoạt bát.")
    assert result.index("quản gia hoạt bát") < result.index("Không được chẩn đoán")
    assert "luôn được ưu tiên" in result


def test_compose_speech_system_degrades_when_provider_fails():
    def broken():
        raise RuntimeError("hỏng")

    contract = "contract gốc"
    assert compose_speech_system(contract, broken) == contract
    assert compose_speech_system(contract, lambda: None) == contract
