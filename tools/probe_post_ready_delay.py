#!/usr/bin/env python3
"""Diagnostic-only test of post-A5-ready delay for selected Hantek A3 modes.

This lab asks a narrow protocol question: for an acquisition where A5 has
already reported state 2/3, does deliberately waiting before C6/A6 change the
returned 4000-word record?

No sample rate is assigned to the tested A3 values.  No waveform recognition,
thresholding, smoothing, reconstruction, or expected-waveform cleanup is used.
Every delay point is a fresh normal acquisition; raw bytes are preserved.
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
    out: list[int] = []
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
        out.append(value)
    if not out:
        raise argparse.ArgumentTypeError("A3 list is empty")
    return out


def parse_delays(text: str) -> list[float]:
    out: list[float] = []
    for field in text.split(","):
        field = field.strip()
        if not field:
            continue
        try:
            value = float(field)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid delay milliseconds: {field}") from exc
        if value < 0:
            raise argparse.ArgumentTypeError("delays must be >= 0 ms")
        out.append(value)
    if not out:
        raise argparse.ArgumentTypeError("delay list is empty")
    return out


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


def wait_ready(scope, timeout_ms: int, max_polls: int) -> dict:
    rows: list[dict] = []
    started = time.perf_counter_ns()
    for poll in range(1, max_polls + 1):
        t0 = time.perf_counter_ns()
        reply = _transact(scope, bytes.fromhex("A5 5A"), timeout_ms)
        t1 = time.perf_counter_ns()
        state = reply[-1] if reply else None
        row = {
            "poll": poll,
            "state": state,
            "transaction_ms": (t1 - t0) / 1_000_000.0,
        }
        rows.append(row)
        if state in (2, 3):
            return {
                "ready": True,
                "ready_state": int(state),
                "poll_count": poll,
                "elapsed_ms": (t1 - started) / 1_000_000.0,
                "polls": rows,
            }
        s0 = time.perf_counter_ns()
        time.sleep(0.002)
        s1 = time.perf_counter_ns()
        row["sleep_ms"] = (s1 - s0) / 1_000_000.0
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
    return {"phases": phases, **wait_ready(scope, timeout_ms, max_polls)}


def finish(scope, timeout_ms: int) -> list[dict]:
    rows = []
    for name, payload in (("e4_post", bytes.fromhex("E4 01")), ("e6_post", bytes.fromhex("E6 01"))):
        reply, elapsed_us = transact_timed(scope, payload, timeout_ms)
        rows.append({"phase": name, "elapsed_us": elapsed_us, "reply_hex": reply.hex().upper()})
    return rows


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def common_prefix_bytes(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def run_mode(a3: int, args, stamp: str) -> dict:
    cfg = DirectADCConfig(channel=args.channel, a3=a3, range_id=args.range_id, timeout_ms=args.usb_timeout_ms)
    result = {
        "a3": f"{a3:02X}",
        "sample_rate_hz": None,
        "sample_rate_status": "unvalidated-by-design",
        "delay_points": [],
    }

    with Hantek1008C() as scope:
        result["device"] = scope.connection_id
        DirectADCSession(scope, cfg).initialize()

        zero_delay_capture: bytes | None = None
        previous_capture: bytes | None = None

        for delay_ms in args.delays_ms:
            ready = arm(scope, cfg.timeout_ms, args.max_polls)
            row = {"post_ready_delay_ms_requested": delay_ms, "readiness": ready}
            if not ready["ready"]:
                row["status"] = "a5-not-ready"
                result["delay_points"].append(row)
                print(
                    f"  delay {delay_ms:6.1f} ms: A5 NOT READY after {ready['poll_count']} polls "
                    f"({ready['elapsed_ms']:.2f} ms)"
                )
                continue

            s0 = time.perf_counter_ns()
            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
            s1 = time.perf_counter_ns()
            actual_delay_ms = (s1 - s0) / 1_000_000.0

            c602 = query_c6(scope, 2, cfg.timeout_ms)
            c603 = query_c6(scope, 3, cfg.timeout_ms)
            m2, m3 = {}, {}
            b2 = _read_buffer(scope, 2, c602["reported_bytes"], cfg.timeout_ms, metrics=m2)
            b3 = _read_buffer(scope, 3, c603["reported_bytes"], cfg.timeout_ms, metrics=m3)
            cleanup = finish(scope, cfg.timeout_ms)
            combined = b2 + b3

            delay_tag = (f"{delay_ms:g}").replace(".", "p")
            prefix = f"{stamp}_post-ready-a3-{a3:02X}_delay-{delay_tag}ms"
            p2 = args.output_dir / f"{prefix}_buffer02.bin"
            p3 = args.output_dir / f"{prefix}_buffer03.bin"
            pc = args.output_dir / f"{prefix}_combined.bin"
            p2.write_bytes(b2)
            p3.write_bytes(b3)
            pc.write_bytes(combined)

            if zero_delay_capture is None and delay_ms == 0:
                zero_delay_capture = combined

            row.update({
                "status": "ok",
                "post_ready_delay_ms_actual": actual_delay_ms,
                "c6_02": c602,
                "c6_03": c603,
                "buffer02_bytes": len(b2),
                "buffer03_bytes": len(b3),
                "combined_bytes": len(combined),
                "combined_u16_words": len(combined) // 2,
                "combined_sha256": sha256(combined),
                "combined_equals_previous_exactly": (combined == previous_capture) if previous_capture is not None else None,
                "combined_equals_zero_delay_exactly": (combined == zero_delay_capture) if zero_delay_capture is not None else None,
                "common_prefix_bytes_with_zero_delay": common_prefix_bytes(zero_delay_capture, combined) if zero_delay_capture is not None else None,
                "buffer02_metrics": m2,
                "buffer03_metrics": m3,
                "cleanup": cleanup,
                "files": {"buffer02": str(p2), "buffer03": str(p3), "combined": str(pc)},
            })
            previous_capture = combined
            result["delay_points"].append(row)

            print(
                f"  delay {delay_ms:6.1f} ms (actual {actual_delay_ms:6.2f}): "
                f"A5={ready['ready_state']}/{ready['poll_count']} ({ready['elapsed_ms']:.2f} ms) "
                f"C6[02]={c602['reported_bytes']:5d} B C6[03]={c603['reported_bytes']:5d} B "
                f"total={len(combined):5d} B/{len(combined)//2:4d} words"
            )

    oks = [r for r in result["delay_points"] if r.get("status") == "ok"]
    result["summary"] = {
        "successful_delay_points": len(oks),
        "c6_size_pairs": [(r["buffer02_bytes"], r["buffer03_bytes"]) for r in oks],
        "unique_combined_hashes": len({r["combined_sha256"] for r in oks}),
        "ready_elapsed_ms": [r["readiness"]["elapsed_ms"] for r in oks],
        "actual_post_ready_delay_ms": [r["post_ready_delay_ms_actual"] for r in oks],
    }
    return result


def main() -> int:
    p = argparse.ArgumentParser(description="Test post-A5-ready delays for selected unvalidated Hantek A3 modes")
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument("--a3-list", type=parse_a3_list, default=parse_a3_list("12,13"), help="comma-separated A3 bytes (default: 12,13)")
    p.add_argument("--delays-ms", type=parse_delays, default=parse_delays("0,5,10,20,40"), help="comma-separated delay after A5 ready, ms (default: 0,5,10,20,40)")
    p.add_argument("--max-polls", type=int, default=2000)
    p.add_argument("--usb-timeout-ms", type=int, default=1000)
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    args = p.parse_args()

    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.max_polls < 1:
        p.error("--max-polls must be >= 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"CH{args.channel}, A2={args.range_id:02X}; post-A5-ready delay diagnostic only.")
    print("No sample-rate/timebase values are assumed or promoted into canonical code.")
    print("Each delay point is a fresh normal acquisition; raw bytes are preserved.\n")

    experiments = []
    for a3 in args.a3_list:
        delays = ", ".join(f"{x:g}" for x in args.delays_ms)
        print(f"=== A3={a3:02X}; post-ready delays [{delays}] ms ===")
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

    out = args.output_dir / f"{stamp}_post-ready-delay.json"
    payload = {
        "format": "hantek1008c-post-ready-delay-v1",
        "timestamp_utc": stamp,
        "channel": args.channel,
        "range_a2": f"{args.range_id:02X}",
        "a3_values": [f"{x:02X}" for x in args.a3_list],
        "post_ready_delays_ms": args.delays_ms,
        "sample_rates": "intentionally-unassigned",
        "canonical_acquisition_modified": False,
        "waveform_specific_processing": False,
        "experiments": experiments,
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Detailed results: {out}")
    print(f"Raw captures    : {args.output_dir}/{stamp}_post-ready-a3-*_delay-*ms_*.bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
