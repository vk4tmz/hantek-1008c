from __future__ import annotations

from dataclasses import dataclass
import math
import statistics


@dataclass
class PeriodicityResult:
    mean: float
    rms_ac: float
    span: int
    dominant_period_samples: int | None
    dominant_corr: float | None
    event_indices: list[int]
    event_spacings: list[int]


def _rms_ac(values):
    if not values:
        return 0.0
    mean = statistics.fmean(values)
    return math.sqrt(statistics.fmean((x - mean) ** 2 for x in values))


def normalized_autocorr(values, lag):
    n = len(values)
    if lag <= 0 or lag >= n:
        return None

    x = values[:-lag]
    y = values[lag:]
    mx = statistics.fmean(x)
    my = statistics.fmean(y)

    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denx = sum((a - mx) ** 2 for a in x)
    deny = sum((b - my) ** 2 for b in y)
    den = math.sqrt(denx * deny)

    if den == 0:
        return 0.0
    return num / den


def dominant_period(values, min_lag=8, max_lag=None):
    n = len(values)
    if n < 2 * min_lag:
        return None, None

    if max_lag is None:
        max_lag = min(n // 2, 250)
    max_lag = min(max_lag, n - 1)

    # We are interested in repeating acquisition structure, not the trivially
    # high correlation of adjacent samples. Start at a modest lag.
    scored = []
    for lag in range(min_lag, max_lag + 1):
        corr = normalized_autocorr(values, lag)
        if corr is not None:
            scored.append((corr, lag))

    if not scored:
        return None, None

    corr, lag = max(scored)
    return lag, corr


def detect_events(values):
    """Find isolated excursions robustly using median/MAD.

    This is intentionally conservative. It is useful for the current Hantek
    calibration trace, where the driven channel contains periodic narrow
    excursions while undriven channels remain near baseline.
    """
    if not values:
        return []

    med = statistics.median(values)
    deviations = [abs(v - med) for v in values]
    mad = statistics.median(deviations)

    # ADC noise on quiet channels is only a few counts. Keep a floor so MAD=0
    # does not turn every 1-count fluctuation into an event.
    threshold = max(6.0, 6.0 * mad)

    candidates = [
        i for i, v in enumerate(values)
        if abs(v - med) >= threshold
    ]

    if not candidates:
        return []

    # Collapse adjacent candidate samples into one event, keeping the sample
    # with greatest absolute deviation from median.
    groups = []
    group = [candidates[0]]
    for idx in candidates[1:]:
        if idx <= group[-1] + 1:
            group.append(idx)
        else:
            groups.append(group)
            group = [idx]
    groups.append(group)

    events = []
    for group in groups:
        best = max(group, key=lambda i: abs(values[i] - med))
        events.append(best)

    return events


def analyze_periodicity(values):
    vals = list(values)
    if not vals:
        return PeriodicityResult(0.0, 0.0, 0, None, None, [], [])

    period, corr = dominant_period(vals)
    events = detect_events(vals)
    spacings = [b - a for a, b in zip(events, events[1:])]

    return PeriodicityResult(
        mean=statistics.fmean(vals),
        rms_ac=_rms_ac(vals),
        span=max(vals) - min(vals),
        dominant_period_samples=period,
        dominant_corr=corr,
        event_indices=events,
        event_spacings=spacings,
    )


@dataclass
class SquareWaveEdges:
    low_level: float
    high_level: float
    low_threshold: float
    high_threshold: float
    edge_indices: list[int]
    edge_spacings: list[int]
    median_half_period: float | None
    period_samples: float | None
    sample_rate: float | None


def _percentile(values, q: float) -> float:
    vals = sorted(values)
    if not vals:
        raise ValueError("percentile of empty data")
    if len(vals) == 1:
        return float(vals[0])
    pos = (len(vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(vals[lo])
    frac = pos - lo
    return vals[lo] * (1.0 - frac) + vals[hi] * frac


def detect_square_edges(
    values,
    *,
    frequency_hz: float | None = None,
    persistence: int = 8,
    min_separation: int | None = None,
) -> SquareWaveEdges:
    """Detect only major HIGH/LOW transitions in a square-wave capture.

    The Hantek calibration output can ring around an edge, so a single midpoint
    threshold creates many false crossings.  Estimate the two plateaus from
    robust percentiles, use Schmitt-like thresholds at 35%/65% of the level
    span, require a crossing to persist, and reject implausibly close edges.

    A rate is reported only with at least three accepted edges (two adjacent
    half-period measurements).  This deliberately fails closed for records
    containing too little of the 1 kHz waveform.
    """
    vals = list(values)
    if len(vals) < max(16, persistence * 2):
        return SquareWaveEdges(0, 0, 0, 0, [], [], None, None, None)

    # Using broad plateau percentiles is more robust to overshoot/ringing than
    # min/max, while still working with the small (~tens of counts) ADC span.
    low_level = _percentile(vals, 0.20)
    high_level = _percentile(vals, 0.80)
    span = high_level - low_level
    if span < 4:
        return SquareWaveEdges(low_level, high_level, low_level, high_level, [], [], None, None, None)

    low_thr = low_level + 0.35 * span
    high_thr = low_level + 0.65 * span
    midpoint = (low_thr + high_thr) / 2.0

    if min_separation is None:
        # A 4000-sample record of the 1 kHz calibration signal should never
        # contain legitimate edges this close in our current timebase sweep.
        # 2.5% of the record = 100 samples, comfortably below the known
        # A3=11 half-period (~400 samples).
        min_separation = max(16, len(vals) // 40)

    state = "high" if vals[0] >= midpoint else "low"
    edges: list[int] = []
    i = 1
    last_edge = -10**9
    while i <= len(vals) - persistence:
        if state == "low":
            crossed = all(v >= high_thr for v in vals[i:i + persistence])
            if crossed and i - last_edge >= min_separation:
                edges.append(i)
                last_edge = i
                state = "high"
                i += persistence
                continue
        else:
            crossed = all(v <= low_thr for v in vals[i:i + persistence])
            if crossed and i - last_edge >= min_separation:
                edges.append(i)
                last_edge = i
                state = "low"
                i += persistence
                continue
        i += 1

    spacings = [b - a for a, b in zip(edges, edges[1:])]
    half = period = rate = None
    if len(spacings) >= 2:
        # Median tolerates a partially clipped first/last plateau and small
        # trigger-position variation without treating ringing as an edge.
        half = float(statistics.median(spacings))
        period = 2.0 * half
        if frequency_hz is not None:
            rate = period * frequency_hz

    return SquareWaveEdges(
        low_level=low_level,
        high_level=high_level,
        low_threshold=low_thr,
        high_threshold=high_thr,
        edge_indices=edges,
        edge_spacings=spacings,
        median_half_period=half,
        period_samples=period,
        sample_rate=rate,
    )
