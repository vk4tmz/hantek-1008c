from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Iterable, Sequence


# Independently hardware-validated at A3=0x11 on 2026-08-30 and A3=0x0F on 2026-09-01.
VERIFIED_ACQUISITION_WIDTH = {1: 1, 2: 2, 3: 4, 4: 4, 5: 6, 6: 6, 7: 8, 8: 8}
# Backward-compatible name retained for protocol-lab reports created before validation.
WINDOWS_OBSERVED_WIDTH = VERIFIED_ACQUISITION_WIDTH


def observed_windows_width(logical_count: int) -> int:
    """Return the hardware-validated direct-ADC acquisition width.

    The function name is retained for compatibility with earlier lab tooling;
    the 1,2,4,4,6,6,8,8 table is independently validated at A3=0x11 and 0x0F.
    """
    try:
        return WINDOWS_OBSERVED_WIDTH[int(logical_count)]
    except (KeyError, ValueError) as exc:
        raise ValueError("logical_count must be 1..8") from exc


def mask_for_channels(channels: Iterable[int]) -> tuple[int, ...]:
    ids = sorted(set(int(ch) for ch in channels))
    if not ids or any(ch < 1 or ch > 8 for ch in ids):
        raise ValueError("channels must contain one or more values in 1..8")
    return tuple(1 if ch in ids else 0 for ch in range(1, 9))


def contiguous_mask(width: int) -> tuple[int, ...]:
    if not 1 <= int(width) <= 8:
        raise ValueError("width must be 1..8")
    return tuple(1 if ch <= int(width) else 0 for ch in range(1, 9))


@dataclass(frozen=True)
class AcquisitionPlan:
    name: str
    logical_channels: tuple[int, ...]
    a0: int
    aa: tuple[int, ...]

    @property
    def logical_count(self) -> int:
        return len(self.logical_channels)

    @property
    def aa_channels(self) -> tuple[int, ...]:
        return tuple(i + 1 for i, value in enumerate(self.aa) if value)


def make_plan(logical_channels: Sequence[int], *, a0_mode: str, aa_mode: str, name: str | None = None) -> AcquisitionPlan:
    logical = tuple(sorted(set(int(ch) for ch in logical_channels)))
    if not logical or any(ch < 1 or ch > 8 for ch in logical):
        raise ValueError("logical_channels must contain one or more values in 1..8")
    if len(logical) != len(logical_channels):
        raise ValueError("logical_channels contains duplicates")

    logical_count = len(logical)
    width = observed_windows_width(logical_count)

    if a0_mode == "logical":
        a0 = logical_count
    elif a0_mode == "width":
        a0 = width
    else:
        raise ValueError("a0_mode must be 'logical' or 'width'")

    if aa_mode == "logical":
        aa = mask_for_channels(logical)
    elif aa_mode == "width":
        # Width-mode is deliberately limited to contiguous CH1..CHN tests.
        # It models the official-Windows observation without claiming that the
        # extra lane is a user-visible enabled channel.
        if logical != tuple(range(1, logical_count + 1)):
            raise ValueError("aa_mode='width' requires contiguous CH1..CHN logical channels")
        aa = contiguous_mask(width)
    else:
        raise ValueError("aa_mode must be 'logical' or 'width'")

    return AcquisitionPlan(
        name=name or f"n{logical_count}-a0-{a0_mode}-aa-{aa_mode}",
        logical_channels=logical,
        a0=a0,
        aa=aa,
    )



def acquisition_layout(channels: Sequence[int]) -> tuple[tuple[int, ...], int]:
    """Return canonical packed physical-channel order and acquisition width.

    AA-selected channels are packed in ascending physical-channel order.  For
    odd counts 3, 5, and 7 the hardware adds one final dummy acquisition slot.
    This layout is hardware-validated for direct ADC at A3=0x11 and 0x0F.
    """
    logical = tuple(sorted(set(int(ch) for ch in channels)))
    if not logical or len(logical) != len(channels) or any(ch < 1 or ch > 8 for ch in logical):
        raise ValueError("channels must contain unique values in 1..8")
    return logical, observed_windows_width(len(logical))


def compact_enabled_rows(words: Sequence[int], channels: Sequence[int]) -> list[list[int]]:
    """Decode complete physical rows and discard the validated final dummy slot.

    The return value contains one sample list per enabled physical channel in
    ascending channel order.  An incomplete trailing physical row is discarded
    so all returned channels have the same number of samples.
    """
    logical, width = acquisition_layout(channels)
    rows = len(words) // width
    return [[words[row * width + lane] for row in range(rows)]
            for lane, _channel in enumerate(logical)]

def deinterleave_words(words: Sequence[int], lane_count: int) -> list[list[int]]:
    """Deinterleave a physical word stream without requiring equal lane lengths.

    A 4000-word frame split across six lanes naturally produces lengths
    667,667,667,667,666,666; truncation or padding is not introduced.
    """
    if not 1 <= int(lane_count) <= 8:
        raise ValueError("lane_count must be 1..8")
    return [list(words[offset::lane_count]) for offset in range(lane_count)]


def u12_words(buffer02: bytes, buffer03: bytes) -> list[int]:
    raw = buffer02 + buffer03
    return [int.from_bytes(raw[i:i + 2], "little") & 0x0FFF for i in range(0, len(raw) - 1, 2)]


def normalized_autocorr(values: Sequence[float], lag: int) -> float | None:
    if lag <= 0 or lag >= len(values):
        return None
    x = values[:-lag]
    y = values[lag:]
    mx = statistics.fmean(x)
    my = statistics.fmean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    denx = sum((a - mx) ** 2 for a in x)
    deny = sum((b - my) ** 2 for b in y)
    den = math.sqrt(denx * deny)
    return 0.0 if den == 0 else num / den


@dataclass(frozen=True)
class PeriodEstimate:
    period_samples: float | None
    correlation: float | None
    rate_hz: float | None
    rms_ac: float
    span: float


def estimate_period_generic(
    values: Sequence[float],
    *,
    reference_frequency_hz: float,
    min_period_samples: int = 8,
    max_period_samples: int | None = None,
    expected_rate_hz: float | None = None,
    search_fraction: float = 0.35,
) -> PeriodEstimate:
    """Estimate repetition period using raw-sample autocorrelation.

    The known reference frequency is used only to convert the measured period
    to samples/second.  It is not used to filter, flatten, threshold, repair,
    or otherwise alter the captured waveform.
    """
    vals = list(values)
    if reference_frequency_hz <= 0:
        raise ValueError("reference_frequency_hz must be > 0")
    if len(vals) < 2 * min_period_samples:
        return PeriodEstimate(None, None, None, 0.0, 0.0)

    mean = statistics.fmean(vals)
    rms = math.sqrt(statistics.fmean((x - mean) ** 2 for x in vals))
    span = float(max(vals) - min(vals))
    if rms == 0:
        return PeriodEstimate(None, None, None, rms, span)

    if expected_rate_hz is not None:
        if expected_rate_hz <= 0:
            raise ValueError("expected_rate_hz must be > 0")
        if not 0 < search_fraction < 1:
            raise ValueError("search_fraction must be between 0 and 1")
        expected_period = expected_rate_hz / reference_frequency_hz
        lo = max(min_period_samples, int(math.floor(expected_period * (1.0 - search_fraction))))
        hi = int(math.ceil(expected_period * (1.0 + search_fraction)))
        if max_period_samples is not None:
            hi = min(hi, int(max_period_samples))
    else:
        lo = min_period_samples
        hi = max_period_samples if max_period_samples is not None else len(vals) // 2
    hi = min(int(hi), len(vals) - 1)
    if hi < lo:
        return PeriodEstimate(None, None, None, rms, span)

    scores: list[tuple[float, int]] = []
    for lag in range(lo, hi + 1):
        corr = normalized_autocorr(vals, lag)
        if corr is not None:
            scores.append((corr, lag))
    if not scores:
        return PeriodEstimate(None, None, None, rms, span)

    # Prefer the earliest strong local positive peak. This avoids automatically
    # choosing a later integer multiple of the physical period merely because
    # it has a marginally higher finite-record correlation.
    best_corr = max(c for c, _ in scores)
    strong = max(0.55, best_corr - 0.08)
    local_peaks: list[tuple[float, int]] = []
    by_lag = {lag: corr for corr, lag in scores}
    for corr, lag in scores:
        left = by_lag.get(lag - 1, -2.0)
        right = by_lag.get(lag + 1, -2.0)
        if corr >= strong and corr >= left and corr >= right:
            local_peaks.append((corr, lag))
    if local_peaks:
        corr, lag = min(local_peaks, key=lambda item: item[1])
    else:
        corr, lag = max(scores)

    # Three-point parabolic interpolation around the autocorrelation peak gives
    # a sub-sample period estimate without touching the captured samples.
    period = float(lag)
    c0 = by_lag.get(lag - 1)
    c1 = by_lag.get(lag)
    c2 = by_lag.get(lag + 1)
    if c0 is not None and c1 is not None and c2 is not None:
        denom = c0 - 2.0 * c1 + c2
        if abs(denom) > 1e-12:
            delta = 0.5 * (c0 - c2) / denom
            if abs(delta) <= 1.0:
                period += delta

    return PeriodEstimate(
        period_samples=period,
        correlation=float(corr),
        rate_hz=period * float(reference_frequency_hz),
        rms_ac=rms,
        span=span,
    )


def candidate_geometry(
    words: Sequence[int],
    *,
    reference_lane: int,
    reference_frequency_hz: float,
    lane_counts: Sequence[int] | None = None,
    expected_aggregate_rate_hz: float | None = None,
) -> list[dict]:
    """Score candidate interleave widths without altering captured samples."""
    rows = []
    candidates = tuple(range(1, 9)) if lane_counts is None else tuple(dict.fromkeys(int(x) for x in lane_counts))
    if any(x < 1 or x > 8 for x in candidates):
        raise ValueError("lane_counts must contain values in 1..8")
    for lane_count in candidates:
        lanes = deinterleave_words(words, lane_count)
        if reference_lane >= lane_count:
            continue
        expected_lane_rate = None if expected_aggregate_rate_hz is None else expected_aggregate_rate_hz / lane_count
        estimate = estimate_period_generic(
            lanes[reference_lane],
            reference_frequency_hz=reference_frequency_hz,
            expected_rate_hz=expected_lane_rate,
        )
        rows.append({
            "lane_count": lane_count,
            "lane_lengths": [len(x) for x in lanes],
            "reference_lane": reference_lane + 1,
            "period_samples": estimate.period_samples,
            "correlation": estimate.correlation,
            "rate_hz": estimate.rate_hz,
            "rms_ac": estimate.rms_ac,
            "span": estimate.span,
        })
    return rows
