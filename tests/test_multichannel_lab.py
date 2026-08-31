import math

import pytest

from hantek1008c.multichannel import (
    acquisition_layout,
    candidate_geometry,
    compact_enabled_rows,
    contiguous_mask,
    deinterleave_words,
    estimate_period_generic,
    make_plan,
    mask_for_channels,
    observed_windows_width,
)


def test_observed_windows_width_table_is_exact_evidence_table():
    assert [observed_windows_width(n) for n in range(1, 9)] == [1, 2, 4, 4, 6, 6, 8, 8]


@pytest.mark.parametrize("bad", [0, 9, -1])
def test_observed_windows_width_rejects_invalid_counts(bad):
    with pytest.raises(ValueError):
        observed_windows_width(bad)


def test_sparse_channel_mask_preserves_physical_positions():
    assert mask_for_channels((1, 8)) == (1, 0, 0, 0, 0, 0, 0, 1)
    assert mask_for_channels((2, 5, 7)) == (0, 1, 0, 0, 1, 0, 1, 0)


def test_contiguous_width_mask():
    assert contiguous_mask(6) == (1, 1, 1, 1, 1, 1, 0, 0)


@pytest.mark.parametrize(
    "n,a0,aa_channels",
    [
        (1, 1, (1,)), (2, 2, (1, 2)), (3, 4, (1, 2, 3, 4)),
        (4, 4, (1, 2, 3, 4)), (5, 6, (1, 2, 3, 4, 5, 6)),
        (6, 6, (1, 2, 3, 4, 5, 6)), (7, 8, tuple(range(1, 9))),
        (8, 8, tuple(range(1, 9))),
    ],
)
def test_windows_width_plan_matches_observed_geometry(n, a0, aa_channels):
    plan = make_plan(tuple(range(1, n + 1)), a0_mode="width", aa_mode="width")
    assert plan.a0 == a0
    assert plan.aa_channels == aa_channels


@pytest.mark.parametrize(
    "a0_mode,aa_mode,expected_a0,expected_aa",
    [
        ("logical", "logical", 5, (1, 2, 3, 4, 5)),
        ("width", "logical", 6, (1, 2, 3, 4, 5)),
        ("logical", "width", 5, (1, 2, 3, 4, 5, 6)),
        ("width", "width", 6, (1, 2, 3, 4, 5, 6)),
    ],
)
def test_odd_boundary_semantics_matrix_is_expressible(a0_mode, aa_mode, expected_a0, expected_aa):
    plan = make_plan((1, 2, 3, 4, 5), a0_mode=a0_mode, aa_mode=aa_mode)
    assert plan.a0 == expected_a0
    assert plan.aa_channels == expected_aa


def test_width_mode_rejects_sparse_logical_mask():
    with pytest.raises(ValueError):
        make_plan((1, 8), a0_mode="logical", aa_mode="width")


def test_six_lane_deinterleave_preserves_all_4000_words_without_padding():
    words = list(range(4000))
    lanes = deinterleave_words(words, 6)
    assert [len(x) for x in lanes] == [667, 667, 667, 667, 666, 666]
    rebuilt = []
    for i in range(max(map(len, lanes))):
        for lane in lanes:
            if i < len(lane):
                rebuilt.append(lane[i])
    assert rebuilt == words


def _sine(samples, period):
    return [2048 + 500 * math.sin(2 * math.pi * i / period) for i in range(samples)]


def _square(samples, period):
    half = period // 2
    return [2500 if (i % period) < half else 1500 for i in range(samples)]


@pytest.mark.parametrize("factory", [_sine, _square])
def test_generic_period_estimator_validates_multiple_waveform_shapes(factory):
    values = factory(4000, 80)
    result = estimate_period_generic(values, reference_frequency_hz=1000.0)
    assert result.period_samples == pytest.approx(80.0, abs=0.2)
    assert result.rate_hz == pytest.approx(80_000.0, rel=0.003)
    assert result.correlation is not None and result.correlation > 0.9


def test_generic_period_estimator_does_not_invent_rate_for_flat_signal():
    result = estimate_period_generic([2048] * 1000, reference_frequency_hz=1000.0)
    assert result.period_samples is None
    assert result.rate_hz is None


def test_candidate_geometry_reports_unequal_six_lane_lengths():
    rows = candidate_geometry(list(range(4000)), reference_lane=0, reference_frequency_hz=1000.0)
    row6 = next(row for row in rows if row["lane_count"] == 6)
    assert row6["lane_lengths"] == [667, 667, 667, 667, 666, 666]


def test_verified_sparse_layout_is_compact_and_uses_count_width():
    channels, width = acquisition_layout((1, 8))
    assert channels == (1, 8)
    assert width == 2


@pytest.mark.parametrize("channels,width", [
    ((1, 2, 3), 4),
    ((1, 2, 3, 4, 5), 6),
    ((1, 2, 3, 4, 5, 6, 7), 8),
])
def test_verified_odd_layout_has_one_final_dummy_slot(channels, width):
    assert acquisition_layout(channels) == (channels, width)


def test_compact_enabled_rows_discards_dummy_and_partial_tail():
    # Four-wide rows: CH1, CH8, dummy-like extra slots are represented here by
    # a three-channel logical layout plus final dummy.  The trailing incomplete
    # row is deliberately ignored to preserve equal channel lengths.
    words = [10, 20, 30, 99, 11, 21, 31, 98, 12, 22]
    assert compact_enabled_rows(words, (1, 2, 3)) == [
        [10, 11], [20, 21], [30, 31]
    ]


def test_compact_enabled_rows_sparse_channel_order():
    words = [100, 800, 101, 801]
    assert compact_enabled_rows(words, (1, 8)) == [[100, 101], [800, 801]]
