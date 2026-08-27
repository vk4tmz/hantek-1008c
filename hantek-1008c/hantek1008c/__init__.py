"""Hantek 1008C protocol research helpers.

Offline decode/analysis helpers intentionally remain importable without PyUSB;
the hardware transport is loaded lazily only when requested.
"""

from .decode import DecodedCapture, decode_buffers, decode_interleaved_u12_le
from .analysis import (
    DeltaImpulseEdges,
    PeriodicityResult,
    analyze_periodicity,
    detect_delta_impulse_edges,
)

__all__ = [
    "DecodedCapture",
    "decode_buffers",
    "decode_interleaved_u12_le",
    "DeltaImpulseEdges",
    "PeriodicityResult",
    "analyze_periodicity",
    "detect_delta_impulse_edges",
]


def __getattr__(name):
    if name in {"Hantek1008C", "HantekUSBError"}:
        from .transport import Hantek1008C, HantekUSBError
        globals().update(Hantek1008C=Hantek1008C, HantekUSBError=HantekUSBError)
        return globals()[name]
    raise AttributeError(name)
