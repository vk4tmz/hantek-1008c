#!/usr/bin/env python3
"""Probe Hantek 1008C A2 gain states in one initialized direct-ADC session.

This is a protocol-lab diagnostic, not part of the canonical reconstruction path.
It deliberately keeps channel, A3/sample rate, USB session, and signal source fixed
while switching only A2.  The default forward/reverse sequence is:

    01 -> 02 -> 03 -> 03 -> 02 -> 01

For each step it records unmodified 12-bit ADC words and simple raw statistics.
No voltage conversion, smoothing, detrending, thresholding, or waveform-specific
processing is performed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession

VALID_RANGES = (0x01, 0x02, 0x03)
DEFAULT_SEQUENCE = (0x01, 0x02, 0x03, 0x03, 0x02, 0x01)


def parse_byte(value: str) -> int:
    result = int(value, 16)
    if not 0 <= result <= 0xFF:
        raise argparse.ArgumentTypeError("hex byte must be 00..FF")
    return result


def transact(scope, payload: bytes, timeout_ms: int) -> bytes:
    tx = scope.transact(payload, read_timeout_ms=timeout_ms)
    if tx.timed_out:
        raise HantekUSBError(f"{payload.hex(' ').upper()}: timeout")
    return tx.rx or b""


def set_a2(scope, range_id: int, timeout_ms: int, settle_ms: float) -> None:
    """Select one A2 gain state for all channels, matching reference sequencing."""
    transact(scope, b"\xF3", timeout_ms)
    transact(scope, bytes([0xA2] + [range_id] * 8), timeout_ms)
    if settle_ms > 0:
        time.sleep(settle_ms / 1000.0)


def raw_summary(words: list[int]) -> dict:
    if not words:
        return {"min": None, "max": None, "mean": None, "span": None, "count": 0}
    mn = min(words)
    mx = max(words)
    return {
        "min": mn,
        "max": mx,
        "mean": sum(words) / len(words),
        "span": mx - mn,
        "count": len(words),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--a3", type=parse_byte, default=0x11)
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--settle-ms", type=float, default=20.0,
                   help="delay after A2 selection before arming (default: 20 ms)")
    p.add_argument("--sequence", nargs="+", type=parse_byte,
                   default=list(DEFAULT_SEQUENCE),
                   help="A2 sequence in hex (default: 01 02 03 03 02 01)")
    p.add_argument("--tag", default="a2-gain-sequence")
    args = p.parse_args()

    bad = [v for v in args.sequence if v not in VALID_RANGES]
    if bad:
        p.error("validated A2 ranges are only 01, 02, and 03")

    # Initialize once.  The first requested A2 is used only as the initial final
    # configuration; each measured step explicitly re-selects its own A2.
    cfg = DirectADCConfig(
        channel=args.channel,
        a3=args.a3,
        range_id=args.sequence[0],
        timeout_ms=args.timeout_ms,
    )

    out = Path("captures")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{args.tag}"
    txlog = out / f"{base}_transactions.jsonl"
    json_path = out / f"{base}.json"

    rows = []
    try:
        with Hantek1008C(logger_path=txlog) as scope:
            session = DirectADCSession(scope, cfg)
            startup_calibration = session.initialize()

            for index, range_id in enumerate(args.sequence, start=1):
                set_a2(scope, range_id, args.timeout_ms, args.settle_ms)
                words = session.acquire_words()
                summary = raw_summary(words)
                raw_path = out / f"{base}_step{index:02d}_a2-{range_id:02X}.bin"
                raw_path.write_bytes(
                    b"".join((v & 0x0FFF).to_bytes(2, "little") for v in words)
                )
                row = {
                    "step": index,
                    "range_hex": f"{range_id:02X}",
                    "raw_summary": summary,
                    "raw_file": str(raw_path),
                }
                rows.append(row)
                print(
                    f"step={index} A2={range_id:02X} "
                    f"min={summary['min']} max={summary['max']} "
                    f"mean={summary['mean']:.3f} span={summary['span']} "
                    f"n={summary['count']}"
                )
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    payload = {
        "timestamp_utc": stamp,
        "tag": args.tag,
        "mode": "diagnostic-a2-gain-sequence",
        "channel": args.channel,
        "a3_hex": f"{args.a3:02X}",
        "sample_rate": cfg.sample_rate,
        "settle_ms": args.settle_ms,
        "sequence_hex": [f"{v:02X}" for v in args.sequence],
        "startup_calibration": startup_calibration,
        "steps": rows,
        "transaction_log": str(txlog),
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n")

    by_range = {rid: [] for rid in VALID_RANGES}
    for row in rows:
        by_range[int(row["range_hex"], 16)].append(row["raw_summary"]["span"])

    print("\nRepeatability by A2 (raw spans):")
    for rid in VALID_RANGES:
        vals = by_range[rid]
        if vals:
            print(f"  A2={rid:02X}: " + ", ".join(str(v) for v in vals))

    print(f"\nSaved: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
