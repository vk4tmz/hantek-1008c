#!/usr/bin/env python3
"""Sweep the A4 -> C0/C2 arm delay for direct-ADC Triggered acquisition."""
from __future__ import annotations

import argparse
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import (
    DirectADCConfig,
    DirectADCSession,
    acquire_direct_buffers,
    decode_direct_u12,
)


def parse_delays(value: str) -> list[float]:
    try:
        values = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("delays must be comma-separated milliseconds") from exc
    if not values or any(value < 0 for value in values):
        raise argparse.ArgumentTypeError("delays must contain non-negative milliseconds")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure direct-ADC acquisition behaviour while reducing the fixed "
            "delay between A4 arm and C0/C2. No sample filtering or waveform-specific "
            "quality test is performed."
        )
    )
    parser.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    parser.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    parser.add_argument("--a3", type=lambda s: int(s, 16), default=0x0F)
    parser.add_argument("--delays-ms", type=parse_delays, default=parse_delays("15,5,2,1,0"))
    parser.add_argument("--triggered-acquisitions", type=int, default=5)
    args = parser.parse_args()
    if args.range_id not in (1, 2, 3):
        parser.error("--range must be 01, 02, or 03")
    if args.triggered_acquisitions < 1:
        parser.error("--triggered-acquisitions must be >= 1")

    cfg = DirectADCConfig(channel=args.channel, a3=args.a3, range_id=args.range_id)
    print(
        f"Target: CH{cfg.channel}, A2={cfg.range_id:02X}, A3={cfg.a3:02X}, "
        f"{cfg.sample_rate/1e6:.3f} MS/s"
    )
    print(f"Sweep: {', '.join(f'{d:g} ms' for d in args.delays_ms)}; {args.triggered_acquisitions} triggered_acquisitions each")
    print("Metrics are raw/integrity-only; no waveform cleanup or expected-shape test is used.\n")

    failures = 0
    with Hantek1008C() as scope:
        print(f"Device: {scope.connection_id}")
        session = DirectADCSession(scope, cfg)
        session.initialize()

        for delay_ms in args.delays_ms:
            elapsed_ms: list[float] = []
            polls: list[int] = []
            word_counts: list[int] = []
            zero_counts: list[int] = []
            mins: list[int] = []
            maxs: list[int] = []
            print(f"\n=== arm delay {delay_ms:g} ms ===")
            for run in range(1, args.triggered_acquisitions + 1):
                started = time.perf_counter()
                try:
                    b2, b3, ready_state, ready_polls = acquire_direct_buffers(
                        scope,
                        cfg.timeout_ms,
                        arm_delay_s=delay_ms / 1000.0,
                        return_ready_info=True,
                    )
                    words = decode_direct_u12((b2, b3))
                except HantekUSBError as exc:
                    failures += 1
                    print(f"run {run}: FAIL: {exc}")
                    continue
                took_ms = (time.perf_counter() - started) * 1000.0
                elapsed_ms.append(took_ms)
                polls.append(ready_polls)
                word_counts.append(len(words))
                zero_counts.append(words.count(0))
                mins.append(min(words) if words else -1)
                maxs.append(max(words) if words else -1)
                integrity = "OK" if len(words) == 4000 else "BAD"
                print(
                    f"run {run}: {integrity} words={len(words)} ready={ready_state} "
                    f"polls={ready_polls} elapsed={took_ms:.2f} ms "
                    f"min={mins[-1]} max={maxs[-1]} zeros={zero_counts[-1]}"
                )

            if elapsed_ms:
                print(
                    "summary: "
                    f"ok={len(elapsed_ms)}/{args.triggered_acquisitions} "
                    f"elapsed_median={statistics.median(elapsed_ms):.2f} ms "
                    f"polls_median={statistics.median(polls):g} "
                    f"words={min(word_counts)}..{max(word_counts)} "
                    f"zeros_total={sum(zero_counts)}"
                )

    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
