"""Vertical-range knowledge for the Hantek 1008C.

A2 values 01..03 select three real analogue gain/range states.  The public
mfg92/hantek1008py implementation supplies nominal scale factors for those
states, but its own Volt/Div interpretation is marked TODO/check.  Keep those
numbers as *reference nominal* values, not as per-device calibration truth.
"""
from __future__ import annotations

REFERENCE_NOMINAL_VSCALE_BY_A2 = {
    0x01: 0.02,
    0x02: 0.125,
    0x03: 1.0,
}

# Backward-compatible name retained for existing analysis/tests.
REFERENCE_VSCALE_BY_A2 = REFERENCE_NOMINAL_VSCALE_BY_A2

RANGE_NAME_BY_A2 = {0x01: "Narrow", 0x02: "Medium", 0x03: "Wide"}

_A2_BY_RANGE_ALIAS = {
    "narrow": 0x01,
    "medium": 0x02,
    "wide": 0x03,
    "01": 0x01,
    "02": 0x02,
    "03": 0x03,
    "a2=01": 0x01,
    "a2=02": 0x02,
    "a2=03": 0x03,
}


def parse_range(value: str) -> int:
    """Parse a public range name or a backward-compatible raw A2 alias."""
    try:
        return _A2_BY_RANGE_ALIAS[value.strip().lower()]
    except KeyError as exc:
        raise ValueError("range must be Narrow, Medium, or Wide") from exc


def range_name(a2: int) -> str:
    """Return the meaningful public name for a validated raw A2 value."""
    return RANGE_NAME_BY_A2[a2]


def range_description(a2: int) -> str:
    """Return a public name while retaining the diagnostic A2 value."""
    return f"{range_name(a2)} (A2={a2:02X})"


def nominal_volts_per_count(a2: int) -> float:
    """Return the reference driver's nominal raw-to-volts scale.

    This is a fallback/reference value only.  A saved per-device/per-channel/
    per-range calibration may legitimately use a different scale.
    """
    return 0.01 * REFERENCE_NOMINAL_VSCALE_BY_A2[a2]


def reference_volts_per_delta_count(a2: int) -> float:
    """Backward-compatible alias for :func:`nominal_volts_per_count`."""
    return nominal_volts_per_count(a2)
