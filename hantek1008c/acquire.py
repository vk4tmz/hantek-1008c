from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, List, Tuple


def _usb_error(message: str):
    from .transport import HantekUSBError
    return HantekUSBError(message)

SAMPLE_RATES = {
    0x11: 800_000.0,
    0x10: 800_000.0,
    0x0F: 2_400_000.0,
    0x0E: 2_400_000.0,
}


def _transact(scope: Any, payload: bytes, timeout_ms: int) -> bytes:
    tx = scope.transact(payload, read_timeout_ms=timeout_ms)
    if tx.timed_out:
        raise _usb_error(f"{payload.hex(' ').upper()}: timeout")
    return tx.rx or b""


def _read_buffer(scope: Any, selector: int, size: int, timeout_ms: int) -> bytes:
    out = bytearray()
    for _ in range((size + 63) // 64):
        scope.write(bytes([0xA6, selector]), timeout_ms=timeout_ms)
        packet = scope.read(size=64, timeout_ms=timeout_ms)
        if len(packet) != 64:
            raise _usb_error(f"A6 {selector:02X}: short packet {len(packet)}")
        out.extend(packet)
    return bytes(out[:size])


def _query_buffer(scope: Any, selector: int, timeout_ms: int) -> bytes:
    reply = _transact(scope, bytes([0xC6, selector]), timeout_ms)
    if len(reply) != 2:
        raise _usb_error(f"C6 {selector:02X}: expected 2-byte size, got {len(reply)}")
    return _read_buffer(scope, selector, int.from_bytes(reply, "big"), timeout_ms)


def wait_ready(scope: Any, timeout_ms: int = 1000, tries: int = 100) -> int:
    """Poll A5 until the device reports a completed/ready acquisition (2 or 3)."""
    for _ in range(tries):
        reply = _transact(scope, bytes.fromhex("A5 5A"), timeout_ms)
        state = reply[-1] if reply else None
        if state in (2, 3):
            return int(state)
        time.sleep(0.002)
    raise _usb_error(
        f"A5 never reached ready state 2/3 in {tries} polls"
    )


def acquire_direct_buffers(scope: Any, timeout_ms: int = 1000) -> Tuple[bytes, bytes]:
    """Acquire one direct-ADC burst after full initialization."""
    _transact(scope, b"\xF3", timeout_ms)
    _transact(scope, bytes.fromhex("E4 01"), timeout_ms)
    _transact(scope, bytes.fromhex("E6 01"), timeout_ms)
    _transact(scope, bytes.fromhex("A4 01"), timeout_ms)
    time.sleep(0.015)
    _transact(scope, b"\xC0", timeout_ms)
    _transact(scope, b"\xC2", timeout_ms)
    wait_ready(scope, timeout_ms)
    b2 = _query_buffer(scope, 2, timeout_ms)
    b3 = _query_buffer(scope, 3, timeout_ms)
    _transact(scope, bytes.fromhex("E4 01"), timeout_ms)
    _transact(scope, bytes.fromhex("E6 01"), timeout_ms)
    return b2, b3


def decode_direct_u12(buffers: Tuple[bytes, bytes]) -> List[int]:
    raw = buffers[0] + buffers[1]
    return [
        int.from_bytes(raw[i:i + 2], "little") & 0x0FFF
        for i in range(0, len(raw) - 1, 2)
    ]


@dataclass
class DirectADCConfig:
    channel: int = 1
    a3: int = 0x0F
    range_id: int = 0x03
    timeout_ms: int = 1000

    @property
    def sample_rate(self) -> float:
        try:
            return SAMPLE_RATES[self.a3]
        except KeyError as exc:
            raise ValueError(f"A3={self.a3:02X} has no validated sample-rate mapping") from exc


class DirectADCSession:
    """Canonical Hantek 1008C direct-ADC acquisition session.

    The initialization follows the public mfg92/hantek1008py burst sequence
    validated on hardware on 2026-08-27.  Unlike the earlier minimal path, the
    resulting burst contains direct ADC samples and requires no integration or
    detrending.
    """

    def __init__(self, scope: Any, config: DirectADCConfig):
        if not 1 <= config.channel <= 8:
            raise ValueError("channel must be 1..8")
        self.scope = scope
        self.config = config
        self.calibration: Dict[int, Dict[str, float | int | None]] = {}
        self.initialized = False

    def _tx(self, payload: bytes) -> bytes:
        return _transact(self.scope, payload, self.config.timeout_ms)

    def initialize(self) -> Dict[int, Dict[str, float | int | None]]:
        c = self.config
        self._tx(b"\xB0")
        time.sleep(0.7)
        self._tx(b"\xB0")
        self._tx(b"\xF3")
        self._tx(bytes.fromhex("B9 01 B0 04 00 00"))
        self._tx(bytes.fromhex("B7 00"))
        self._tx(bytes.fromhex("BB 08 00"))
        for payload in (b"\xB5", b"\xB6", b"\xE5", b"\xF7", b"\xF8", b"\xFA"):
            self._tx(payload)
        self._tx(b"\xF5")
        self._tx(bytes.fromhex("A0 08"))
        self._tx(bytes.fromhex("AA 01 01 01 01 01 01 01 01"))
        self._tx(bytes.fromhex("A3 11"))
        self._tx(bytes.fromhex("C1 00 00"))
        self._tx(bytes.fromhex("A7 00 00"))
        self._tx(bytes.fromhex("AC 01 F4 00 09 C5 00 09 C5"))

        calibration: Dict[int, Dict[str, float | int | None]] = {}
        for range_id in (1, 2, 3):
            self._tx(b"\xF3")
            self._tx(bytes([0xA2] + [range_id] * 8))
            self._tx(bytes.fromhex("A4 01"))
            self._tx(b"\xC0")
            time.sleep(0.0124)
            self._tx(b"\xC2")
            wait_ready(self.scope, c.timeout_ms)
            words = decode_direct_u12((
                _query_buffer(self.scope, 2, c.timeout_ms),
                _query_buffer(self.scope, 3, c.timeout_ms),
            ))
            calibration[range_id] = {
                "word_count": len(words),
                "mean": (sum(words) / len(words)) if words else None,
                "min": min(words) if words else None,
                "max": max(words) if words else None,
            }

        self._tx(b"\xF6")
        time.sleep(0.2132)
        for payload in (b"\xE5", b"\xF7", b"\xF8", b"\xFA"):
            self._tx(payload)
        self._tx(bytes([0xA3, c.a3]))
        self._tx(bytes.fromhex("AC 00 C8 00 02 BD 00 02 BD"))
        self._tx(bytes.fromhex("E4 01"))
        self._tx(bytes.fromhex("E6 01"))
        self._tx(b"\xF3")
        self._tx(bytes.fromhex("A0 01"))
        aa = [0] * 8
        aa[c.channel - 1] = 1
        self._tx(bytes([0xAA] + aa))
        self._tx(bytes([0xA2] + [c.range_id] * 8))
        self._tx(bytes([0xA3, c.a3]))
        self._tx(bytes.fromhex("C1 00 00"))
        self._tx(bytes.fromhex("A7 00 00"))
        self._tx(bytes.fromhex("AC 00 00 00 00 01 00 05 79"))
        self._tx(bytes.fromhex("AB 08 00"))
        self._tx(b"\xE9")

        self.calibration = calibration
        self.initialized = True
        return calibration

    def acquire_words(self) -> List[int]:
        if not self.initialized:
            raise _usb_error("DirectADCSession.initialize() must be called first")
        return decode_direct_u12(acquire_direct_buffers(self.scope, self.config.timeout_ms))
