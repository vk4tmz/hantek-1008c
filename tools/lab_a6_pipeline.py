#!/usr/bin/env python3
"""Diagnostic-only Hantek 1008C A6 command-pipelining probes.

The canonical acquisition path remains untouched.  Each queue depth uses a
fresh USB/device initialization, captures one normal direct-ADC burst, then
reads buffer 03 by sending up to N A6 commands before reading the matching N
64-byte replies.  Every returned byte and per-batch timing is preserved.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession, _query_buffer, _transact, wait_ready_with_polls


def arm_ready(scope, timeout_ms: int):
    for payload in (b"\xF3", bytes.fromhex("E4 01"), bytes.fromhex("E6 01"),
                    bytes.fromhex("A4 01"), b"\xC0", b"\xC2"):
        _transact(scope, payload, timeout_ms)
    m = {}
    state, polls = wait_ready_with_polls(scope, timeout_ms, metrics=m)
    return state, polls, m


def read_pipelined(scope, selector: int, size: int, depth: int, timeout_ms: int):
    total_packets = math.ceil(size / 64)
    out = bytearray()
    batches = []
    packet_lengths = []
    packet_index = 0

    while packet_index < total_packets:
        n = min(depth, total_packets - packet_index)
        b0 = time.perf_counter_ns()
        write_times = []
        for _ in range(n):
            w0 = time.perf_counter_ns()
            scope.write(bytes([0xA6, selector]), timeout_ms=timeout_ms)
            w1 = time.perf_counter_ns()
            write_times.append((w1 - w0) / 1000.0)
        writes_done = time.perf_counter_ns()

        read_times = []
        lengths = []
        for _ in range(n):
            r0 = time.perf_counter_ns()
            packet = scope.read(size=64, timeout_ms=timeout_ms)
            r1 = time.perf_counter_ns()
            if len(packet) != 64:
                raise HantekUSBError(f"A6 {selector:02X}: short packet {len(packet)} at packet {packet_index}")
            out.extend(packet)
            lengths.append(len(packet))
            packet_lengths.append(len(packet))
            read_times.append((r1 - r0) / 1000.0)
            packet_index += 1
        b1 = time.perf_counter_ns()
        batches.append({
            "batch": len(batches),
            "commands": n,
            "write_total_us": (writes_done - b0) / 1000.0,
            "read_total_us": (b1 - writes_done) / 1000.0,
            "total_us": (b1 - b0) / 1000.0,
            "write_us": write_times,
            "read_us": read_times,
            "lengths": lengths,
        })

    logical = bytes(out[:size])
    return {
        "depth": depth,
        "reported_bytes": size,
        "returned_bytes": len(out),
        "logical_bytes": len(logical),
        "packet_count": total_packets,
        "packet_lengths": packet_lengths,
        "data_hex": logical.hex().upper(),
        "batches": batches,
        "transfer_total_us": sum(x["total_us"] for x in batches),
    }


def run_depth(depth: int, cfg: DirectADCConfig):
    with Hantek1008C() as scope:
        device = scope.connection_id
        DirectADCSession(scope, cfg).initialize()
        state, polls, a5 = arm_ready(scope, cfg.timeout_ms)
        b2 = _query_buffer(scope, 2, cfg.timeout_ms)
        reply = _transact(scope, bytes([0xC6, 3]), cfg.timeout_ms)
        if len(reply) != 2:
            raise HantekUSBError(f"C6 03: expected 2-byte size, got {len(reply)}")
        size03 = int.from_bytes(reply, "big")
        t0 = time.perf_counter_ns()
        result = read_pipelined(scope, 3, size03, depth, cfg.timeout_ms)
        t1 = time.perf_counter_ns()
        _transact(scope, bytes.fromhex("E4 01"), cfg.timeout_ms)
        _transact(scope, bytes.fromhex("E6 01"), cfg.timeout_ms)
        result["wall_transfer_us"] = (t1 - t0) / 1000.0
        return {
            "depth": depth,
            "device": device,
            "ready_state": state,
            "ready_polls": polls,
            "a5": a5,
            "buffer02_bytes": len(b2),
            "buffer03_bytes": size03,
            "result": result,
        }


def pct(values, q):
    if not values:
        return 0.0
    vals = sorted(values)
    idx = (len(vals) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(vals) - 1)
    f = idx - lo
    return vals[lo] * (1 - f) + vals[hi] * f


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnostic-only A6 command-pipelining lab")
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument("--a3", type=lambda s: int(s, 16), default=0x0F)
    p.add_argument("--depths", default="1,2,4,8,16", help="comma-separated A6 queue depths")
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    args = p.parse_args()
    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    try:
        depths = [int(x.strip()) for x in args.depths.split(",") if x.strip()]
    except ValueError:
        p.error("--depths must be comma-separated positive integers")
    if not depths or any(d < 1 or d > 125 for d in depths):
        p.error("--depths values must be 1..125")

    cfg = DirectADCConfig(channel=args.channel, a3=args.a3, range_id=args.range_id)
    print(f"Target: CH{cfg.channel}, A2={cfg.range_id:02X}, A3={cfg.a3:02X}, {cfg.sample_rate/1e6:.3f} MS/s")
    print(f"A6 pipeline depths: {', '.join(map(str, depths))}")
    print("Each depth uses a fresh USB/device initialization; canonical acquisition is unchanged.\n")

    rows = []
    baseline_hex = None
    for depth in depths:
        print(f"=== depth {depth} ===")
        try:
            row = run_depth(depth, cfg)
        except Exception as exc:
            row = {"depth": depth, "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            print(f"FAIL: {row['error']}\n")
            continue
        rows.append(row)
        r = row["result"]
        batch_us = [b["total_us"] for b in r["batches"]]
        all_writes = [x for b in r["batches"] for x in b["write_us"]]
        all_reads = [x for b in r["batches"] for x in b["read_us"]]
        valid = (r["logical_bytes"] == row["buffer03_bytes"] == 8000 and all(x == 64 for x in r["packet_lengths"]))
        if baseline_hex is None and depth == 1:
            baseline_hex = r["data_hex"]
        # Different fresh acquisitions are not expected byte-identical; don't use equality as waveform validation.
        print(f"A5 ready={row['ready_state']} polls={row['ready_polls']}; buffer03={row['buffer03_bytes']} B")
        print(f"returned={r['returned_bytes']} logical={r['logical_bytes']} packets={r['packet_count']} valid={valid}")
        print(f"transfer={r['wall_transfer_us']/1000.0:.3f} ms batches={len(r['batches'])} "
              f"batch-med={statistics.median(batch_us):.1f} us p95={pct(batch_us, .95):.1f} us")
        print(f"per-command write-med={statistics.median(all_writes):.1f} us; "
              f"per-reply read-med={statistics.median(all_reads):.1f} us\n")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{stamp}_a6-pipeline-lab.json"
    payload = {
        "format": 1,
        "channel": cfg.channel,
        "range_a2": cfg.range_id,
        "a3": cfg.a3,
        "sample_rate": cfg.sample_rate,
        "depths": depths,
        "experiments": rows,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Detailed raw results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
