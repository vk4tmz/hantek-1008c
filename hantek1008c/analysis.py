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
