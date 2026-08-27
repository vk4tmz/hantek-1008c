#!/usr/bin/env python3
"""Basic live Hantek 1008C viewer using the canonical direct-ADC path."""
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

from hantek1008c.acquire import DirectADCConfig, DirectADCSession, SAMPLE_RATES
from hantek1008c.transport import Hantek1008C, HantekUSBError


def byte_value(value):
    try:
        result = int(value, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected hexadecimal byte, e.g. 0F or 03") from exc
    if not 0 <= result <= 255:
        raise argparse.ArgumentTypeError("byte must be 00..FF")
    return result


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--channel", type=int, required=True, choices=range(1, 9))
    p.add_argument("--a3", type=byte_value, default=0x0F)
    p.add_argument("--range", dest="a2", type=byte_value, default=0x03)
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--refresh-ms", type=int, default=30)
    p.add_argument("--no-trigger", action="store_true",
                   help="do not align the trace on a rising midpoint crossing")
    return p.parse_args()


def trigger_align(values):
    if len(values) < 32:
        return values
    a = np.asarray(values, float)
    lo, hi = np.percentile(a, [20, 80])
    mid = (lo + hi) / 2
    start = max(1, len(a) // 10)
    stop = min(len(a) - 1, len(a) // 2)
    cross = np.where((a[start - 1:stop - 1] < mid) & (a[start:stop] >= mid))[0]
    if not len(cross):
        return a
    idx = int(cross[0] + start)
    return np.roll(a, len(a) // 4 - idx)


def main():
    args = parse_args()
    if args.a3 not in SAMPLE_RATES:
        raise SystemExit(f"A3={args.a3:02X} has no validated sample-rate mapping; use 11,10,0F,0E")

    cfg = DirectADCConfig(
        channel=args.channel,
        a3=args.a3,
        range_id=args.a2,
        timeout_ms=args.timeout_ms,
    )
    fs = cfg.sample_rate

    plt.ion()
    fig, ax = plt.subplots(figsize=(12, 6))
    line, = ax.plot([], [], lw=1)
    ax.grid(True, alpha=.3)
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel("Direct ADC counts (12-bit; not volts)")
    title = ax.set_title("")
    status = ax.text(.01, .98, "", transform=ax.transAxes, va="top", ha="left")
    fig.canvas.manager.set_window_title(f"Hantek 1008C - CH{args.channel}")
    plt.show(block=False)

    frame = 0
    t0 = time.monotonic()
    try:
        with Hantek1008C() as scope:
            session = DirectADCSession(scope, cfg)
            print("Initializing Hantek 1008C direct-ADC mode...")
            calibration = session.initialize()
            print(f"Initialization complete; range-03 calibration={calibration.get(3)}")

            while plt.fignum_exists(fig.number):
                raw = np.asarray(session.acquire_words(), dtype=float)
                y = raw if args.no_trigger else trigger_align(raw)
                x = np.arange(len(y)) / fs * 1000.0

                line.set_data(x, y)
                ax.set_xlim(x[0], x[-1] if len(x) > 1 else 1)
                if len(y):
                    lo, hi = np.percentile(y, [1, 99])
                    pad = max((hi - lo) * .15, 1.0)
                    ax.set_ylim(lo - pad, hi + pad)

                frame += 1
                fps = frame / max(time.monotonic() - t0, 1e-6)
                title.set_text(
                    f"Hantek 1008C  CH{args.channel}   A2={args.a2:02X}   "
                    f"A3={args.a3:02X}   {fs / 1e6:.3f} MS/s   {len(raw)} samples"
                )
                status.set_text(f"capture {frame}   {fps:.1f} frame/s   direct ADC")
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                plt.pause(max(args.refresh_ms, 1) / 1000.0)
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
