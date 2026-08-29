from __future__ import annotations

"""Offline timing-validation helpers for official C9/CA Scan evidence.

These helpers are for validating a known periodic test stimulus.  They are not
part of waveform reconstruction and must not be used to clean, alter, select,
or otherwise transform acquired samples.
"""

import statistics


def mean_upward_crossing_positions(samples: list[int] | list[float]) -> list[float]:
    """Return linearly interpolated upward crossings of the sample mean.

    This intentionally simple estimator is suitable for the controlled 20 Hz
    sine validation capture.  It is not a general acquisition decoder.
    """
    if len(samples) < 2:
        return []
    level = statistics.mean(samples)
    positions: list[float] = []
    for i, (a, b) in enumerate(zip(samples, samples[1:])):
        da = a - level
        db = b - level
        if da < 0 <= db and b != a:
            fraction = (level - a) / (b - a)
            positions.append(i + fraction)
    return positions


def estimate_reference_frequency(
    samples: list[int] | list[float], sample_rate_hz: float
) -> tuple[float, float, int]:
    """Estimate periodic frequency from upward mean-crossing intervals.

    Returns ``(frequency_hz, median_period_samples, interval_count)``.
    """
    if sample_rate_hz <= 0:
        raise ValueError(f"sample rate must be > 0, got {sample_rate_hz}")
    crossings = mean_upward_crossing_positions(samples)
    periods = [b - a for a, b in zip(crossings, crossings[1:]) if b > a]
    if not periods:
        raise ValueError("not enough upward crossings to estimate frequency")
    median_period = statistics.median(periods)
    return sample_rate_hz / median_period, median_period, len(periods)
