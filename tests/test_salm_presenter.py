from features.salm.presenter import care_opacity, care_progress_steps


def test_care_pulse_starts_and_ends_at_user_opacity_and_only_dims():
    values = [care_opacity(0.7, progress) for progress in care_progress_steps()]
    assert values[0] == 0.7
    assert values[-1] == 0.7
    assert min(values) >= 0.7 * 0.82
    assert max(values) <= 0.7


def test_care_opacity_clamps_inputs():
    assert care_opacity(2, -1) == 1
    assert care_opacity(-1, 0.5) == 0
