from pathlib import Path
import json

import numpy as np
import pytest

from hantek1008c.analysis import reconstruct_continuous_delta
from hantek1008c.offline import square_sample_rate

FIX = Path(__file__).parent / "fixtures" / "20260827_bias_lab"
GROUND = FIX / "20260827T075115Z_grounded-a3-0f_capture.json"
SQUARE = FIX / "20260827T074648Z_square-1khz-a3-0f-fresh_capture.json"


def load_capture(path):
    meta = json.loads(path.read_text())
    b2 = path.parent / Path(meta["buffer02"]["file"]).name
    b3 = path.parent / Path(meta["buffer03"]["file"]).name
    words = np.frombuffer(b2.read_bytes() + b3.read_bytes(), dtype="<u2").astype(float)
    return meta, words


def a5_replies(path):
    replies = []
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if row.get("tx_hex") == "A55A":
            replies.append(row.get("rx_hex"))
    return replies


def test_canonical_captures_are_same_healthy_24msps_mode():
    for path in (GROUND, SQUARE):
        meta, words = load_capture(path)
        cfg = meta["resolved_configuration"]
        assert cfg["a3_hex"] == "0F"
        assert cfg["a0_active_channel_count"] == 1
        assert cfg["active_channels"] == [1]
        assert cfg["a2_ranges_hex"] == ["03"] * 8
        assert meta["buffer02"]["reported_size_bytes"] == 500
        assert meta["buffer03"]["reported_size_bytes"] == 7500
        assert len(words) == 4000

        tx = path.parent / Path(meta["transaction_log"]).name
        assert a5_replies(tx) == ["A502", "A502"]


def test_grounded_raw_stream_has_stable_two_phase_offset():
    _, words = load_capture(GROUND)
    even = words[0::2]
    odd = words[1::2]

    assert np.ptp(words) <= 6
    assert np.std(words) < 0.8
    assert np.mean(even) - np.mean(odd) == pytest.approx(0.871, abs=0.03)


def test_clean_square_confirms_24msps_from_raw_edges():
    _, words = load_capture(SQUARE)
    rate, centers, center, threshold = square_sample_rate(
        words, 1000.0, center=2003, threshold=8
    )

    assert center == 2003
    assert threshold == 8
    assert centers == pytest.approx([774.5, 1974.5, 3174.5], abs=2.0)
    assert np.diff(centers) == pytest.approx([1200.0, 1200.0], abs=2.0)
    assert rate == pytest.approx(2_400_000.0, abs=4_000.0)


def test_quiet_square_regions_retain_level_dependent_delta_center_shift():
    """Preserve the defect evidence without applying waveform-specific cleanup."""
    _, words = load_capture(SQUARE)
    # Windows are deliberately far from the known transitions. They quantify
    # the current raw encoding behaviour; they are not a reconstruction rule.
    windows = [(100, 650), (900, 1850), (2100, 3050), (3300, 3900)]
    means = np.array([np.mean(words[a:b]) for a, b in windows])

    # Alternating plateaus have two repeatable quiet centres separated by ~0.1 count.
    assert means[[0, 2]].mean() - means[[1, 3]].mean() == pytest.approx(0.106, abs=0.03)


def test_phase_only_ground_calibration_is_not_accepted_as_the_fix():
    """Document the failed A/B: even/odd calibration alone does not remove slopes."""
    _, ground = load_capture(GROUND)
    _, square = load_capture(SQUARE)

    current, _ = reconstruct_continuous_delta(square)
    current = np.asarray(current)

    phase_zero = np.array([np.mean(ground[0::2]), np.mean(ground[1::2])])
    idx = np.arange(len(square))
    phase_delta = square - np.where(idx % 2 == 0, phase_zero[0], phase_zero[1])
    phase = np.cumsum(phase_delta)

    windows = [(100, 650), (900, 1850), (2100, 3050), (3300, 3900)]

    def mean_abs_slope(y):
        slopes = []
        for a, b in windows:
            x = np.arange(a, b, dtype=float)
            slopes.append(np.polyfit(x, y[a:b], 1)[0])
        return float(np.mean(np.abs(slopes)))

    # A phase-only correction is not an improvement over the existing path;
    # this prevents accidentally promoting today's rejected hypothesis.
    assert mean_abs_slope(phase) >= mean_abs_slope(current)
