#!/usr/bin/env python3
"""Diagnostic-only Hantek 1008C acquisition/readout overlap probes.

Each experiment opens and fully initializes a fresh device session.  The
canonical acquisition implementation is not modified.  The lab deliberately
leaves all or part of buffer 03 unread, starts a second acquisition, and records
what the device reports before and after the re-arm.

No waveform reconstruction, smoothing, thresholding, or expected-shape test is
performed.  Every byte explicitly read from buffer 03 is preserved in JSON.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import (
    DirectADCConfig,
    DirectADCSession,
    _transact,
    wait_ready_with_polls,
)


def timed_tx(scope, payload: bytes, timeout_ms: int):
    t0 = time.perf_counter_ns()
    reply = _transact(scope, payload, timeout_ms)
    t1 = time.perf_counter_ns()
    return reply, (t1 - t0) / 1000.0


def arm_and_wait(scope, timeout_ms: int):
    """Use the validated zero-fixed-delay direct-ADC arm sequence."""
    phases = []
    for name, payload in (
        ("f3", b"\xF3"),
        ("e4_pre", bytes.fromhex("E4 01")),
        ("e6_pre", bytes.fromhex("E6 01")),
        ("a4", bytes.fromhex("A4 01")),
        ("c0", b"\xC0"),
        ("c2", b"\xC2"),
    ):
        reply, us = timed_tx(scope, payload, timeout_ms)
        phases.append({"phase": name, "elapsed_us": us, "reply_hex": reply.hex().upper()})
    a5m = {}
    state, polls = wait_ready_with_polls(scope, timeout_ms, metrics=a5m)
    return {"ready_state": state, "ready_polls": polls, "a5": a5m, "phases": phases}


def query_size(scope, selector: int, timeout_ms: int):
    reply, elapsed_us = timed_tx(scope, bytes([0xC6, selector]), timeout_ms)
    if len(reply) != 2:
        raise HantekUSBError(f"C6 {selector:02X}: expected 2-byte size, got {len(reply)}")
    return int.from_bytes(reply, "big"), {"elapsed_us": elapsed_us, "reply_hex": reply.hex().upper()}


def read_packets(scope, selector: int, count: int, timeout_ms: int):
    rows = []
    data = bytearray()
    for idx in range(count):
        w0 = time.perf_counter_ns()
        scope.write(bytes([0xA6, selector]), timeout_ms=timeout_ms)
        w1 = time.perf_counter_ns()
        packet = scope.read(size=64, timeout_ms=timeout_ms)
        r1 = time.perf_counter_ns()
        rows.append({
            "packet": idx,
            "length": len(packet),
            "write_us": (w1 - w0) / 1000.0,
            "read_us": (r1 - w1) / 1000.0,
            "total_us": (r1 - w0) / 1000.0,
            "data_hex": packet.hex().upper(),
        })
        data.extend(packet)
    return bytes(data), rows


def drain_reported(scope, selector: int, size: int, timeout_ms: int):
    count = (size + 63) // 64
    data, rows = read_packets(scope, selector, count, timeout_ms)
    return data[:size], rows


def finish(scope, timeout_ms: int):
    phases = []
    for name, payload in (("e4_post", bytes.fromhex("E4 01")), ("e6_post", bytes.fromhex("E6 01"))):
        reply, us = timed_tx(scope, payload, timeout_ms)
        phases.append({"phase": name, "elapsed_us": us, "reply_hex": reply.hex().upper()})
    return phases


def run_one(mode: str, cfg: DirectADCConfig, partial_packets: int):
    with Hantek1008C() as scope:
        device = scope.connection_id
        DirectADCSession(scope, cfg).initialize()

        first = arm_and_wait(scope, cfg.timeout_ms)
        size02_first, c6_02_first = query_size(scope, 2, cfg.timeout_ms)
        if size02_first:
            b2_first, b2_rows = drain_reported(scope, 2, size02_first, cfg.timeout_ms)
        else:
            b2_first, b2_rows = b"", []
        size03_first, c6_03_first = query_size(scope, 3, cfg.timeout_ms)

        pre_data = b""
        pre_rows = []
        if mode == "partial-rearm":
            count = min(partial_packets, (size03_first + 63) // 64)
            pre_data, pre_rows = read_packets(scope, 3, count, cfg.timeout_ms)
        elif mode != "unread-rearm":
            raise ValueError(mode)

        # Querying size again is intentionally omitted here: it would add a
        # protocol operation between the partial read and the re-arm.  The lab
        # wants the smallest possible perturbation of the state under test.
        second = arm_and_wait(scope, cfg.timeout_ms)

        size02_second, c6_02_second = query_size(scope, 2, cfg.timeout_ms)
        if size02_second:
            b2_second, b2_second_rows = drain_reported(scope, 2, size02_second, cfg.timeout_ms)
        else:
            b2_second, b2_second_rows = b"", []
        size03_second, c6_03_second = query_size(scope, 3, cfg.timeout_ms)
        second_data, second_rows = drain_reported(scope, 3, size03_second, cfg.timeout_ms)
        cleanup = finish(scope, cfg.timeout_ms)

        return {
            "mode": mode,
            "device": device,
            "first": {
                "readiness": first,
                "buffer02_reported_bytes": size02_first,
                "buffer02_c6": c6_02_first,
                "buffer02_data_hex": b2_first.hex().upper(),
                "buffer02_packets": b2_rows,
                "buffer03_reported_bytes": size03_first,
                "buffer03_c6": c6_03_first,
                "buffer03_pre_rearm_bytes": len(pre_data),
                "buffer03_pre_rearm_data_hex": pre_data.hex().upper(),
                "buffer03_pre_rearm_packets": pre_rows,
                "buffer03_unread_bytes_estimate": max(0, size03_first - len(pre_data)),
            },
            "second": {
                "readiness": second,
                "buffer02_reported_bytes": size02_second,
                "buffer02_c6": c6_02_second,
                "buffer02_data_hex": b2_second.hex().upper(),
                "buffer02_packets": b2_second_rows,
                "buffer03_reported_bytes": size03_second,
                "buffer03_c6": c6_03_second,
                "buffer03_returned_bytes": len(second_data),
                "buffer03_data_hex": second_data.hex().upper(),
                "buffer03_packets": second_rows,
            },
            "cleanup": cleanup,
        }


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnostic-only Hantek acquisition/readout overlap lab")
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument("--a3", type=lambda s: int(s, 16), default=0x0F)
    p.add_argument("--modes", default="unread-rearm,partial-rearm",
                   help="comma-separated: unread-rearm,partial-rearm")
    p.add_argument("--partial-packets", type=int, default=4,
                   help="A6 packets drained before the second arm in partial-rearm mode")
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    args = p.parse_args()

    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.partial_packets < 1:
        p.error("--partial-packets must be >= 1")
    allowed = {"unread-rearm", "partial-rearm"}
    modes = [x.strip() for x in args.modes.split(",") if x.strip()]
    if not modes or any(x not in allowed for x in modes):
        p.error("--modes must use unread-rearm,partial-rearm")

    cfg = DirectADCConfig(channel=args.channel, a3=args.a3, range_id=args.range_id)
    print(f"Target: CH{cfg.channel}, A2={cfg.range_id:02X}, A3={cfg.a3:02X}, {cfg.sample_rate/1e6:.3f} MS/s")
    print("Diagnostic overlap lab: each mode uses a fresh USB/device initialization.")
    print("The first buffer is intentionally left unread or partly unread before re-arming.")
    print("Canonical acquisition is not modified.\n")

    rows = []
    for mode in modes:
        print(f"=== {mode} ===")
        try:
            row = run_one(mode, cfg, args.partial_packets)
        except Exception as exc:
            row = {"mode": mode, "error": f"{type(exc).__name__}: {exc}"}
            rows.append(row)
            print(f"FAIL: {row['error']}\n")
            continue
        rows.append(row)
        f = row["first"]
        s = row["second"]
        print(
            f"burst 1: A5={f['readiness']['ready_state']}/{f['readiness']['ready_polls']} polls "
            f"buffer03={f['buffer03_reported_bytes']} B pre-read={f['buffer03_pre_rearm_bytes']} B "
            f"unread~={f['buffer03_unread_bytes_estimate']} B"
        )
        print(
            f"burst 2: A5={s['readiness']['ready_state']}/{s['readiness']['ready_polls']} polls "
            f"buffer03={s['buffer03_reported_bytes']} B returned={s['buffer03_returned_bytes']} B"
        )
        print()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{stamp}_overlap-lab.json"
    payload = {
        "format": 1,
        "channel": cfg.channel,
        "range_a2": cfg.range_id,
        "a3": cfg.a3,
        "sample_rate": cfg.sample_rate,
        "partial_packets": args.partial_packets,
        "experiments": rows,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Detailed raw results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
