from pathlib import Path
import json

import numpy as np
import pytest

FIX = Path(__file__).parent / "fixtures" / "20260827_mfg92_reference"
CAPTURE = FIX / "20260827T083001Z_square-1khz-mfg92-reference_capture.json"


def load_words():
    meta = json.loads(CAPTURE.read_text())
    b3 = FIX / "20260827T083001Z_square-1khz-mfg92-reference_buffer03.bin"
    words = np.frombuffer(b3.read_bytes(), dtype="<u2") & 0x0FFF
    return meta, words.astype(float)


def a5_states():
    tx = FIX / "20260827T083001Z_square-1khz-mfg92-reference_capture-transactions.jsonl"
    states = []
    for line in tx.read_text().splitlines():
        row = json.loads(line)
        if row.get("tx_hex") == "A55A":
            rx = row.get("rx_hex", "")
            if len(rx) >= 4:
                states.append(int(rx[-2:], 16))
    return states


def test_full_reference_init_changes_buffer_layout_to_direct_adc_mode():
    meta, words = load_words()
    assert meta["mode"] == "mfg92-reference-full-init-experiment"
    assert meta["a3_hex"] == "11"
    assert meta["buffer02_bytes"] == 0
    assert meta["buffer03_bytes"] == 8000
    assert meta["word_count"] == 4000
    assert len(words) == 4000
    assert words.min() == 2001
    assert words.max() == 2206


def test_reference_burst_reaches_ready_state_before_readout():
    states = a5_states()
    # Calibration and final burst may each poll 1 -> 2; the important invariant
    # is that state 2 is observed rather than reading buffers while still state 0/1.
    assert 2 in states
    assert states[-1] == 2


def test_direct_adc_square_has_exact_400_sample_half_periods():
    _, words = load_words()
    # The two direct ADC plateaus are separated by a very wide gap, so a midpoint
    # threshold is a robust fixture characterization, not a production decoder rule.
    threshold = 2100.0
    high = words > threshold
    edges = np.flatnonzero(high[1:] != high[:-1]) + 1
    assert edges.tolist() == [312, 712, 1112, 1512, 1912, 2312, 2712, 3112, 3512, 3912]
    assert np.diff(edges).tolist() == [400] * 9
    sample_rate = 2.0 * 400.0 * 1000.0
    assert sample_rate == pytest.approx(800_000.0)


def test_direct_adc_plateaus_are_stable_without_integration_or_detrend():
    _, words = load_words()
    high = words > 2100.0
    edges = np.flatnonzero(high[1:] != high[:-1]) + 1
    quiet = np.ones(len(words), dtype=bool)
    for edge in edges:
        quiet[max(0, edge - 20):min(len(words), edge + 20)] = False
    low_values = words[quiet & ~high]
    high_values = words[quiet & high]

    assert np.mean(low_values) == pytest.approx(2005.619, abs=0.05)
    assert np.std(low_values) < 1.0
    assert np.mean(high_values) == pytest.approx(2201.388, abs=0.05)
    assert np.std(high_values) < 0.8
    assert np.mean(high_values) - np.mean(low_values) == pytest.approx(195.769, abs=0.1)
