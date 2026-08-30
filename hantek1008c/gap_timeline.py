from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Iterable, Sequence


@dataclass(frozen=True)
class GapTimelineTriggered:
    triggered: int
    start_s: float
    end_s: float
    sample_count: int
    sample_duration_s: float
    cycle_elapsed_s: float
    gap_after_s: float


def build_gap_timeline(
    triggered_acquisitions: Sequence[Sequence[int]],
    triggered_start_s: Sequence[float],
    sample_rate_hz: float,
):
    """Build a gap-aware timeline from measured acquisition start times.

    ``triggered_start_s`` is the monotonic start time of each hardware acquisition,
    normalized or absolute. Real ADC samples are placed at 1/sample_rate_hz
    starting at that measured time. Missing time is therefore derived only from
    the interval between successive acquisition starts; no samples are invented.

    A single NaN marker is inserted between triggered_acquisitions when a positive gap exists so
    ordinary plotting does not draw a false edge across missing time. No gap is
    inferred after the final triggered because there is no following acquisition
    start with which to measure it.
    """
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if len(triggered_acquisitions) != len(triggered_start_s):
        raise ValueError("triggered_acquisitions and triggered_start_s must have equal length")
    if any(b < a for a, b in zip(triggered_start_s, triggered_start_s[1:])):
        raise ValueError("triggered_start_s must be monotonic")

    times: list[float] = []
    values: list[float] = []
    rows: list[GapTimelineTriggered] = []
    dt = 1.0 / sample_rate_hz
    origin = triggered_start_s[0] if triggered_start_s else 0.0

    for index, samples in enumerate(triggered_acquisitions):
        n = len(samples)
        sample_duration_s = n * dt
        start_s = triggered_start_s[index] - origin
        for i, value in enumerate(samples):
            times.append(start_s + i * dt)
            values.append(float(value))
        end_s = start_s + sample_duration_s

        if index + 1 < len(triggered_acquisitions):
            next_start_s = triggered_start_s[index + 1] - origin
            start_to_start_s = next_start_s - start_s
            gap_after_s = max(0.0, start_to_start_s - sample_duration_s)
        else:
            start_to_start_s = sample_duration_s
            gap_after_s = 0.0

        rows.append(GapTimelineTriggered(
            triggered=index + 1,
            start_s=start_s,
            end_s=end_s,
            sample_count=n,
            sample_duration_s=sample_duration_s,
            cycle_elapsed_s=start_to_start_s,
            gap_after_s=gap_after_s,
        ))
        if gap_after_s > 0:
            times.append(end_s + gap_after_s / 2.0)
            values.append(math.nan)

    return times, values, rows


def estimate_square_frequency_per_triggered_acquisition(
    samples: Sequence[int], sample_rate_hz: float
) -> tuple[float | None, int]:
    """Validation-only square frequency estimate using Schmitt crossings.

    This helper is intentionally outside the canonical acquisition/reconstruction
    path. It uses the known square-wave test source only to validate time-base
    preservation within individual real hardware triggered_acquisitions.
    """
    if len(samples) < 4:
        return None, 0
    lo = min(samples)
    hi = max(samples)
    span = hi - lo
    if span <= 0:
        return None, 0
    lower = lo + 0.25 * span
    upper = lo + 0.75 * span
    state = None
    rising: list[int] = []
    for i, value in enumerate(samples):
        if state is None:
            if value <= lower:
                state = 0
            elif value >= upper:
                state = 1
            continue
        if state == 0 and value >= upper:
            state = 1
            rising.append(i)
        elif state == 1 and value <= lower:
            state = 0
    periods = [b - a for a, b in zip(rising, rising[1:]) if b > a]
    if not periods:
        return None, len(rising)
    return sample_rate_hz / statistics.median(periods), len(rising)
