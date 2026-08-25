"""Vertical-scale knowledge for the Hantek 1008C.

IDs 1..3 and factors are taken from the mfg92/hantek1008py reference
implementation. IDs 0 and 4 are deliberately not declared valid even though
our single test unit currently behaves like aliases (00~03, 04~02).
"""
REFERENCE_VSCALE_BY_A2 = {
    0x01: 0.02,
    0x02: 0.125,
    0x03: 1.0,
}

def reference_volts_per_delta_count(a2: int) -> float:
    """Reference driver's nominal raw-to-volt scale, without correction data."""
    return 0.01 * REFERENCE_VSCALE_BY_A2[a2]
