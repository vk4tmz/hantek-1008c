import math
import pytest
from hantek1008c.gap_timeline import build_gap_timeline, estimate_square_frequency_per_triggered_acquisition


def test_gap_timeline_preserves_samples_and_uses_start_to_start_spacing():
    triggered_acquisitions = [[1,2,3,4], [5,6,7,8], [9,10,11,12]]
    starts = [10.000, 10.010, 10.022]
    times, values, rows = build_gap_timeline(triggered_acquisitions, starts, 1000.0)
    assert [v for v in values if not math.isnan(v)] == list(range(1,13))
    assert sum(math.isnan(v) for v in values) == 2
    assert rows[0].sample_duration_s == pytest.approx(0.004)
    assert rows[0].cycle_elapsed_s == pytest.approx(0.010)
    assert rows[0].gap_after_s == pytest.approx(0.006)
    assert rows[1].start_s == pytest.approx(0.010)
    assert rows[1].gap_after_s == pytest.approx(0.008)
    assert rows[2].start_s == pytest.approx(0.022)
    assert rows[2].gap_after_s == 0.0


def test_gap_timeline_rejects_nonmonotonic_starts():
    with pytest.raises(ValueError):
        build_gap_timeline([[1], [2]], [2.0, 1.0], 1000.0)


def test_square_frequency_validator_is_per_triggered_acquisition_only():
    samples = []
    for _ in range(10):
        samples.extend([100] * 50)
        samples.extend([900] * 50)
    freq, rises = estimate_square_frequency_per_triggered_acquisition(samples, 100000.0)
    assert rises >= 9
    assert freq == pytest.approx(1000.0)
