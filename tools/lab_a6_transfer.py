#!/usr/bin/env python3
"""Diagnostic-only Hantek 1008C A6 transfer experiments.

Each experiment opens and fully initializes a fresh device session, arms one
normal direct-ADC acquisition with the canonical zero fixed arm delay, waits for
A5 readiness, and then probes buffer 03 using a selected A6 read strategy.

This tool intentionally does NOT modify the canonical acquisition implementation.
It preserves every byte returned by the device in JSON for protocol archaeology.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import usb.core

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import (
    DirectADCConfig,
    DirectADCSession,
    _query_buffer,
    _transact,
    wait_ready_with_polls,
)


def arm_ready(scope, timeout_ms: int):
    """Perform the canonical zero-delay arm/readiness sequence."""
    rows = []
    for name, payload in (
        ("f3", b"\xF3"),
        ("e4_pre", bytes.fromhex("E4 01")),
        ("e6_pre", bytes.fromhex("E6 01")),
        ("a4", bytes.fromhex("A4 01")),
        ("c0", b"\xC0"),
        ("c2", b"\xC2"),
    ):
        t0 = time.perf_counter_ns()
        _transact(scope, payload, timeout_ms)
        t1 = time.perf_counter_ns()
        rows.append({"phase": name, "elapsed_us": (t1 - t0) / 1000.0})
    m = {}
    state, polls = wait_ready_with_polls(scope, timeout_ms, metrics=m)
    return {"ready_state": state, "ready_polls": polls, "a5": m, "phases": rows}


def query_sizes(scope, timeout_ms: int):
    """Query/drain buffer 02, then return buffer-03 reported byte count."""
    b2m = {}
    b2 = _query_buffer(scope, 2, timeout_ms, metrics=b2m)
    reply = _transact(scope, bytes([0xC6, 3]), timeout_ms)
    if len(reply) != 2:
        raise HantekUSBError(f"C6 03: expected 2-byte size, got {len(reply)}")
    return b2, b2m, int.from_bytes(reply, "big")


def read_baseline(scope, size: int, timeout_ms: int):
    packets = []
    out = bytearray()
    for idx in range((size + 63) // 64):
        t0 = time.perf_counter_ns()
        scope.write(bytes([0xA6, 3]), timeout_ms=timeout_ms)
        t1 = time.perf_counter_ns()
        packet = scope.read(size=64, timeout_ms=timeout_ms)
        t2 = time.perf_counter_ns()
        packets.append({
            "packet": idx,
            "length": len(packet),
            "write_us": (t1 - t0) / 1000.0,
            "read_us": (t2 - t1) / 1000.0,
            "data_hex": packet.hex().upper(),
        })
        out.extend(packet)
    return {"returned_bytes": len(out), "logical_bytes": len(out[:size]), "packets": packets}


def read_large(scope, request_size: int, timeout_ms: int):
    t0 = time.perf_counter_ns()
    scope.write(bytes([0xA6, 3]), timeout_ms=timeout_ms)
    t1 = time.perf_counter_ns()
    try:
        data = scope.read(size=request_size, timeout_ms=timeout_ms)
        timed_out = False
        error = None
    except usb.core.USBTimeoutError as exc:
        data = b""
        timed_out = True
        error = str(exc)
    t2 = time.perf_counter_ns()
    return {
        "request_size": request_size,
        "returned_bytes": len(data),
        "timed_out": timed_out,
        "error": error,
        "write_us": (t1 - t0) / 1000.0,
        "read_us": (t2 - t1) / 1000.0,
        "data_hex": data.hex().upper(),
    }


def read_consecutive(scope, reads: int, timeout_ms: int, probe_timeout_ms: int):
    """Send one A6, then attempt repeated 64-byte reads without further A6."""
    result = []
    t0 = time.perf_counter_ns()
    scope.write(bytes([0xA6, 3]), timeout_ms=timeout_ms)
    t1 = time.perf_counter_ns()
    for idx in range(reads):
        r0 = time.perf_counter_ns()
        try:
            data = scope.read(size=64, timeout_ms=probe_timeout_ms)
            timed_out = False
            error = None
        except usb.core.USBTimeoutError as exc:
            data = b""
            timed_out = True
            error = str(exc)
        r1 = time.perf_counter_ns()
        result.append({
            "read": idx,
            "length": len(data),
            "timed_out": timed_out,
            "error": error,
            "read_us": (r1 - r0) / 1000.0,
            "data_hex": data.hex().upper(),
        })
        if timed_out:
            break
    return {"a6_write_us": (t1 - t0) / 1000.0, "reads": result}


def run_one(mode: str, cfg: DirectADCConfig, request_size: int, consecutive_reads: int, probe_timeout_ms: int):
    with Hantek1008C() as scope:
        device = scope.connection_id
        DirectADCSession(scope, cfg).initialize()
        readiness = arm_ready(scope, cfg.timeout_ms)
        b2, b2m, size03 = query_sizes(scope, cfg.timeout_ms)
        row = {
            "mode": mode,
            "device": device,
            "reported_buffer02_bytes": len(b2),
            "buffer02_metrics": b2m,
            "reported_buffer03_bytes": size03,
            "readiness": readiness,
        }
        if mode == "baseline":
            row["result"] = read_baseline(scope, size03, cfg.timeout_ms)
        elif mode == "large-read":
            row["result"] = read_large(scope, request_size, cfg.timeout_ms)
        elif mode == "consecutive-read":
            row["result"] = read_consecutive(scope, consecutive_reads, cfg.timeout_ms, probe_timeout_ms)
        else:
            raise ValueError(mode)
        return row


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnostic-only A6 USB transfer protocol lab")
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument("--a3", type=lambda s: int(s, 16), default=0x0F)
    p.add_argument("--modes", default="baseline,large-read,consecutive-read",
                   help="comma-separated: baseline,large-read,consecutive-read")
    p.add_argument("--request-size", type=int, default=512,
                   help="read size after one A6 in large-read mode")
    p.add_argument("--consecutive-reads", type=int, default=4,
                   help="maximum 64-byte reads after one A6")
    p.add_argument("--probe-timeout-ms", type=int, default=50,
                   help="short timeout for extra uncommanded reads")
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    args = p.parse_args()
    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.request_size < 64:
        p.error("--request-size must be >= 64")
    if args.consecutive_reads < 1:
        p.error("--consecutive-reads must be >= 1")

    allowed = {"baseline", "large-read", "consecutive-read"}
    modes = [x.strip() for x in args.modes.split(",") if x.strip()]
    bad = [x for x in modes if x not in allowed]
    if bad or not modes:
        p.error(f"--modes must use {','.join(sorted(allowed))}")

    cfg = DirectADCConfig(channel=args.channel, a3=args.a3, range_id=args.range_id)
    print(f"Target: CH{cfg.channel}, A2={cfg.range_id:02X}, A3={cfg.a3:02X}, {cfg.sample_rate/1e6:.3f} MS/s")
    print("Diagnostic A6 lab: each mode uses a fresh USB/device initialization.")
    print("Canonical acquisition is not modified by these probe strategies.\n")

    rows = []
    for mode in modes:
        print(f"=== {mode} ===")
        try:
            row = run_one(mode, cfg, args.request_size, args.consecutive_reads, args.probe_timeout_ms)
        except Exception as exc:
            row = {"mode": mode, "error": f"{type(exc).__name__}: {exc}"}
            print(f"FAIL: {row['error']}")
            rows.append(row)
            continue
        rows.append(row)
        print(f"A5 ready={row['readiness']['ready_state']} polls={row['readiness']['ready_polls']}; "
              f"buffer03={row['reported_buffer03_bytes']} bytes")
        r = row["result"]
        if mode == "baseline":
            print(f"125-command baseline: returned={r['returned_bytes']} logical={r['logical_bytes']} bytes")
        elif mode == "large-read":
            print(f"one A6, read({r['request_size']}): returned={r['returned_bytes']} bytes "
                  f"timeout={r['timed_out']} read={r['read_us']:.1f} us")
        else:
            for rr in r["reads"]:
                print(f"read {rr['read'] + 1}: bytes={rr['length']} timeout={rr['timed_out']} "
                      f"elapsed={rr['read_us']:.1f} us")
        print()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{stamp}_a6-transfer-lab.json"
    payload = {
        "format": 1,
        "channel": cfg.channel,
        "range_a2": cfg.range_id,
        "a3": cfg.a3,
        "sample_rate": cfg.sample_rate,
        "request_size": args.request_size,
        "consecutive_reads": args.consecutive_reads,
        "probe_timeout_ms": args.probe_timeout_ms,
        "experiments": rows,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Detailed raw results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
