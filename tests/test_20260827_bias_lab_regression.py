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


def _linear_detrend(values):
    y = np.asarray(values, dtype=float)
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    return y - (slope * x + intercept)


def _clean_deltas_like_current_decoder(words, limit=64.0):
    words = np.asarray(words, dtype=float)
    zero = float(np.median(words))
    deltas = words - zero
    cleaned = deltas.copy()
    for i, value in enumerate(deltas):
        if abs(value) <= limit:
            continue
        lo = max(0, i - 4)
        hi = min(len(deltas), i + 5)
        nearby = deltas[lo:hi]
        good = nearby[np.abs(nearby) <= limit]
        cleaned[i] = float(np.median(good)) if len(good) else 0.0
    return cleaned


def _reconstruct_leaky_delta(words, retention):
    """Experimental rejected hypothesis: inverse of a leaky first-difference."""
    deltas = _clean_deltas_like_current_decoder(words)
    out = np.empty(len(deltas), dtype=float)
    acc = 0.0
    for i, delta in enumerate(deltas):
        acc = retention * acc + delta
        out[i] = acc
    return _linear_detrend(out)


def _sine_fit_correlation(values, frequency_hz, sample_rate=2_400_400.0):
    y = np.asarray(values, dtype=float)
    t = np.arange(len(y), dtype=float) / sample_rate
    design = np.column_stack([
        np.ones(len(y)),
        np.sin(2 * np.pi * frequency_hz * t),
        np.cos(2 * np.pi * frequency_hz * t),
    ])
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    fitted = design @ beta
    return float(np.corrcoef(y, fitted)[0, 1])


def test_rejected_leaky_integrator_tradeoff_breaks_sine_fidelity():
    """A square-flattening leaky integrator is not waveform-agnostic enough.

    retention=0.99966 was the offline square-optimal value on the 2026-08-27
    fixture.  It roughly halves the square plateau slope metric, but degrades
    the independent 2 kHz sine regression substantially.  Preserve this
    negative result so the hypothesis is not accidentally promoted later.
    """
    _, square = load_capture(SQUARE)
    current_square, _ = reconstruct_continuous_delta(square)
    leaky_square = _reconstruct_leaky_delta(square, 0.99966)

    windows = [(100, 650), (900, 1850), (2100, 3050), (3300, 3900)]

    def mean_abs_slope(y):
        y = np.asarray(y, dtype=float)
        slopes = []
        for a, b in windows:
            x = np.arange(a, b, dtype=float)
            slopes.append(np.polyfit(x, y[a:b], 1)[0])
        return float(np.mean(np.abs(slopes)))

    assert mean_abs_slope(leaky_square) < 0.6 * mean_abs_slope(current_square)

    sine_json = Path(__file__).parent / "fixtures" / "sine_2k_8k" / "20260825T090035Z_sine-2khz-ch1-a3-0f_capture.json"
    _, sine = load_capture(sine_json)
    current_sine, _ = reconstruct_continuous_delta(sine)
    leaky_sine = _reconstruct_leaky_delta(sine, 0.99966)

    current_corr = _sine_fit_correlation(current_sine, 2000.0)
    leaky_corr = _sine_fit_correlation(leaky_sine, 2000.0)

    assert current_corr > 0.94
    assert leaky_corr < 0.80
    assert leaky_corr < 0.85 * current_corr


def test_pair_averaging_phase_bias_does_not_fix_square_plateau_drift():
    """Removing the measured even/odd phase offset is a secondary calibration only.

    Adjacent-pair averaging nearly cancels the two-phase raw-code offset while
    preserving the 4000-sample timeline.  It leaves the square plateau drift
    metric essentially unchanged, so phase alternation is not the root cause.
    """
    _, square = load_capture(SQUARE)
    pair_corrected = np.asarray(square, dtype=float).copy()
    pair_means = (pair_corrected[0::2] + pair_corrected[1::2]) / 2.0
    pair_corrected[0::2] = pair_means
    pair_corrected[1::2] = pair_means

    current, _ = reconstruct_continuous_delta(square)
    corrected, _ = reconstruct_continuous_delta(pair_corrected)

    windows = [(100, 650), (900, 1850), (2100, 3050), (3300, 3900)]

    def mean_abs_slope(y):
        y = np.asarray(y, dtype=float)
        return float(np.mean([
            abs(np.polyfit(np.arange(a, b, dtype=float), y[a:b], 1)[0])
            for a, b in windows
        ]))

    current_metric = mean_abs_slope(current)
    corrected_metric = mean_abs_slope(corrected)
    assert corrected_metric == pytest.approx(current_metric, rel=0.01)
