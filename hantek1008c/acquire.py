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


def _read_buffer(scope: Any, selector: int, size: int, timeout_ms: int, *, metrics: dict | None = None) -> bytes:
    out = bytearray()
    packet_metrics = []
    phase_start = time.perf_counter_ns()
    for packet_index in range((size + 63) // 64):
        packet_start = time.perf_counter_ns()
        write_start = packet_start
        scope.write(bytes([0xA6, selector]), timeout_ms=timeout_ms)
        write_end = time.perf_counter_ns()
        read_start = write_end
        packet = scope.read(size=64, timeout_ms=timeout_ms)
        read_end = time.perf_counter_ns()
        if len(packet) != 64:
            raise _usb_error(f"A6 {selector:02X}: short packet {len(packet)}")
        out.extend(packet)
        if metrics is not None:
            packet_metrics.append({
                "packet": packet_index,
                "write_us": (write_end - write_start) / 1000.0,
                "read_us": (read_end - read_start) / 1000.0,
                "total_us": (read_end - packet_start) / 1000.0,
            })
    phase_end = time.perf_counter_ns()
    if metrics is not None:
        metrics.update({
            "selector": selector,
            "bytes": size,
            "packets": len(packet_metrics),
            "elapsed_ms": (phase_end - phase_start) / 1_000_000.0,
            "packet_metrics": packet_metrics,
        })
    return bytes(out[:size])


def _query_buffer(scope: Any, selector: int, timeout_ms: int, *, metrics: dict | None = None) -> bytes:
    c6_start = time.perf_counter_ns()
    reply = _transact(scope, bytes([0xC6, selector]), timeout_ms)
    c6_end = time.perf_counter_ns()
    if len(reply) != 2:
        raise _usb_error(f"C6 {selector:02X}: expected 2-byte size, got {len(reply)}")
    size = int.from_bytes(reply, "big")
    if metrics is not None:
        metrics["c6_ms"] = (c6_end - c6_start) / 1_000_000.0
        metrics["reported_bytes"] = size
    read_metrics = {} if metrics is not None else None
    data = _read_buffer(scope, selector, size, timeout_ms, metrics=read_metrics)
    if metrics is not None:
        metrics["a6"] = read_metrics
        metrics["elapsed_ms"] = metrics["c6_ms"] + read_metrics["elapsed_ms"]
    return data


def wait_ready_with_polls(
    scope: Any, timeout_ms: int = 1000, tries: int = 100, *, metrics: dict | None = None
) -> tuple[int, int]:
    """Poll A5 until ready, returning ``(state, poll_count)``."""
    poll_rows = []
    phase_start = time.perf_counter_ns()
    for poll_count in range(1, tries + 1):
        poll_start = time.perf_counter_ns()
        reply = _transact(scope, bytes.fromhex("A5 5A"), timeout_ms)
        poll_end = time.perf_counter_ns()
        state = reply[-1] if reply else None
        if metrics is not None:
            poll_rows.append({
                "poll": poll_count,
                "state": state,
                "transaction_ms": (poll_end - poll_start) / 1_000_000.0,
            })
        if state in (2, 3):
            if metrics is not None:
                metrics.update({
                    "elapsed_ms": (poll_end - phase_start) / 1_000_000.0,
                    "polls": poll_rows,
                    "ready_state": int(state),
                })
            return int(state), poll_count
        sleep_start = time.perf_counter_ns()
        time.sleep(0.002)
        sleep_end = time.perf_counter_ns()
        if metrics is not None:
            poll_rows[-1]["sleep_ms"] = (sleep_end - sleep_start) / 1_000_000.0
    raise _usb_error(
        f"A5 never reached ready state 2/3 in {tries} polls"
    )


def wait_ready(scope: Any, timeout_ms: int = 1000, tries: int = 100) -> int:
    """Poll A5 until the device reports a completed/ready acquisition (2 or 3)."""
    state, _ = wait_ready_with_polls(scope, timeout_ms, tries)
    return state


def poll_ready_until(
    scope: Any,
    timeout_ms: int,
    *,
    poll_interval_ms: float = 15.0,
    deadline_ms: float | None = None,
    metrics: dict | None = None,
) -> tuple[bool, int | None, int]:
    """Poll F3/A5 until hardware reports ready.

    ``deadline_ms=None`` implements Normal-style waiting: polling continues until
    a genuine trigger completes the acquisition.  A finite deadline implements
    Auto-style host policy: if the deadline expires the caller may force
    completion with C2.
    """
    rows = []
    started = time.perf_counter_ns()
    deadline_ns = None if deadline_ms is None else started + int(deadline_ms * 1_000_000.0)
    polls = 0
    last_state = None

    while True:
        _transact(scope, b"\xF3", timeout_ms)
        poll_started = time.perf_counter_ns()
        reply = _transact(scope, bytes.fromhex("A5 5A"), timeout_ms)
        poll_ended = time.perf_counter_ns()
        polls += 1
        state = reply[-1] if reply else None
        last_state = int(state) if state is not None else None
        if metrics is not None:
            rows.append({
                "poll": polls,
                "state": last_state,
                "elapsed_ms": (poll_ended - started) / 1_000_000.0,
                "transaction_ms": (poll_ended - poll_started) / 1_000_000.0,
            })
        if state in (2, 3):
            if metrics is not None:
                metrics.update({
                    "elapsed_ms": (poll_ended - started) / 1_000_000.0,
                    "polls": rows,
                    "ready_state": int(state),
                    "timed_out": False,
                })
            return True, int(state), polls

        now = time.perf_counter_ns()
        if deadline_ns is not None and now >= deadline_ns:
            if metrics is not None:
                metrics.update({
                    "elapsed_ms": (now - started) / 1_000_000.0,
                    "polls": rows,
                    "ready_state": None,
                    "last_state": last_state,
                    "timed_out": True,
                })
            return False, last_state, polls

        if poll_interval_ms > 0:
            time.sleep(poll_interval_ms / 1000.0)


def acquire_direct_buffers(
    scope: Any,
    timeout_ms: int = 1000,
    *,
    trigger_enabled: bool = False,
    auto_timeout_ms: float = 1870.0,
    poll_interval_ms: float = 15.0,
    arm_delay_s: float = 0.0,
    return_ready_info: bool = False,
    return_metrics: bool = False,
):
    """Acquire one direct-ADC burst using the proven trigger state machine.

    The hardware is armed with A4 01 -> C0 and A5 is then polled.  C2 is *not*
    part of initial arming.

    ``trigger_enabled=False`` implements Auto/free-running frontend semantics:
    wait for a genuine trigger until ``auto_timeout_ms`` expires, then send C2
    to force completion.

    ``trigger_enabled=True`` implements Normal frontend semantics: wait
    indefinitely for genuine hardware readiness and never send a timeout C2.

    ``arm_delay_s`` remains a protocol-lab control; validated canonical use is
    zero seconds.  Single-shot is intentionally not represented here because
    it is a frontend re-arm policy, not a different USB arm sequence.
    """
    if auto_timeout_ms < 0:
        raise ValueError("auto_timeout_ms must be >= 0")
    if poll_interval_ms < 0:
        raise ValueError("poll_interval_ms must be >= 0")

    metrics = {
        "arm_delay_requested_ms": arm_delay_s * 1000.0,
        "trigger_policy": "normal" if trigger_enabled else "auto",
    } if return_metrics else None
    total_start = time.perf_counter_ns()

    def tx_timed(name: str, payload: bytes) -> bytes:
        started = time.perf_counter_ns()
        reply = _transact(scope, payload, timeout_ms)
        ended = time.perf_counter_ns()
        if metrics is not None:
            metrics[name] = (ended - started) / 1_000_000.0
            if name == "a4_ms":
                metrics["a4_start_ns"] = started
                metrics["a4_end_ns"] = ended
        return reply

    tx_timed("f3_ms", b"\xF3")
    tx_timed("e4_pre_ms", bytes.fromhex("E4 01"))
    tx_timed("e6_pre_ms", bytes.fromhex("E6 01"))
    tx_timed("a4_ms", bytes.fromhex("A4 01"))
    if arm_delay_s > 0:
        delay_start = time.perf_counter_ns()
        time.sleep(arm_delay_s)
        delay_end = time.perf_counter_ns()
        if metrics is not None:
            metrics["arm_delay_actual_ms"] = (delay_end - delay_start) / 1_000_000.0
    elif metrics is not None:
        metrics["arm_delay_actual_ms"] = 0.0

    tx_timed("c0_ms", b"\xC0")

    a5_metrics = {} if metrics is not None else None
    ready, ready_state, ready_polls = poll_ready_until(
        scope,
        timeout_ms,
        poll_interval_ms=poll_interval_ms,
        deadline_ms=None if trigger_enabled else auto_timeout_ms,
        metrics=a5_metrics,
    )
    forced = False
    if not ready:
        if trigger_enabled:
            raise _usb_error("Normal trigger wait ended without hardware readiness")
        forced = True
        tx_timed("c2_ms", b"\xC2")
        cleanup_metrics = {} if metrics is not None else None
        ready, ready_state, cleanup_polls = poll_ready_until(
            scope,
            timeout_ms,
            poll_interval_ms=poll_interval_ms,
            deadline_ms=max(1800.0, float(timeout_ms)),
            metrics=cleanup_metrics,
        )
        ready_polls += cleanup_polls
        if metrics is not None:
            metrics["a5_after_c2"] = cleanup_metrics
        if not ready:
            raise _usb_error("C2 forced completion did not reach A5 ready state 2/3")

    if metrics is not None:
        metrics["a5"] = a5_metrics
        metrics["forced_completion"] = forced

    b2_metrics = {} if metrics is not None else None
    b2 = _query_buffer(scope, 2, timeout_ms, metrics=b2_metrics)
    if metrics is not None:
        metrics["buffer02"] = b2_metrics

    b3_metrics = {} if metrics is not None else None
    b3 = _query_buffer(scope, 3, timeout_ms, metrics=b3_metrics)
    if metrics is not None:
        metrics["buffer03"] = b3_metrics

    tx_timed("e4_post_ms", bytes.fromhex("E4 01"))
    tx_timed("e6_post_ms", bytes.fromhex("E6 01"))
    total_end = time.perf_counter_ns()
    if metrics is not None:
        metrics["total_ms"] = (total_end - total_start) / 1_000_000.0

    if return_metrics and return_ready_info:
        return b2, b3, ready_state, ready_polls, metrics
    if return_metrics:
        return b2, b3, metrics
    if return_ready_info:
        return b2, b3, ready_state, ready_polls
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
    trigger_enabled: bool = False
    trigger_slope_raw: int = 0x00
    trigger_level_adc: int = 0x0800
    auto_timeout_ms: float = 1870.0
    trigger_poll_interval_ms: float = 15.0

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
        self.set_trigger_slope_raw(c.trigger_slope_raw)
        self._tx(bytes.fromhex("A7 00 00"))
        self._tx(bytes.fromhex("AC 00 00 00 00 01 00 05 79"))
        self.set_trigger_level_adc(c.trigger_level_adc)
        self._tx(b"\xE9")

        self.calibration = calibration
        self.initialized = True
        return calibration

    def set_trigger_slope_raw(self, value: int) -> None:
        """Set the proven C1 edge-trigger selector.

        Windows UI chronology proves C1 00 00 = ``+`` / rising and
        C1 00 01 = ``-`` / falling.  The raw setter remains useful for
        protocol-lab correlation tools.
        """
        if value not in (0, 1):
            raise ValueError("trigger_slope_raw must be 0 or 1")
        self._tx(bytes([0xC1, 0x00, value]))
        self.config.trigger_slope_raw = value

    def set_trigger_slope(self, slope: str) -> None:
        """Set edge trigger slope by proven frontend meaning."""
        normalized = slope.strip().lower()
        mapping = {"rising": 0, "+": 0, "falling": 1, "-": 1}
        if normalized not in mapping:
            raise ValueError("trigger slope must be rising/+ or falling/-")
        self.set_trigger_slope_raw(mapping[normalized])

    def set_trigger_level_adc(self, value: int) -> None:
        """Set AB as the proven big-endian 16-bit ADC-domain trigger level."""
        if not 0 <= value <= 0xFFFF:
            raise ValueError("trigger_level_adc must be 0..65535")
        self._tx(bytes([0xAB, (value >> 8) & 0xFF, value & 0xFF]))
        self.config.trigger_level_adc = value

    def acquire_words(self) -> List[int]:
        if not self.initialized:
            raise _usb_error("DirectADCSession.initialize() must be called first")
        return decode_direct_u12(acquire_direct_buffers(
            self.scope,
            self.config.timeout_ms,
            trigger_enabled=self.config.trigger_enabled,
            auto_timeout_ms=self.config.auto_timeout_ms,
            poll_interval_ms=self.config.trigger_poll_interval_ms,
        ))
