"""Persistent user-assisted calibration for the Hantek 1008C.

Calibration data belongs to the physical scope, not to a particular frontend.
The canonical store therefore lives under the user's XDG data directory and is
shared by the Python reference tools and the libsigrok driver.
"""
from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import statistics
from typing import Iterable, Sequence

from .vertical import nominal_volts_per_count

FORMAT_VERSION = 1
ADC_MAX = 4095
FIRST_ZERO_MIN = 0.45 * ADC_MAX
FIRST_ZERO_MAX = 0.55 * ADC_MAX
DEFAULT_MAX_ZERO_SHIFT_COUNTS = 20.0
DEFAULT_ZERO_TRIGGERED_ACQUISITIONS = 3
DEFAULT_VALIDATION_TRIGGERED_ACQUISITIONS = 3


def calibration_path() -> Path:
    root = os.environ.get("XDG_DATA_HOME")
    if root:
        base = Path(root).expanduser()
    else:
        base = Path.home() / ".local" / "share"
    return base / "hantek-1008c" / "calibration.ini"


def section_name(connection_id: str, channel: int, range_id: int) -> str:
    if not connection_id:
        raise ValueError("connection_id must not be empty")
    if not 1 <= channel <= 8:
        raise ValueError("channel must be 1..8")
    if range_id not in (1, 2, 3):
        raise ValueError("range_id must be one of the validated A2 ranges 01..03")
    return f"device {connection_id} channel CH{channel} range {range_id:02X}"


def policy_section_name(connection_id: str) -> str:
    if not connection_id:
        raise ValueError("connection_id must not be empty")
    return f"calibration policy {connection_id}"


@dataclass(frozen=True)
class ZeroCalibration:
    connection_id: str
    channel: int
    range_id: int
    zero_adc: float
    zero_stddev: float
    zero_min: int
    zero_max: int
    samples: int
    volts_per_count: float
    calibrated_utc: str
    scale_source: str = "reference_nominal_mfg92"

    @property
    def section(self) -> str:
        return section_name(self.connection_id, self.channel, self.range_id)

    def volts(self, raw_adc: float) -> float:
        return (float(raw_adc) - self.zero_adc) * self.volts_per_count


@dataclass(frozen=True)
class ReferenceValidation:
    source: str
    measured_vpp: float
    measured_frequency_hz: float | None
    passed: bool
    samples: int
    validated_utc: str


def _parser() -> ConfigParser:
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    return parser


def _load_parser(path: Path) -> ConfigParser:
    parser = _parser()
    if path.exists():
        parser.read(path, encoding="utf-8")
    return parser


def load_max_zero_shift_counts(
    connection_id: str,
    path: Path | None = None,
) -> tuple[float, str]:
    """Return the device policy and whether it was saved or defaulted."""
    path = calibration_path() if path is None else Path(path)
    parser = _load_parser(path)
    section = policy_section_name(connection_id)
    if not parser.has_option(section, "max_zero_shift_counts"):
        return DEFAULT_MAX_ZERO_SHIFT_COUNTS, "default"
    value = parser.getfloat(section, "max_zero_shift_counts")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("invalid saved max_zero_shift_counts policy")
    return value, "saved device policy"


def save_max_zero_shift_counts(
    connection_id: str,
    value: float,
    path: Path | None = None,
) -> Path:
    """Persist the maximum accepted same-entry zero change for one device."""
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("max_zero_shift_counts must be finite and > 0")
    path = calibration_path() if path is None else Path(path)
    parser = _load_parser(path)
    if not parser.has_section("format"):
        parser.add_section("format")
    parser.set("format", "version", str(FORMAT_VERSION))
    section = policy_section_name(connection_id)
    if not parser.has_section(section):
        parser.add_section(section)
    parser.set(section, "max_zero_shift_counts", f"{value:.9g}")
    parser.set(section, "updated_utc", datetime.now(timezone.utc).isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        parser.write(fh)
    os.replace(tmp, path)
    return path


def validate_zero_candidate(
    candidate: "ZeroCalibration",
    previous: "ZeroCalibration | None",
    max_zero_shift_counts: float,
) -> float | None:
    """Validate absolute first-run plausibility or change from a stored zero."""
    limit = float(max_zero_shift_counts)
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError("max_zero_shift_counts must be finite and > 0")
    if not FIRST_ZERO_MIN <= candidate.zero_adc <= FIRST_ZERO_MAX:
        raise ValueError(
            f"candidate zero {candidate.zero_adc:.3f} is outside the plausible "
            f"{FIRST_ZERO_MIN:.0f}..{FIRST_ZERO_MAX:.0f} count region"
        )
    if previous is None:
        return None
    shift = candidate.zero_adc - previous.zero_adc
    if abs(shift) > limit:
        raise ValueError(
            f"candidate zero shift {shift:+.3f} counts exceeds "
            f"the permitted +/-{limit:.3f} counts"
        )
    return shift


def save_zero_calibration(cal: ZeroCalibration, path: Path | None = None) -> Path:
    path = calibration_path() if path is None else Path(path)
    parser = _load_parser(path)
    if not parser.has_section("format"):
        parser.add_section("format")
    parser.set("format", "version", str(FORMAT_VERSION))

    if not parser.has_section(cal.section):
        parser.add_section(cal.section)
    values = {
        "usb_vid": "0783",
        "usb_pid": "5725",
        "connection_id": cal.connection_id,
        "channel": f"CH{cal.channel}",
        "range_a2": f"{cal.range_id:02X}",
        "zero_adc": f"{cal.zero_adc:.9f}",
        "zero_stddev": f"{cal.zero_stddev:.9f}",
        "zero_min": str(cal.zero_min),
        "zero_max": str(cal.zero_max),
        "samples": str(cal.samples),
        "volts_per_count": f"{cal.volts_per_count:.12g}",
        "scale_source": cal.scale_source,
        "calibrated_utc": cal.calibrated_utc,
    }
    for key, value in values.items():
        parser.set(cal.section, key, value)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        parser.write(fh)
    os.replace(tmp, path)
    return path


def save_reference_validation(
    cal: ZeroCalibration,
    validation: ReferenceValidation,
    path: Path | None = None,
) -> Path:
    path = calibration_path() if path is None else Path(path)
    parser = _load_parser(path)
    if not parser.has_section(cal.section):
        raise ValueError(f"no stored zero calibration section {cal.section!r}")
    values = {
        "validation_source": validation.source,
        "validation_measured_vpp": f"{validation.measured_vpp:.9f}",
        "validation_measured_frequency_hz": (
            "" if validation.measured_frequency_hz is None
            else f"{validation.measured_frequency_hz:.9f}"
        ),
        "validation_passed": "true" if validation.passed else "false",
        "validation_samples": str(validation.samples),
        "validated_utc": validation.validated_utc,
    }
    for key, value in values.items():
        parser.set(cal.section, key, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        parser.write(fh)
    os.replace(tmp, path)
    return path


def load_zero_calibration(
    connection_id: str,
    channel: int,
    range_id: int,
    path: Path | None = None,
) -> ZeroCalibration | None:
    path = calibration_path() if path is None else Path(path)
    parser = _load_parser(path)
    if parser.has_section("format"):
        version = parser.getint("format", "version", fallback=0)
        if version != FORMAT_VERSION:
            raise ValueError(f"unsupported calibration format version {version}")
    section = section_name(connection_id, channel, range_id)
    if not parser.has_section(section):
        return None
    zero_adc = parser.getfloat(section, "zero_adc")
    zero_stddev = parser.getfloat(section, "zero_stddev")
    volts_per_count = parser.getfloat(section, "volts_per_count")
    samples = parser.getint(section, "samples")
    if not math.isfinite(zero_adc) or not math.isfinite(zero_stddev):
        raise ValueError("non-finite zero calibration")
    if not math.isfinite(volts_per_count) or volts_per_count <= 0:
        raise ValueError("invalid volts_per_count in calibration")
    if samples <= 0:
        raise ValueError("invalid calibration sample count")
    return ZeroCalibration(
        connection_id=connection_id,
        channel=channel,
        range_id=range_id,
        zero_adc=zero_adc,
        zero_stddev=zero_stddev,
        zero_min=parser.getint(section, "zero_min"),
        zero_max=parser.getint(section, "zero_max"),
        samples=samples,
        volts_per_count=volts_per_count,
        calibrated_utc=parser.get(section, "calibrated_utc"),
        scale_source=parser.get(section, "scale_source", fallback="legacy_unspecified"),
    )


def build_zero_calibration(
    connection_id: str,
    channel: int,
    range_id: int,
    words: Sequence[int],
) -> ZeroCalibration:
    if not words:
        raise ValueError("zero calibration requires samples")
    values = [int(v) for v in words]
    mean = statistics.fmean(values)
    stddev = statistics.pstdev(values)
    return ZeroCalibration(
        connection_id=connection_id,
        channel=channel,
        range_id=range_id,
        zero_adc=mean,
        zero_stddev=stddev,
        zero_min=min(values),
        zero_max=max(values),
        samples=len(values),
        volts_per_count=nominal_volts_per_count(range_id),
        calibrated_utc=datetime.now(timezone.utc).isoformat(),
        scale_source="reference_nominal_mfg92",
    )


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        raise ValueError("quantile requires values")
    pos = fraction * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight



def replace_voltage_scale(
    cal: ZeroCalibration,
    volts_per_count: float,
    source: str,
) -> ZeroCalibration:
    """Return ``cal`` with an explicitly sourced voltage scale.

    Zero calibration and voltage-scale calibration are deliberately separate:
    changing the scale never changes the measured zero ADC offset.
    """
    scale = float(volts_per_count)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("volts_per_count must be finite and > 0")
    if not source.strip():
        raise ValueError("scale source must not be empty")
    return replace(cal, volts_per_count=scale, scale_source=source.strip())


def estimate_onboard_reference_scale(
    frames: Iterable[Sequence[int]],
    expected_vpp: float = 2.0,
) -> tuple[float, float]:
    """Estimate V/count from the nominal onboard square-wave reference.

    This helper is validation/calibration-only.  It uses 10/90 percentiles to
    estimate the two square-wave plateaux and is never part of canonical
    acquisition or waveform reconstruction.  Returns ``(volts_per_count,
    raw_plateau_span_counts)``.
    """
    if not math.isfinite(expected_vpp) or expected_vpp <= 0:
        raise ValueError("expected_vpp must be finite and > 0")
    all_words = [int(v) for frame in frames for v in frame]
    if not all_words:
        raise ValueError("reference scale estimation requires samples")
    low = _quantile(all_words, 0.10)
    high = _quantile(all_words, 0.90)
    span = high - low
    if span <= 0:
        raise ValueError("reference plateau span must be > 0")
    return expected_vpp / span, span


def validate_onboard_reference(
    frames: Iterable[Sequence[int]],
    cal: ZeroCalibration,
    sample_rate: float,
    expected_frequency_hz: float = 1000.0,
    expected_vpp: float = 2.0,
) -> ReferenceValidation:
    """Validate against the known onboard reference without changing calibration.

    Quantiles and threshold crossings are intentionally confined to this
    validation helper. They are not part of the canonical acquisition or
    reconstruction path.
    """
    frame_list = [list(frame) for frame in frames if frame]
    if not frame_list:
        raise ValueError("reference validation requires samples")
    all_words = [v for frame in frame_list for v in frame]
    low = _quantile(all_words, 0.10)
    high = _quantile(all_words, 0.90)
    measured_vpp = (high - low) * cal.volts_per_count

    # The onboard reference is a square wave, so use a Schmitt-style detector
    # for this validation-only measurement.  A single midpoint threshold is
    # vulnerable to transition ringing/noise, which can create several toggles
    # around one physical edge and falsely double the estimated frequency.
    span = high - low
    low_trigger = low + (0.25 * span)
    high_trigger = low + (0.75 * span)
    periods: list[float] = []
    for frame in frame_list:
        if not frame:
            continue
        state_high = float(frame[0]) >= ((low + high) / 2.0)
        rising_edges: list[int] = []
        falling_edges: list[int] = []
        for i, value in enumerate(frame[1:], start=1):
            sample = float(value)
            if state_high:
                if sample <= low_trigger:
                    state_high = False
                    falling_edges.append(i)
            elif sample >= high_trigger:
                state_high = True
                rising_edges.append(i)
        periods.extend(
            float(b - a) for a, b in zip(rising_edges, rising_edges[1:]) if b > a
        )
        periods.extend(
            float(b - a) for a, b in zip(falling_edges, falling_edges[1:]) if b > a
        )
    frequency = None
    if periods:
        median_period = statistics.median(periods)
        if median_period > 0:
            frequency = sample_rate / median_period

    vpp_ok = expected_vpp * 0.80 <= measured_vpp <= expected_vpp * 1.20
    freq_ok = (
        frequency is not None
        and expected_frequency_hz * 0.90 <= frequency <= expected_frequency_hz * 1.10
    )
    return ReferenceValidation(
        source="onboard_1khz_2vpp",
        measured_vpp=measured_vpp,
        measured_frequency_hz=frequency,
        passed=bool(vpp_ok and freq_ok),
        samples=len(all_words),
        validated_utc=datetime.now(timezone.utc).isoformat(),
    )
