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


def nominal_volts_per_count(a2: int) -> float:
    """Return the reference driver's nominal raw-to-volts scale.

    This is a fallback/reference value only.  A saved per-device/per-channel/
    per-range calibration may legitimately use a different scale.
    """
    return 0.01 * REFERENCE_NOMINAL_VSCALE_BY_A2[a2]


def reference_volts_per_delta_count(a2: int) -> float:
    """Backward-compatible alias for :func:`nominal_volts_per_count`."""
    return nominal_volts_per_count(a2)
