#!/usr/bin/env python3
"""Live viewer for the Hantek 1008C using proven direct-ADC burst mode.

The device is fully initialized using the mfg92/hantek1008py-style sequence
validated against the onboard 1 kHz reference.  Each frame then performs a
proper guarded burst acquisition, waits for A5 ready state 2/3, reads the
returned capture buffers, decodes direct 12-bit ADC samples, and updates one
Matplotlib window.

Vertical units are direct ADC counts, NOT volts.  No delta integration,
detrending, thresholding, smoothing, or waveform-specific reconstruction is
performed.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import numpy as np
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit("live_scope.py requires numpy and matplotlib") from exc

from hantek1008c.transport import Hantek1008C, HantekUSBError
from hantek1008c.decode import decode_buffers

SAMPLE_RATES = {
    0x11: 800_000.0,
    0x10: 800_000.0,
    0x0F: 2_400_000.0,
    0x0E: 2_400_000.0,
}


def byte_value(s):
    try:
        v = int(s, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "expected hexadecimal byte, e.g. 0F or 03"
        ) from exc
    if not 0 <= v <= 255:
        raise argparse.ArgumentTypeError("byte must be 00..FF")
    return v


def args():
    p = argparse.ArgumentParser()
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--a3", type=byte_value, default=0x0F)
    p.add_argument("--range", dest="a2", type=byte_value, default=0x03)
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--refresh-ms", type=int, default=30,
                   help="minimum GUI pause between frames")
    p.add_argument("--no-trigger", action="store_true",
                   help="do not align trace on a rising midpoint crossing")
    return p.parse_args()


def transact(scope, payload, timeout):
    t = scope.transact(payload, read_timeout_ms=timeout)
    if t.timed_out:
        raise HantekUSBError(f"{payload.hex(' ').upper()}: timeout")
    return t.rx or b""


def tx(scope, payload, timeout):
    return transact(scope, payload, timeout)


def query_size(scope, selector, timeout):
    b = transact(scope, bytes([0xC6, selector]), timeout)
    if len(b) != 2:
        raise HantekUSBError(
            f"C6 {selector:02X}: expected 2-byte size, got {len(b)}"
        )
    return int.from_bytes(b, "big")


def read_buffer(scope, selector, size, timeout):
    out = bytearray()
    packets = (size + 63) // 64
    for _ in range(packets):
        scope.write(bytes([0xA6, selector]), timeout_ms=timeout)
        b = scope.read(size=64, timeout_ms=timeout)
        if len(b) != 64:
            raise HantekUSBError(f"A6 {selector:02X}: short packet {len(b)}")
        out.extend(b)
    return bytes(out[:size])


def wait_ready(scope, timeout, tries=20):
    """Poll A5 until the hardware reports a completed/ready burst."""
    last = None
    for _ in range(tries):
        r = transact(scope, bytes.fromhex("A5 5A"), timeout)
        last = r[-1] if r else None
        if last in (2, 3):
            return last
        time.sleep(0.002)
    raise HantekUSBError(
        f"A5 never reached ready state 2/3 in {tries} polls "
        f"(last={last!r}); unplug/replug may be required"
    )


def read_capture_buffers(scope, timeout):
    n2 = query_size(scope, 2, timeout)
    b2 = read_buffer(scope, 2, n2, timeout)
    n3 = query_size(scope, 3, timeout)
    b3 = read_buffer(scope, 3, n3, timeout)
    return b2, b3


def calibration_burst(scope, range_id, timeout):
    tx(scope, b"\xF3", timeout)
    tx(scope, bytes([0xA2] + [range_id] * 8), timeout)
    tx(scope, bytes.fromhex("A4 01"), timeout)
    tx(scope, b"\xC0", timeout)
    time.sleep(0.0124)
    tx(scope, b"\xC2", timeout)
    wait_ready(scope, timeout)
    return read_capture_buffers(scope, timeout)


def configure_direct_adc(scope, ch, a3, a2, timeout):
    """Perform the full initialization proven to select direct-ADC burst mode."""
    aa = [0] * 8
    aa[ch - 1] = 1

    # mfg92-style init1.
    tx(scope, b"\xB0", timeout)
    time.sleep(0.7)
    tx(scope, b"\xB0", timeout)
    tx(scope, b"\xF3", timeout)
    tx(scope, bytes.fromhex("B9 01 B0 04 00 00"), timeout)
    tx(scope, bytes.fromhex("B7 00"), timeout)
    tx(scope, bytes.fromhex("BB 08 00"), timeout)
    for cmd in (b"\xB5", b"\xB6", b"\xE5", b"\xF7", b"\xF8", b"\xFA"):
        tx(scope, cmd, timeout)
    tx(scope, b"\xF5", timeout)
    tx(scope, bytes.fromhex("A0 08"), timeout)
    tx(scope, bytes.fromhex("AA 01 01 01 01 01 01 01 01"), timeout)
    tx(scope, bytes.fromhex("A3 11"), timeout)
    tx(scope, bytes.fromhex("C1 00 00"), timeout)
    tx(scope, bytes.fromhex("A7 00 00"), timeout)
    tx(scope, bytes.fromhex("AC 01 F4 00 09 C5 00 09 C5"), timeout)

    # Hardware zero-calibration passes.  Their data is intentionally not used
    # yet for voltage conversion; completing these passes is what matters for
    # selecting the proven direct-ADC acquisition state.
    for rid in (1, 2, 3):
        calibration_burst(scope, rid, timeout)

    # mfg92-style init3, generalized to the requested active channel/range/A3.
    tx(scope, b"\xF6", timeout)
    time.sleep(0.2132)
    for cmd in (b"\xE5", b"\xF7", b"\xF8", b"\xFA"):
        tx(scope, cmd, timeout)
    tx(scope, bytes([0xA3, a3]), timeout)
    tx(scope, bytes.fromhex("AC 00 C8 00 02 BD 00 02 BD"), timeout)
    tx(scope, bytes.fromhex("E4 01"), timeout)
    tx(scope, bytes.fromhex("E6 01"), timeout)
    tx(scope, b"\xF3", timeout)
    tx(scope, bytes([0xA0, 1]), timeout)
    tx(scope, bytes([0xAA] + aa), timeout)
    tx(scope, bytes([0xA2] + [a2] * 8), timeout)
    tx(scope, bytes([0xA3, a3]), timeout)
    tx(scope, bytes.fromhex("C1 00 00"), timeout)
    tx(scope, bytes.fromhex("A7 00 00"), timeout)
    tx(scope, bytes.fromhex("AC 00 00 00 00 01 00 05 79"), timeout)
    tx(scope, bytes.fromhex("AB 08 00"), timeout)
    tx(scope, b"\xE9", timeout)


def acquire_direct_adc(scope, timeout):
    """Acquire one direct-ADC frame without replaying full initialization."""
    tx(scope, b"\xF3", timeout)
    tx(scope, bytes.fromhex("E4 01"), timeout)
    tx(scope, bytes.fromhex("E6 01"), timeout)
    tx(scope, bytes.fromhex("A4 01"), timeout)
    time.sleep(0.015)
    tx(scope, b"\xC0", timeout)
    tx(scope, b"\xC2", timeout)
    ready = wait_ready(scope, timeout)
    b2, b3 = read_capture_buffers(scope, timeout)
    tx(scope, bytes.fromhex("E4 01"), timeout)
    tx(scope, bytes.fromhex("E6 01"), timeout)
    return b2, b3, ready


def trigger_align(y):
    if len(y) < 32:
        return y
    a = np.asarray(y, float)
    lo = np.percentile(a, 20)
    hi = np.percentile(a, 80)
    mid = (lo + hi) / 2
    start = max(1, len(a) // 10)
    stop = min(len(a) - 1, len(a) // 2)
    cross = np.where((a[start - 1:stop - 1] < mid) & (a[start:stop] >= mid))[0]
    if not len(cross):
        return a
    idx = int(cross[0] + start)
    target = len(a) // 4
    return np.roll(a, target - idx)


def main():
    a = args()
    fs = SAMPLE_RATES.get(a.a3)
    if fs is None:
        raise SystemExit(
            f"A3={a.a3:02X} has no validated sample-rate mapping; use 11,10,0F,0E"
        )

    plt.ion()
    fig, ax = plt.subplots(figsize=(12, 6))
    line, = ax.plot([], [], lw=1)
    ax.grid(True, alpha=.3)
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Direct ADC counts (12-bit; not volts)")
    title = ax.set_title("")
    status = ax.text(.01, .98, "", transform=ax.transAxes, va="top", ha="left")
    fig.canvas.manager.set_window_title(f"Hantek 1008C - CH{a.channel}")
    plt.show(block=False)

    frame = 0
    t0 = time.monotonic()
    try:
        with Hantek1008C() as scope:
            print("Initializing Hantek 1008C direct-ADC mode...")
            configure_direct_adc(scope, a.channel, a.a3, a.a2, a.timeout_ms)
            print("Direct-ADC mode initialized.")
            while plt.fignum_exists(fig.number):
                b2, b3, ready = acquire_direct_adc(scope, a.timeout_ms)
                dec = decode_buffers(b2, b3, active_channels=[a.channel])
                y = np.asarray(dec.channels[0], dtype=float)
                if not a.no_trigger:
                    y = trigger_align(y)

                x = np.arange(len(y)) / fs * 1000.0
                line.set_data(x, y)
                if len(x):
                    ax.set_xlim(x[0], x[-1] if len(x) > 1 else 1)
                if len(y):
                    lo, hi = np.percentile(y, [1, 99])
                    pad = max((hi - lo) * .15, 1.0)
                    ax.set_ylim(lo - pad, hi + pad)

                frame += 1
                elapsed = max(time.monotonic() - t0, 1e-6)
                fps = frame / elapsed
                title.set_text(
                    f"Hantek 1008C  CH{a.channel}   A2={a.a2:02X}   A3={a.a3:02X}   "
                    f"{fs / 1e6:.3f} MS/s   {len(y)} direct ADC samples"
                )
                if len(y):
                    status.set_text(
                        f"capture {frame}   {fps:.1f} frame/s   A5={ready}   "
                        f"min={np.min(y):.0f}  max={np.max(y):.0f}  mean={np.mean(y):.2f}"
                    )
                else:
                    status.set_text(
                        f"capture {frame}   {fps:.1f} frame/s   A5={ready}   empty frame"
                    )
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                plt.pause(max(a.refresh_ms, 1) / 1000.0)
    except KeyboardInterrupt:
        pass
    except HantekUSBError as exc:
        print(f"USB ERROR: {exc}", file=sys.stderr)
        return 4
    finally:
        plt.close("all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
