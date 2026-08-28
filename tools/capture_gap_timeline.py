#!/usr/bin/env python3
"""Capture direct-ADC bursts and reconstruct a truthful gap-aware time axis."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession, acquire_direct_buffers, decode_direct_u12
from hantek1008c.gap_timeline import build_gap_timeline, estimate_square_frequency_per_burst


def main() -> int:
    p = argparse.ArgumentParser(description=(
        "Capture repeated 4000-sample bursts and place them on an irregular time axis "
        "with explicit missing-time gaps. Real ADC samples are never filled/interpolated."
    ))
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument("--a3", type=lambda s: int(s, 16), default=0x0F)
    p.add_argument("--bursts", type=int, default=25)
    p.add_argument("--arm-delay-ms", type=float, default=0.0)
    p.add_argument("--validate-square-hz", type=float, default=None,
                   help="validation only; report within-burst square-wave frequency")
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    p.add_argument("--tag", default="gap-timeline")
    args = p.parse_args()
    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.bursts < 1:
        p.error("--bursts must be >= 1")

    cfg = DirectADCConfig(channel=args.channel, a3=args.a3, range_id=args.range_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / f"{stamp}_{args.tag}_{args.bursts}bursts.csv"
    json_path = args.output_dir / f"{stamp}_{args.tag}_{args.bursts}bursts.json"

    print(f"Target: CH{cfg.channel}, A2={cfg.range_id:02X}, A3={cfg.a3:02X}, {cfg.sample_rate/1e6:.3f} MS/s")
    print(f"Bursts: {args.bursts}; gap derived from successive measured A4 acquisition starts; arm delay={args.arm_delay_ms:g} ms")
    print("No samples are synthesized in missing time; CSV uses a NaN break between bursts.\n")

    bursts: list[list[int]] = []
    burst_start_s: list[float] = []
    call_elapsed_s: list[float] = []
    device = None
    with Hantek1008C() as scope:
        device = scope.connection_id
        print(f"Device: {device}")
        DirectADCSession(scope, cfg).initialize()
        for n in range(1, args.bursts + 1):
            started = time.perf_counter_ns()
            try:
                b2, b3, state, polls, metrics = acquire_direct_buffers(
                    scope, cfg.timeout_ms,
                    arm_delay_s=args.arm_delay_ms / 1000.0,
                    return_ready_info=True,
                    return_metrics=True,
                )
            except HantekUSBError as exc:
                print(f"burst {n}: FAIL: {exc}")
                return 2
            ended = time.perf_counter_ns()
            words = decode_direct_u12((b2, b3))
            if len(words) != 4000:
                print(f"burst {n}: FAIL expected 4000 words, got {len(words)}")
                return 2
            cycle_s = (ended - started) / 1e9
            bursts.append(words)
            burst_start_s.append(metrics["a4_start_ns"] / 1e9)
            call_elapsed_s.append(cycle_s)
            sample_ms = len(words) / cfg.sample_rate * 1000.0
            freq_text = ""
            if args.validate_square_hz is not None:
                freq, edges = estimate_square_frequency_per_burst(words, cfg.sample_rate)
                freq_text = f" freq={freq:.2f} Hz/{edges} rises" if freq is not None else f" freq=unresolved/{edges} rises"
            print(f"burst {n:3d}: call={cycle_s*1000:.3f} ms real={sample_ms:.3f} ms A5={state}/{polls}{freq_text}")

    times, values, rows = build_gap_timeline(bursts, burst_start_s, cfg.sample_rate)
    for row in rows[:-1]:
        print(f"gap after burst {row.burst:3d}: start-to-start={row.cycle_elapsed_s*1000:.3f} ms gap={row.gap_after_s*1000:.3f} ms")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["time_s", "adc", "kind"])
        for t, v in zip(times, values):
            if v != v:
                w.writerow([f"{t:.12f}", "nan", "gap"])
            else:
                w.writerow([f"{t:.12f}", int(v), "sample"])

    frequencies = []
    validation_rows = []
    if args.validate_square_hz is not None:
        for i, words in enumerate(bursts, 1):
            freq, edges = estimate_square_frequency_per_burst(words, cfg.sample_rate)
            validation_rows.append({"burst": i, "frequency_hz": freq, "rising_edges": edges})
            if freq is not None:
                frequencies.append(freq)

    meta = {
        "format": "hantek1008c-gap-timeline-v1",
        "timestamp_utc": stamp,
        "device": device,
        "channel": cfg.channel,
        "range_a2": f"{cfg.range_id:02X}",
        "a3": f"{cfg.a3:02X}",
        "sample_rate_hz_within_burst": cfg.sample_rate,
        "burst_samples": 4000,
        "burst_count": len(rows),
        "gap_rule": "gap_after[i] = max(0, A4_start[i+1] - A4_start[i] - real_sample_duration); no inferred gap after final burst",
        "a4_start_monotonic_s": burst_start_s,
        "capture_call_elapsed_s": call_elapsed_s,
        "timeline": [r.__dict__ for r in rows],
        "validation_square_hz_expected": args.validate_square_hz,
        "validation": validation_rows,
        "validation_frequency_median_hz": statistics.median(frequencies) if frequencies else None,
        "csv": csv_path.name,
        "note": "Frequency validation is test-source-specific and does not affect acquisition/reconstruction. Boundary-adjacent missing time is represented as NaN, never synthesized ADC values.",
    }
    json_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    gaps_ms = [r.gap_after_s * 1000.0 for r in rows[:-1]]
    print("\nGap-aware reconstruction:")
    print(f"  real burst duration : {4000/cfg.sample_rate*1000:.3f} ms")
    if gaps_ms:
        print(f"  gap median          : {statistics.median(gaps_ms):.3f} ms")
        print(f"  gap min..max        : {min(gaps_ms):.3f} .. {max(gaps_ms):.3f} ms")
    else:
        print("  gap                 : unresolved (need >=2 bursts)")
    if frequencies:
        print(f"  within-burst freq   : median={statistics.median(frequencies):.3f} Hz min={min(frequencies):.3f} max={max(frequencies):.3f}")
        if args.validate_square_hz:
            err = 100.0 * (statistics.median(frequencies) - args.validate_square_hz) / args.validate_square_hz
            print(f"  median freq error   : {err:+.4f}%")
    print(f"\nTimeline CSV : {csv_path}")
    print(f"Metadata     : {json_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
