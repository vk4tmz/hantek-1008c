#!/usr/bin/env python3
"""Diagnostic-only raw ADC capture for the Hantek 1008C ROLL path.

This intentionally does not modify or reuse the canonical burst acquisition
function.  It follows the already validated ROLL transport sequence:

    A3 <rate-id>, settle, F3, A4 02, C0, C2
    F3, C7 -> available byte count
    C8 -> 64-byte packets

For the validated CH1-only ROLL layout each row is four bytes: one little-endian
12-bit CH1 ADC word followed by one extra device word.  The extra lane is
preserved in the raw transport file and reported separately; it is not treated
as waveform data.

No smoothing, interpolation, thresholding, detrending, waveform recognition, or
voltage conversion is performed.
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
from hantek1008c.acquire import DirectADCConfig, DirectADCSession, _transact


# Validated ROLL mappings live here deliberately rather than in the canonical
# DirectADCConfig burst-rate table.
ROLL_SAMPLE_RATES = {
    0x22: 1.0,
    0x21: 2.0,
    0x20: 5.0,
    0x1F: 9.0,
    0x1E: 23.0,
    0x1D: 50.0,
    0x1C: 100.0,
    0x1B: 201.0,
    0x1A: 401.0,
    0x19: 1003.0,
    0x18: 2006.0,
}


def parse_byte(value: str) -> int:
    result = int(value, 16)
    if not 0 <= result <= 0xFF:
        raise argparse.ArgumentTypeError("hex byte must be 00..FF")
    return result


def summary(values: list[int]) -> dict:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": (sum(values) / len(values)) if values else None,
        "span": (max(values) - min(values)) if values else None,
    }


def read_c8_bytes(scope, byte_count: int, timeout_ms: int) -> bytes:
    """Drain exactly ``byte_count`` logical bytes via 64-byte C8 packets."""
    out = bytearray()
    while len(out) < byte_count:
        scope.write(b"\xC8", timeout_ms=timeout_ms)
        packet = scope.read(size=64, timeout_ms=timeout_ms)
        if len(packet) != 64:
            raise HantekUSBError(f"C8: expected 64-byte packet, got {len(packet)}")
        need = byte_count - len(out)
        out.extend(packet[:need])
    return bytes(out)


def decode_roll_rows(raw: bytes) -> tuple[list[int], list[int]]:
    if len(raw) % 4:
        raise HantekUSBError(
            f"ROLL payload is {len(raw)} bytes; expected CH1+extra 4-byte rows"
        )
    ch1: list[int] = []
    extra: list[int] = []
    for i in range(0, len(raw), 4):
        ch1.append(int.from_bytes(raw[i:i + 2], "little") & 0x0FFF)
        extra.append(int.from_bytes(raw[i + 2:i + 4], "little"))
    return ch1, extra


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnostic raw Hantek 1008C ROLL ADC capture")
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--a3", type=parse_byte, default=0x18,
                   help="validated ROLL A3 byte (default: 18 = ~2006 Sa/s)")
    p.add_argument("--range", dest="range_id", type=parse_byte, default=0x02)
    p.add_argument("--samples", type=int, default=4000,
                   help="collect at least this many CH1 rows (default: 4000)")
    p.add_argument("--capture-timeout-s", type=float, default=6.0)
    p.add_argument("--poll-ms", type=float, default=5.0)
    p.add_argument("--usb-timeout-ms", type=int, default=1000)
    p.add_argument("--tag", default="roll-adc")
    args = p.parse_args()

    if args.channel != 1:
        p.error("diagnostic ROLL row decoding is currently validated for CH1 only")
    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.a3 not in ROLL_SAMPLE_RATES:
        p.error("--a3 must be one of the validated ROLL IDs: " +
                ", ".join(f"{x:02X}" for x in sorted(ROLL_SAMPLE_RATES)))
    if args.samples < 1:
        p.error("--samples must be >= 1")
    if args.capture_timeout_s <= 0:
        p.error("--capture-timeout-s must be > 0")

    out = Path("captures")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{args.tag}"
    txlog = out / f"{base}_capture-transactions.jsonl"

    cfg = DirectADCConfig(
        channel=args.channel,
        a3=args.a3,
        range_id=args.range_id,
        timeout_ms=args.usb_timeout_ms,
    )

    chunks: list[bytes] = []
    c7_rows: list[dict] = []
    total_rows = 0

    try:
        with Hantek1008C(logger_path=txlog) as scope:
            session = DirectADCSession(scope, cfg)
            startup_calibration = session.initialize()
            device = scope.connection_id

            # ROLL start is intentionally distinct from acquire_direct_buffers().
            _transact(scope, bytes([0xA3, args.a3]), args.usb_timeout_ms)
            time.sleep(0.010)
            _transact(scope, b"\xF3", args.usb_timeout_ms)
            _transact(scope, bytes.fromhex("A4 02"), args.usb_timeout_ms)
            _transact(scope, b"\xC0", args.usb_timeout_ms)
            _transact(scope, b"\xC2", args.usb_timeout_ms)

            deadline = time.monotonic() + args.capture_timeout_s
            poll = 0
            while total_rows < args.samples and time.monotonic() < deadline:
                poll += 1
                _transact(scope, b"\xF3", args.usb_timeout_ms)
                reply = _transact(scope, b"\xC7", args.usb_timeout_ms)
                if len(reply) != 2:
                    raise HantekUSBError(f"C7: expected 2-byte length, got {len(reply)}")
                ready_bytes = int.from_bytes(reply, "big")
                row = {"poll": poll, "ready_bytes": ready_bytes}
                if ready_bytes == 0:
                    c7_rows.append(row)
                    time.sleep(args.poll_ms / 1000.0)
                    continue
                if ready_bytes % 4:
                    raise HantekUSBError(
                        f"C7 returned {ready_bytes} bytes, not divisible by 4-byte CH1 rows"
                    )
                raw = read_c8_bytes(scope, ready_bytes, args.usb_timeout_ms)
                chunks.append(raw)
                rows = ready_bytes // 4
                total_rows += rows
                row.update({"rows": rows, "total_rows": total_rows})
                c7_rows.append(row)

    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    raw_transport = b"".join(chunks)
    ch1, extra = decode_roll_rows(raw_transport)
    if len(ch1) < args.samples:
        print(
            f"ERROR: collected only {len(ch1)} rows before {args.capture_timeout_s:.3f}s timeout",
            file=sys.stderr,
        )
        return 5

    # Preserve all drained rows in the transport file.  The CH1 convenience
    # file contains the requested prefix only, making repeated comparisons easy.
    selected = ch1[:args.samples]
    raw_path = out / f"{base}_roll-transport.bin"
    ch1_path = out / f"{base}_ch1-u12.bin"
    meta_path = out / f"{base}_capture.json"
    raw_path.write_bytes(raw_transport)
    ch1_path.write_bytes(b"".join(v.to_bytes(2, "little") for v in selected))

    metadata = {
        "timestamp_utc": stamp,
        "tag": args.tag,
        "mode": "diagnostic-roll-direct-adc",
        "canonical_acquisition_modified": False,
        "device": device,
        "channel": args.channel,
        "a3_hex": f"{args.a3:02X}",
        "sample_rate": ROLL_SAMPLE_RATES[args.a3],
        "range_hex": f"{args.range_id:02X}",
        "requested_samples": args.samples,
        "drained_rows": len(ch1),
        "selected_samples": len(selected),
        "raw_word_summary": summary(selected),
        "extra_lane_summary": summary(extra),
        "startup_calibration": startup_calibration,
        "c7_polls": c7_rows,
        "roll_transport_file": str(raw_path),
        "ch1_u12_file": str(ch1_path),
        "transaction_log": str(txlog),
        "notes": [
            "ROLL path uses A4 02 plus C7/C8 and does not poll burst-ready A5.",
            "CH1 is the first 16-bit word of each validated 4-byte ROLL row.",
            "No voltage conversion or waveform-specific processing was applied.",
        ],
    }
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    s = metadata["raw_word_summary"]
    print(f"Capture complete: {meta_path}")
    print(
        f"ROLL CH1: {len(selected)} samples @ {ROLL_SAMPLE_RATES[args.a3]:g} Sa/s; "
        f"min={s['min']} max={s['max']} mean={s['mean']:.3f} span={s['span']}"
    )
    print(f"Transport rows drained: {len(ch1)} across {len(chunks)} C8 drain(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
