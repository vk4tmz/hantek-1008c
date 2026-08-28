#!/usr/bin/env python3
"""Capture many direct-ADC bursts while preserving exact burst boundaries."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession, acquire_direct_buffers, decode_direct_u12


def main() -> int:
    p = argparse.ArgumentParser(description=(
        "Capture a long direct-ADC run as independent hardware bursts. Raw samples and "
        "burst boundaries are preserved; no waveform-specific processing is performed."
    ))
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument("--a3", type=lambda s: int(s, 16), default=0x0F)
    p.add_argument("--samples", type=int, default=100000)
    p.add_argument("--arm-delay-ms", type=float, default=0.0)
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    p.add_argument("--tag", default="long-direct")
    args = p.parse_args()
    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.samples < 1:
        p.error("--samples must be >= 1")
    if args.arm_delay_ms < 0:
        p.error("--arm-delay-ms must be >= 0")

    cfg = DirectADCConfig(channel=args.channel, a3=args.a3, range_id=args.range_id)
    target_bursts = (args.samples + 3999) // 4000
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{args.tag}_{args.samples}samples"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.output_dir / f"{base}.u16le"
    meta_path = args.output_dir / f"{base}.json"
    boundaries_path = args.output_dir / f"{base}_bursts.jsonl"

    print(f"Target: CH{cfg.channel}, A2={cfg.range_id:02X}, A3={cfg.a3:02X}, {cfg.sample_rate/1e6:.3f} MS/s")
    print(f"Requested samples: {args.samples}; planned bursts: {target_bursts}; arm delay: {args.arm_delay_ms:g} ms")
    print("Raw/integrity capture only; burst boundaries are preserved explicitly.\n")

    all_words: list[int] = []
    burst_rows = []
    started_all = time.perf_counter()
    device_id = None

    with Hantek1008C() as scope:
        device_id = scope.connection_id
        print(f"Device: {device_id}")
        session = DirectADCSession(scope, cfg)
        session.initialize()

        for burst in range(1, target_bursts + 1):
            started = time.perf_counter()
            try:
                b2, b3, ready_state, ready_polls = acquire_direct_buffers(
                    scope, cfg.timeout_ms,
                    arm_delay_s=args.arm_delay_ms / 1000.0,
                    return_ready_info=True,
                )
            except HantekUSBError as exc:
                print(f"burst {burst}: FAIL: {exc}")
                return 2
            ended = time.perf_counter()
            words = decode_direct_u12((b2, b3))
            if len(words) != 4000:
                print(f"burst {burst}: FAIL: expected 4000 words, got {len(words)}")
                return 2
            keep = min(len(words), args.samples - len(all_words))
            kept_words = words[:keep]
            global_start = len(all_words)
            all_words.extend(kept_words)
            row = {
                "burst": burst,
                "global_start": global_start,
                "samples_kept": keep,
                "hardware_words": len(words),
                "ready_state": ready_state,
                "ready_polls": ready_polls,
                "elapsed_ms": (ended - started) * 1000.0,
                "min": min(words),
                "max": max(words),
                "zeros": words.count(0),
                "buffer02_bytes": len(b2),
                "buffer03_bytes": len(b3),
                "first8": words[:8],
                "last8": words[-8:],
            }
            burst_rows.append(row)
            print(
                f"burst {burst:3d}/{target_bursts}: words=4000 ready={ready_state} polls={ready_polls} "
                f"elapsed={row['elapsed_ms']:.2f} ms min={row['min']} max={row['max']} zeros={row['zeros']}"
            )

    total_elapsed_ms = (time.perf_counter() - started_all) * 1000.0
    with raw_path.open("wb") as fh:
        for word in all_words:
            fh.write(struct.pack("<H", word))
    with boundaries_path.open("w", encoding="utf-8") as fh:
        for row in burst_rows:
            fh.write(json.dumps(row, separators=(",", ":")) + "\n")

    metadata = {
        "format": "hantek1008c-long-direct-v1",
        "timestamp_utc": stamp,
        "device": device_id,
        "channel": cfg.channel,
        "range_a2": f"{cfg.range_id:02X}",
        "a3": f"{cfg.a3:02X}",
        "sample_rate_hz_within_burst": cfg.sample_rate,
        "arm_delay_ms": args.arm_delay_ms,
        "requested_samples": args.samples,
        "samples_written": len(all_words),
        "hardware_burst_words": 4000,
        "burst_count": len(burst_rows),
        "total_wall_elapsed_ms_including_init": total_elapsed_ms,
        "raw_file": raw_path.name,
        "bursts_file": boundaries_path.name,
        "note": "Samples are contiguous only within each 4000-word hardware burst; burst boundaries must not be interpreted as gap-free sample time.",
    }
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print("\nCapture complete.")
    print(f"Raw samples : {raw_path}")
    print(f"Burst map   : {boundaries_path}")
    print(f"Metadata    : {meta_path}")
    print(f"Samples     : {len(all_words)} in {len(burst_rows)} hardware bursts")
    print(f"Zeros total : {sum(row['zeros'] for row in burst_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
