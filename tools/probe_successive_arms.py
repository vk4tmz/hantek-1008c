#!/usr/bin/env python3
"""Diagnostic-only map of successive normal Hantek 1008C acquisitions.

This probe does not modify the canonical acquisition implementation.  For each
requested A3 value it opens a fresh USB session, performs the validated full
direct-ADC initialization once, then executes several ordinary arm/wait/read
cycles.  C6 selectors 02 and 03 are recorded before each read, and exactly the
reported bytes are drained once.

The purpose is to determine whether successive arms alternate or otherwise use
buffers 02/03 differently, and whether acquisition depth changes with A3.  Raw
bytes are preserved for every triggered.  Comparisons are exact-byte/hash based;
there is no thresholding, smoothing, triggering, expected-waveform analysis, or
waveform-specific reconstruction.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import (
    DirectADCConfig,
    DirectADCSession,
    _read_buffer,
    _transact,
    wait_ready_with_polls,
)


def tx(scope, payload: bytes, timeout_ms: int) -> tuple[bytes, float]:
    t0 = time.perf_counter_ns()
    reply = _transact(scope, payload, timeout_ms)
    t1 = time.perf_counter_ns()
    return reply, (t1 - t0) / 1000.0


def query_c6(scope, selector: int, timeout_ms: int) -> dict:
    reply, elapsed_us = tx(scope, bytes([0xC6, selector]), timeout_ms)
    if len(reply) != 2:
        raise HantekUSBError(f"C6 {selector:02X}: expected 2 bytes, got {len(reply)}")
    return {
        "selector": selector,
        "reply_hex": reply.hex().upper(),
        "reported_bytes": int.from_bytes(reply, "big"),
        "elapsed_us": elapsed_us,
    }


def arm_wait(scope, timeout_ms: int) -> dict:
    phases = []
    a4_start_ns = None
    for name, payload in (
        ("f3", b"\xF3"),
        ("e4_pre", bytes.fromhex("E4 01")),
        ("e6_pre", bytes.fromhex("E6 01")),
        ("a4", bytes.fromhex("A4 01")),
        ("c0", b"\xC0"),
        ("c2", b"\xC2"),
    ):
        if name == "a4":
            a4_start_ns = time.perf_counter_ns()
        reply, elapsed_us = tx(scope, payload, timeout_ms)
        phases.append({"phase": name, "elapsed_us": elapsed_us, "reply_hex": reply.hex().upper()})
    a5 = {}
    state, polls = wait_ready_with_polls(scope, timeout_ms, metrics=a5)
    return {
        "a4_start_ns": a4_start_ns,
        "ready_state": state,
        "ready_polls": polls,
        "a5": a5,
        "phases": phases,
    }


def finish(scope, timeout_ms: int) -> list[dict]:
    rows = []
    for name, payload in (("e4_post", bytes.fromhex("E4 01")), ("e6_post", bytes.fromhex("E6 01"))):
        reply, elapsed_us = tx(scope, payload, timeout_ms)
        rows.append({"phase": name, "elapsed_us": elapsed_us, "reply_hex": reply.hex().upper()})
    return rows


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_a3_list(text: str) -> list[int]:
    values = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part, 16))
    if not values:
        raise ValueError("empty A3 list")
    return values


def run_a3(a3: int, args, stamp: str) -> dict:
    cfg = DirectADCConfig(channel=args.channel, a3=a3, range_id=args.range_id)
    row = {
        "a3": f"{a3:02X}",
        "sample_rate_hz": cfg.sample_rate,
        "triggered_acquisitions": [],
    }

    with Hantek1008C() as scope:
        row["device"] = scope.connection_id
        DirectADCSession(scope, cfg).initialize()
        previous_a4 = None
        previous_combined = None

        for index in range(1, args.triggered_acquisitions + 1):
            readiness = arm_wait(scope, cfg.timeout_ms)
            c602 = query_c6(scope, 2, cfg.timeout_ms)
            c603 = query_c6(scope, 3, cfg.timeout_ms)

            m2, m3 = {}, {}
            b2 = _read_buffer(scope, 2, c602["reported_bytes"], cfg.timeout_ms, metrics=m2)
            b3 = _read_buffer(scope, 3, c603["reported_bytes"], cfg.timeout_ms, metrics=m3)
            cleanup = finish(scope, cfg.timeout_ms)
            combined = b2 + b3

            prefix = f"{stamp}_successive-a3-{a3:02X}_triggered-{index:02d}"
            p2 = args.output_dir / f"{prefix}_buffer02.bin"
            p3 = args.output_dir / f"{prefix}_buffer03.bin"
            pc = args.output_dir / f"{prefix}_combined.bin"
            p2.write_bytes(b2)
            p3.write_bytes(b3)
            pc.write_bytes(combined)

            a4_gap_ms = None
            if previous_a4 is not None and readiness["a4_start_ns"] is not None:
                a4_gap_ms = (readiness["a4_start_ns"] - previous_a4) / 1_000_000.0
            previous_a4 = readiness["a4_start_ns"]

            triggered = {
                "index": index,
                "readiness": readiness,
                "a4_to_previous_a4_ms": a4_gap_ms,
                "c6_02": c602,
                "c6_03": c603,
                "buffer02_bytes": len(b2),
                "buffer03_bytes": len(b3),
                "combined_bytes": len(combined),
                "combined_u16_words": len(combined) // 2,
                "nominal_time_span_ms_at_validated_rate": (len(combined) / 2) / cfg.sample_rate * 1000.0,
                "buffer02_sha256": sha256(b2),
                "buffer03_sha256": sha256(b3),
                "combined_sha256": sha256(combined),
                "combined_equals_previous_exactly": (combined == previous_combined) if previous_combined is not None else None,
                "buffer02_metrics": m2,
                "buffer03_metrics": m3,
                "cleanup": cleanup,
                "files": {
                    "buffer02": str(p2),
                    "buffer03": str(p3),
                    "combined": str(pc),
                },
            }
            previous_combined = combined
            row["triggered_acquisitions"].append(triggered)
            print(
                f"  triggered {index:02d}: A5={readiness['ready_state']}/{readiness['ready_polls']} "
                f"C6[02]={c602['reported_bytes']:5d} B C6[03]={c603['reported_bytes']:5d} B "
                f"total={len(combined):5d} B/{len(combined)//2:4d} words "
                f"same-prev={triggered['combined_equals_previous_exactly']}"
            )

    sizes = [(b["buffer02_bytes"], b["buffer03_bytes"]) for b in row["triggered_acquisitions"]]
    row["summary"] = {
        "c6_size_pairs": sizes,
        "all_size_pairs_identical": len(set(sizes)) <= 1,
        "unique_combined_hashes": len(set(b["combined_sha256"] for b in row["triggered_acquisitions"])),
        "any_buffer02_nonzero": any(b["buffer02_bytes"] for b in row["triggered_acquisitions"]),
        "any_buffer03_nonzero": any(b["buffer03_bytes"] for b in row["triggered_acquisitions"]),
    }
    return row


def main() -> int:
    p = argparse.ArgumentParser(description="Map successive normal Hantek acquisition arms")
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument("--a3-list", default="0F,11", help="comma-separated A3 bytes (default: 0F,11)")
    p.add_argument("--triggered-acquisitions", type=int, default=8, help="normal acquisitions per A3 value (default: 8)")
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    args = p.parse_args()

    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.triggered_acquisitions < 2:
        p.error("--triggered-acquisitions must be >= 2")
    try:
        a3_values = parse_a3_list(args.a3_list)
        # Validate all values through DirectADCConfig.sample_rate before touching USB.
        for value in a3_values:
            _ = DirectADCConfig(channel=args.channel, a3=value, range_id=args.range_id).sample_rate
    except (ValueError, KeyError) as exc:
        p.error(str(exc))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"CH{args.channel}, A2={args.range_id:02X}; successive-arm diagnostic only.")
    print("Each A3 value uses a fresh full initialization; canonical acquisition is unchanged.")
    print("Every triggered records C6 02/03 before a single exact reported-length drain.\n")

    results = []
    for a3 in a3_values:
        cfg = DirectADCConfig(channel=args.channel, a3=a3, range_id=args.range_id)
        print(f"=== A3={a3:02X} ({cfg.sample_rate/1e6:.3f} MS/s), {args.triggered_acquisitions} triggered_acquisitions ===")
        try:
            result = run_a3(a3, args, stamp)
        except Exception as exc:
            result = {"a3": f"{a3:02X}", "error": f"{type(exc).__name__}: {exc}"}
            print(f"  FAIL: {result['error']}")
        results.append(result)
        print()

    out = args.output_dir / f"{stamp}_successive-arms.json"
    payload = {
        "format": "hantek1008c-successive-arms-v1",
        "timestamp_utc": stamp,
        "channel": args.channel,
        "range_a2": f"{args.range_id:02X}",
        "a3_values": [f"{x:02X}" for x in a3_values],
        "triggered_acquisitions_per_a3": args.triggered_acquisitions,
        "experiments": results,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Detailed results: {out}")
    print(f"Raw triggered files : {args.output_dir}/{stamp}_successive-a3-*_triggered-*_*.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
