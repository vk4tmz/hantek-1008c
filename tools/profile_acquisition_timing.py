#!/usr/bin/env python3
"""Profile one-burst Hantek 1008C direct-ADC timing without altering samples."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession, acquire_direct_buffers, decode_direct_u12


def median(values):
    return statistics.median(values) if values else 0.0


def percentile(values, pct):
    if not values:
        return 0.0
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * pct / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    frac = pos - lo
    return data[lo] * (1.0 - frac) + data[hi] * frac


def main() -> int:
    p = argparse.ArgumentParser(description=(
        "Measure direct-ADC protocol/USB timing by phase. Timing is observational only; "
        "captured ADC words are neither filtered nor waveform-scored."
    ))
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument("--a3", type=lambda s: int(s, 16), default=0x0F)
    p.add_argument("--bursts", type=int, default=25)
    p.add_argument("--arm-delay-ms", type=float, default=0.0)
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    p.add_argument("--tag", default="acquisition-timing")
    args = p.parse_args()
    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.bursts < 1:
        p.error("--bursts must be >= 1")
    if args.arm_delay_ms < 0:
        p.error("--arm-delay-ms must be >= 0")

    cfg = DirectADCConfig(channel=args.channel, a3=args.a3, range_id=args.range_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.output_dir / f"{stamp}_{args.tag}_{args.bursts}bursts.jsonl"
    summary_path = args.output_dir / f"{stamp}_{args.tag}_{args.bursts}bursts_summary.json"

    print(f"Target: CH{cfg.channel}, A2={cfg.range_id:02X}, A3={cfg.a3:02X}, {cfg.sample_rate/1e6:.3f} MS/s")
    print(f"Bursts: {args.bursts}; arm delay: {args.arm_delay_ms:g} ms")
    print("Timing only; raw acquisition semantics are unchanged.\n")

    rows = []
    with Hantek1008C() as scope:
        print(f"Device: {scope.connection_id}")
        DirectADCSession(scope, cfg).initialize()
        for n in range(1, args.bursts + 1):
            try:
                b2, b3, state, polls, m = acquire_direct_buffers(
                    scope,
                    cfg.timeout_ms,
                    arm_delay_s=args.arm_delay_ms / 1000.0,
                    return_ready_info=True,
                    return_metrics=True,
                )
            except HantekUSBError as exc:
                print(f"burst {n}: FAIL: {exc}")
                return 2
            words = decode_direct_u12((b2, b3))
            row = {
                "burst": n,
                "ready_state": state,
                "ready_polls": polls,
                "words": len(words),
                "zeros": words.count(0),
                "min": min(words) if words else None,
                "max": max(words) if words else None,
                "timing": m,
            }
            rows.append(row)
            b3m = m["buffer03"]
            print(
                f"burst {n:3d}: total={m['total_ms']:.3f} ms "
                f"A5={m['a5']['elapsed_ms']:.3f} ms/{polls} polls "
                f"C6-03={b3m['c6_ms']:.3f} ms "
                f"A6-03={b3m['a6']['elapsed_ms']:.3f} ms/{b3m['a6']['packets']} pkts "
                f"words={len(words)} zeros={row['zeros']}"
            )

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    phase_paths = {
        "f3_ms": lambda m: m["f3_ms"],
        "e4_pre_ms": lambda m: m["e4_pre_ms"],
        "e6_pre_ms": lambda m: m["e6_pre_ms"],
        "a4_ms": lambda m: m["a4_ms"],
        "c0_ms": lambda m: m["c0_ms"],
        "c2_ms": lambda m: m["c2_ms"],
        "a5_ms": lambda m: m["a5"]["elapsed_ms"],
        "c6_02_ms": lambda m: m["buffer02"]["c6_ms"],
        "a6_02_ms": lambda m: m["buffer02"]["a6"]["elapsed_ms"],
        "c6_03_ms": lambda m: m["buffer03"]["c6_ms"],
        "a6_03_ms": lambda m: m["buffer03"]["a6"]["elapsed_ms"],
        "e4_post_ms": lambda m: m["e4_post_ms"],
        "e6_post_ms": lambda m: m["e6_post_ms"],
        "total_ms": lambda m: m["total_ms"],
    }
    phases = {}
    for name, getter in phase_paths.items():
        vals = [getter(r["timing"]) for r in rows]
        phases[name] = {
            "min": min(vals), "median": median(vals), "p95": percentile(vals, 95), "max": max(vals)
        }

    a6_packets = [
        p
        for r in rows
        for p in r["timing"]["buffer03"]["a6"]["packet_metrics"]
    ]
    packet_totals = [p["total_us"] for p in a6_packets]
    packet_writes = [p["write_us"] for p in a6_packets]
    packet_reads = [p["read_us"] for p in a6_packets]
    summary = {
        "format": "hantek1008c-acquisition-timing-v1",
        "timestamp_utc": stamp,
        "channel": cfg.channel,
        "range_a2": f"{cfg.range_id:02X}",
        "a3": f"{cfg.a3:02X}",
        "sample_rate_hz_within_burst": cfg.sample_rate,
        "arm_delay_ms": args.arm_delay_ms,
        "bursts": len(rows),
        "phase_ms": phases,
        "buffer03_a6_packet_us": {
            "count": len(packet_totals),
            "total": {"min": min(packet_totals), "median": median(packet_totals), "p95": percentile(packet_totals, 95), "max": max(packet_totals)},
            "write": {"median": median(packet_writes), "p95": percentile(packet_writes, 95)},
            "read": {"median": median(packet_reads), "p95": percentile(packet_reads, 95)},
        },
        "integrity": {
            "word_counts": sorted(set(r["words"] for r in rows)),
            "zeros_total": sum(r["zeros"] for r in rows),
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print("\nMedian phase timing:")
    for name in ("f3_ms", "e4_pre_ms", "e6_pre_ms", "a4_ms", "c0_ms", "c2_ms", "a5_ms", "c6_02_ms", "a6_02_ms", "c6_03_ms", "a6_03_ms", "e4_post_ms", "e6_post_ms", "total_ms"):
        print(f"  {name:12s} {phases[name]['median']:8.3f} ms   p95={phases[name]['p95']:8.3f}")
    pkt = summary["buffer03_a6_packet_us"]
    print(f"\nA6 buffer03 packets: {pkt['count']} total")
    print(f"  packet total median={pkt['total']['median']:.1f} us p95={pkt['total']['p95']:.1f} us max={pkt['total']['max']:.1f} us")
    print(f"  write median={pkt['write']['median']:.1f} us; read median={pkt['read']['median']:.1f} us")
    print(f"\nDetailed bursts: {jsonl_path}")
    print(f"Summary        : {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
