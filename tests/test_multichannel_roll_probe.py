from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "probe_multichannel_roll.py"
spec = importlib.util.spec_from_file_location("probe_multichannel_roll", SCRIPT)
assert spec is not None
assert spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_default_matrix_contains_contiguous_and_sparse_cases():
    sets = probe.default_channel_sets()
    assert sets[:8] == tuple(tuple(range(1, n + 1)) for n in range(8, 0, -1))
    assert (1, 8) in sets
    assert (1, 5, 8) in sets


def test_candidate_views_keep_three_interpretations_separate():
    raw = b"".join(value.to_bytes(2, "little") for value in range(24))
    views = probe.candidate_views(raw, 3)
    assert views["all_words_enabled_count"]["complete_rows"] == 8
    assert views["historical_word0_enabled_count"]["complete_rows"] == 4
    assert views["paired_words_per_enabled_channel"]["complete_rows"] == 4
    assert views["all_words_triggered_padded_width"]["width"] == 4
