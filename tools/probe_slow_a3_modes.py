#!/usr/bin/env python3
"""Diagnostic-only probe of unvalidated slower/adjacent A3 modes.

The canonical direct-ADC path intentionally exposes sample rates only for A3
values already validated on hardware.  This lab deliberately does *not* add
sample-rate mappings.  Instead it tries selected adjacent A3 bytes in fresh USB
sessions and records only protocol-level observations: A5 readiness, C6 02/03
sizes, exact drained bytes, hashes, and raw files.

There is no waveform recognition, thresholding, smoothing, reconstruction, or
assumed sample-rate/timebase conversion in this tool.
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
from hantek1008c.acquire import DirectADCConfig, DirectADCSession, _read_buffer, _transact


def transact_timed(scope, payload: bytes, timeout_ms: int) -> tuple[bytes, float]:
    t0 = time.perf_counter_ns()
    reply = _transact(scope, payload, timeout_ms)
    t1 = time.perf_counter_ns()
    return reply, (t1 - t0) / 1000.0


def parse_a3_list(text: str) -> list[int]:
    values: list[int] = []
    for field in text.split(","):
        field = field.strip()
        if not field:
            continue
        try:
            value = int(field, 16)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid A3 byte: {field}") from exc
        if not 0 <= value <= 0xFF:
            raise argparse.ArgumentTypeError(f"A3 out of range: {field}")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("A3 list is empty")
    return values


def query_c6(scope, selector: int, timeout_ms: int) -> dict:
    reply, elapsed_us = transact_timed(scope, bytes([0xC6, selector]), timeout_ms)
    if len(reply) != 2:
        raise HantekUSBError(f"C6 {selector:02X}: expected 2 bytes, got {len(reply)}")
    return {
        "selector": selector,
        "reply_hex": reply.hex().upper(),
        "reported_bytes": int.from_bytes(reply, "big"),
        "elapsed_us": elapsed_us,
    }


def wait_ready_extended(scope, timeout_ms: int, max_polls: int) -> dict:
    rows: list[dict] = []
    started = time.perf_counter_ns()
    for poll in range(1, max_polls + 1):
        t0 = time.perf_counter_ns()
        reply = _transact(scope, bytes.fromhex("A5 5A"), timeout_ms)
        t1 = time.perf_counter_ns()
        state = reply[-1] if reply else None
        rows.append({
            "poll": poll,
            "state": state,
            "transaction_ms": (t1 - t0) / 1_000_000.0,
        })
        if state in (2, 3):
            return {
                "ready": True,
                "ready_state": int(state),
                "poll_count": poll,
                "elapsed_ms": (t1 - started) / 1_000_000.0,
                "polls": rows,
            }
        sleep0 = time.perf_counter_ns()
        time.sleep(0.002)
        sleep1 = time.perf_counter_ns()
        rows[-1]["sleep_ms"] = (sleep1 - sleep0) / 1_000_000.0
    return {
        "ready": False,
        "ready_state": None,
        "poll_count": max_polls,
        "elapsed_ms": (time.perf_counter_ns() - started) / 1_000_000.0,
        "polls": rows,
    }


def arm(scope, timeout_ms: int, max_polls: int) -> dict:
    phases = []
    for name, payload in (
        ("f3", b"\xF3"),
        ("e4_pre", bytes.fromhex("E4 01")),
        ("e6_pre", bytes.fromhex("E6 01")),
        ("a4", bytes.fromhex("A4 01")),
        ("c0", b"\xC0"),
        ("c2", b"\xC2"),
    ):
        reply, elapsed_us = transact_timed(scope, payload, timeout_ms)
        phases.append({"phase": name, "elapsed_us": elapsed_us, "reply_hex": reply.hex().upper()})
    ready = wait_ready_extended(scope, timeout_ms, max_polls)
    return {"phases": phases, **ready}


def finish(scope, timeout_ms: int) -> list[dict]:
    rows = []
    for name, payload in (("e4_post", bytes.fromhex("E4 01")), ("e6_post", bytes.fromhex("E6 01"))):
        reply, elapsed_us = transact_timed(scope, payload, timeout_ms)
        rows.append({"phase": name, "elapsed_us": elapsed_us, "reply_hex": reply.hex().upper()})
    return rows


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_mode(a3: int, args, stamp: str) -> dict:
    cfg = DirectADCConfig(
        channel=args.channel,
        a3=a3,
        range_id=args.range_id,
        timeout_ms=args.usb_timeout_ms,
    )
    result = {
        "a3": f"{a3:02X}",
        "sample_rate_hz": None,
        "sample_rate_status": "unvalidated-by-design",
        "bursts": [],
    }

    with Hantek1008C() as scope:
        result["device"] = scope.connection_id
        # DirectADCSession.initialize() can program arbitrary A3 bytes; it does
        # not require DirectADCConfig.sample_rate.  No canonical mapping changes.
        DirectADCSession(scope, cfg).initialize()

        previous: bytes | None = None
        for n in range(1, args.bursts + 1):
            readiness = arm(scope, cfg.timeout_ms, args.max_polls)
            burst = {"index": n, "readiness": readiness}
            if not readiness["ready"]:
                burst["status"] = "a5-not-ready"
                result["bursts"].append(burst)
                print(
                    f"  burst {n:02d}: A5 NOT READY after {readiness['poll_count']} polls "
                    f"({readiness['elapsed_ms']:.1f} ms)"
                )
                break

            c602 = query_c6(scope, 2, cfg.timeout_ms)
            c603 = query_c6(scope, 3, cfg.timeout_ms)
            m2, m3 = {}, {}
            b2 = _read_buffer(scope, 2, c602["reported_bytes"], cfg.timeout_ms, metrics=m2)
            b3 = _read_buffer(scope, 3, c603["reported_bytes"], cfg.timeout_ms, metrics=m3)
            cleanup = finish(scope, cfg.timeout_ms)
            combined = b2 + b3

            prefix = f"{stamp}_slow-a3-{a3:02X}_burst-{n:02d}"
            p2 = args.output_dir / f"{prefix}_buffer02.bin"
            p3 = args.output_dir / f"{prefix}_buffer03.bin"
            pc = args.output_dir / f"{prefix}_combined.bin"
            p2.write_bytes(b2)
            p3.write_bytes(b3)
            pc.write_bytes(combined)

            burst.update({
                "status": "ok",
                "c6_02": c602,
                "c6_03": c603,
                "buffer02_bytes": len(b2),
                "buffer03_bytes": len(b3),
                "combined_bytes": len(combined),
                "combined_u16_words": len(combined) // 2,
                "buffer02_sha256": digest(b2),
                "buffer03_sha256": digest(b3),
                "combined_sha256": digest(combined),
                "combined_equals_previous_exactly": (combined == previous) if previous is not None else None,
                "buffer02_metrics": m2,
                "buffer03_metrics": m3,
                "cleanup": cleanup,
                "files": {"buffer02": str(p2), "buffer03": str(p3), "combined": str(pc)},
            })
            previous = combined
            result["bursts"].append(burst)
            print(
                f"  burst {n:02d}: A5={readiness['ready_state']}/{readiness['poll_count']} "
                f"({readiness['elapsed_ms']:.2f} ms) "
                f"C6[02]={c602['reported_bytes']:5d} B C6[03]={c603['reported_bytes']:5d} B "
                f"total={len(combined):5d} B/{len(combined)//2:4d} words "
                f"same-prev={burst['combined_equals_previous_exactly']}"
            )

    oks = [b for b in result["bursts"] if b.get("status") == "ok"]
    result["summary"] = {
        "successful_bursts": len(oks),
        "c6_size_pairs": [(b["buffer02_bytes"], b["buffer03_bytes"]) for b in oks],
        "any_buffer02_nonzero": any(b["buffer02_bytes"] for b in oks),
        "unique_combined_hashes": len({b["combined_sha256"] for b in oks}),
        "ready_elapsed_ms": [b["readiness"]["elapsed_ms"] for b in oks],
    }
    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Probe adjacent slower/unvalidated Hantek A3 modes safely")
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument(
        "--a3-list",
        type=parse_a3_list,
        default=parse_a3_list("12,13,14,15"),
        help="comma-separated unvalidated A3 bytes (default: 12,13,14,15)",
    )
    p.add_argument("--bursts", type=int, default=3, help="normal acquisitions per A3 value (default: 3)")
    p.add_argument("--max-polls", type=int, default=2000, help="A5 poll ceiling per burst (default: 2000)")
    p.add_argument("--usb-timeout-ms", type=int, default=1000)
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    args = p.parse_args()

    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.bursts < 1:
        p.error("--bursts must be >= 1")
    if args.max_polls < 1:
        p.error("--max-polls must be >= 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"CH{args.channel}, A2={args.range_id:02X}; unvalidated-A3 diagnostic only.")
    print("No sample-rate/timebase values are assumed or promoted into canonical code.")
    print("Each A3 value gets a fresh full initialization; failures are isolated per mode.\n")

    experiments = []
    for a3 in args.a3_list:
        print(f"=== A3={a3:02X} (sample rate intentionally unknown), {args.bursts} burst(s) ===")
        try:
            row = run_mode(a3, args, stamp)
        except Exception as exc:
            row = {
                "a3": f"{a3:02X}",
                "sample_rate_hz": None,
                "sample_rate_status": "unvalidated-by-design",
                "error": f"{type(exc).__name__}: {exc}",
            }
            print(f"  FAIL: {row['error']}")
        experiments.append(row)
        print()

    out = args.output_dir / f"{stamp}_slow-a3-modes.json"
    payload = {
        "format": "hantek1008c-slow-a3-modes-v1",
        "timestamp_utc": stamp,
        "channel": args.channel,
        "range_a2": f"{args.range_id:02X}",
        "a3_values": [f"{x:02X}" for x in args.a3_list],
        "sample_rates": "intentionally-unassigned",
        "canonical_acquisition_modified": False,
        "experiments": experiments,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Detailed results: {out}")
    print(f"Raw burst files : {args.output_dir}/{stamp}_slow-a3-*_burst-*_*.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
