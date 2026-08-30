#!/usr/bin/env python3
"""Legacy diagnostic-only A3/AC probe around the 17/18 timing boundary.

IMPORTANT: this is *not* the official Trigger/Scan boundary probe.  Later
Windows evidence established the actual Trigger -> Scan transition at
A3=19 (200 ms/div) -> A3=1A (500 ms/div).  Use
``tools/probe_official_scan.py`` for the C9/CA Scan Mode experiment.

This older probe is retained only to investigate the separate A3=17/18 AC
configuration discontinuity:

    50 ms/div  -> A3 17, AC 00 00 00 00 01 07 B0 A1
    100 ms/div -> A3 18, AC 00 00 00 00 01 00 00 01

This tool asks a deliberately narrower question: which acquisition transport
works after programming those exact A3+AC pairs?

It tests triggered framing (A4 01 + A5/C6) and/or the independently validated ROLL
transport (A4 02 + C7/C8).  It records protocol-level evidence and raw bytes.
It does not add canonical sample-rate mappings, perform voltage conversion,
recognize waveforms, smooth, threshold, interpolate, integrate, or detrend.
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
    _query_buffer,
    _transact,
    decode_direct_u12,
    wait_ready_with_polls,
)


PROFILES = {
    "17": {
        "a3": 0x17,
        "time_div": "50ms/div",
        "ac": bytes.fromhex("AC 00 00 00 00 01 07 B0 A1"),
        "windows_ac_fields": [0, 1, 503969],
    },
    "18": {
        "a3": 0x18,
        "time_div": "100ms/div",
        "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01"),
        "windows_ac_fields": [0, 1, 1],
    },
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tx(scope, payload: bytes, timeout_ms: int) -> dict:
    t0 = time.perf_counter_ns()
    reply = _transact(scope, payload, timeout_ms)
    t1 = time.perf_counter_ns()
    return {
        "tx_hex": payload.hex(" ").upper(),
        "rx_hex": reply.hex(" ").upper(),
        "elapsed_ms": (t1 - t0) / 1_000_000.0,
    }


def program_profile(scope, profile: dict, timeout_ms: int) -> list[dict]:
    return [
        tx(scope, bytes([0xA3, profile["a3"]]), timeout_ms),
        tx(scope, profile["ac"], timeout_ms),
    ]


def triggered_probe(scope, timeout_ms: int, max_polls: int) -> dict:
    rows = []
    for payload in (
        b"\xF3",
        bytes.fromhex("E4 01"),
        bytes.fromhex("E6 01"),
        bytes.fromhex("A4 01"),
        b"\xC0",
        b"\xC2",
    ):
        rows.append(tx(scope, payload, timeout_ms))

    ready_metrics = {}
    try:
        state, polls = wait_ready_with_polls(
            scope, timeout_ms=timeout_ms, tries=max_polls, metrics=ready_metrics
        )
    except HantekUSBError as exc:
        return {
            "transport": "triggered-a4-01",
            "status": "a5-not-ready",
            "error": str(exc),
            "transactions": rows,
            "a5": ready_metrics,
        }

    b2 = _query_buffer(scope, 2, timeout_ms)
    b3 = _query_buffer(scope, 3, timeout_ms)
    combined = b2 + b3
    words = decode_direct_u12((b2, b3))
    rows.extend([
        tx(scope, bytes.fromhex("E4 01"), timeout_ms),
        tx(scope, bytes.fromhex("E6 01"), timeout_ms),
    ])
    return {
        "transport": "triggered-a4-01",
        "status": "ok",
        "ready_state": state,
        "ready_polls": polls,
        "a5": ready_metrics,
        "buffer02_bytes": len(b2),
        "buffer03_bytes": len(b3),
        "combined_bytes": len(combined),
        "combined_sha256": digest(combined),
        "u12_words": len(words),
        "u12_min": min(words) if words else None,
        "u12_max": max(words) if words else None,
        "u12_span": (max(words) - min(words)) if words else None,
        "transactions": rows,
        "raw": combined,
    }


def read_c8_packet(scope, timeout_ms: int) -> bytes:
    scope.write(b"\xC8", timeout_ms=timeout_ms)
    packet = scope.read(size=64, timeout_ms=timeout_ms)
    if len(packet) != 64:
        raise HantekUSBError(f"C8: expected 64-byte packet, got {len(packet)}")
    return packet


def roll_probe(scope, timeout_ms: int, capture_s: float, poll_ms: float) -> dict:
    rows = []
    for payload in (b"\xF3", bytes.fromhex("A4 02"), b"\xC0", b"\xC2"):
        rows.append(tx(scope, payload, timeout_ms))

    deadline = time.monotonic() + capture_s
    drained = bytearray()
    polls = []
    while time.monotonic() < deadline:
        rows.append(tx(scope, b"\xF3", timeout_ms))
        reply = _transact(scope, b"\xC7", timeout_ms)
        if len(reply) != 2:
            raise HantekUSBError(f"C7: expected 2 bytes, got {len(reply)}")
        available = int.from_bytes(reply, "big")
        polls.append({"available_bytes": available})
        if available:
            need = available
            chunk = bytearray()
            while len(chunk) < need:
                packet = read_c8_packet(scope, timeout_ms)
                chunk.extend(packet[: need - len(chunk)])
            drained.extend(chunk)
        else:
            time.sleep(poll_ms / 1000.0)

    return {
        "transport": "roll-a4-02-c7-c8",
        "status": "ok" if drained else "no-data",
        "drained_bytes": len(drained),
        "drained_sha256": digest(bytes(drained)) if drained else None,
        "c7_polls": polls,
        "transactions": rows,
        "raw": bytes(drained),
    }


def run_one(profile_name: str, transport: str, args, stamp: str) -> dict:
    profile = PROFILES[profile_name]
    # DirectADCSession initialization accepts arbitrary A3 values without using
    # DirectADCConfig.sample_rate.  We then overwrite A3+AC with the exact
    # official-Windows profile immediately before the transport test.
    cfg = DirectADCConfig(
        channel=1,
        a3=profile["a3"],
        range_id=args.range_id,
        timeout_ms=args.usb_timeout_ms,
    )

    with Hantek1008C() as scope:
        DirectADCSession(scope, cfg).initialize()
        programmed = program_profile(scope, profile, args.usb_timeout_ms)
        time.sleep(args.settle_ms / 1000.0)
        if transport == "triggered":
            result = triggered_probe(scope, args.usb_timeout_ms, args.max_polls)
        else:
            result = roll_probe(
                scope, args.usb_timeout_ms, args.roll_capture_s, args.poll_ms
            )
        result["device"] = scope.connection_id

    raw = result.pop("raw", b"")
    raw_path = None
    if raw:
        raw_path = args.output_dir / f"{stamp}_boundary-a3-{profile_name}_{transport}.bin"
        raw_path.write_bytes(raw)

    return {
        "profile": profile_name,
        "a3_hex": f"{profile['a3']:02X}",
        "official_time_div": profile["time_div"],
        "official_ac_hex": profile["ac"].hex(" ").upper(),
        "official_ac_fields_u16_u24_u24": profile["windows_ac_fields"],
        "transport_tested": transport,
        "program_transactions": programmed,
        "raw_file": str(raw_path) if raw_path else None,
        **result,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description="Legacy diagnostic A3=17/18 AC/timing-boundary probe (not Trigger/Scan)"
    )
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument(
        "--profiles", choices=("17", "18", "both"), default="both",
        help="official Windows A3/AC profile(s) to test (default: both)",
    )
    p.add_argument(
        "--transport", choices=("triggered", "roll", "both"), default="both",
        help="transport(s) to try, each in a fresh USB session (default: both)",
    )
    p.add_argument("--settle-ms", type=float, default=10.0)
    p.add_argument("--max-polls", type=int, default=2000)
    p.add_argument("--roll-capture-s", type=float, default=1.0)
    p.add_argument("--poll-ms", type=float, default=5.0)
    p.add_argument("--usb-timeout-ms", type=int, default=1000)
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    args = p.parse_args()

    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.settle_ms < 0 or args.max_polls < 1 or args.roll_capture_s <= 0 or args.poll_ms < 0:
        p.error("invalid timing argument")

    profiles = ["17", "18"] if args.profiles == "both" else [args.profiles]
    transports = ["triggered", "roll"] if args.transport == "both" else [args.transport]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("Legacy A3=17/18 AC/timing diagnostic; this is NOT the Trigger/Scan boundary.")
    print("For official A3=1A/1B C9/CA Scan Mode use tools/probe_official_scan.py.\n")

    results = []
    for profile in profiles:
        for transport in transports:
            print(f"=== A3={profile}, transport={transport} ===")
            try:
                row = run_one(profile, transport, args, stamp)
                print(
                    f"  status={row['status']} "
                    f"bytes={row.get('combined_bytes', row.get('drained_bytes', 0))}"
                )
            except Exception as exc:
                row = {
                    "profile": profile,
                    "transport_tested": transport,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                print(f"  ERROR: {row['error']}")
            results.append(row)
            print()

    out = args.output_dir / f"{stamp}_timebase-boundary.json"
    out.write_text(json.dumps({
        "format": "hantek1008c-timebase-boundary-v1",
        "timestamp_utc": stamp,
        "canonical_acquisition_modified": False,
        "range_a2": f"{args.range_id:02X}",
        "results": results,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
