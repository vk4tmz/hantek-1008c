#!/usr/bin/env python3
"""Diagnostic multichannel geometry matrix for the C7/C8 ROLL transport.

No multi-channel layout is assumed. Raw bytes are retained and three neutral
candidate views are reported: every word interleaved by enabled count,
historical 4-byte-row word0 values interleaved by enabled count, and adjacent
word pairs assigned per enabled channel. No samples are filtered or altered.
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
from hantek1008c.acquire import DirectADCConfig, DirectADCSession, _transact
from hantek1008c.multichannel import mask_for_channels, observed_windows_width


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


def parse_channel_sets(value: str) -> tuple[tuple[int, ...], ...]:
    sets = []
    try:
        for group in value.split(";"):
            channels = tuple(
                sorted(int(part.strip()) for part in group.split(",") if part.strip())
            )
            if not channels or any(channel < 1 or channel > 8 for channel in channels):
                raise ValueError
            if len(set(channels)) != len(channels):
                raise ValueError
            sets.append(channels)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "channel sets must look like '1,8;2,5;1,2,5,8'"
        ) from exc
    if not sets or len(set(sets)) != len(sets):
        raise argparse.ArgumentTypeError("channel sets must be non-empty and unique")
    return tuple(sets)


def default_channel_sets() -> tuple[tuple[int, ...], ...]:
    contiguous = tuple(tuple(range(1, count + 1)) for count in range(8, 0, -1))
    sparse = ((1, 8), (2, 5), (1, 5), (5, 8), (1, 5, 8), (1, 2, 5, 8))
    return contiguous + sparse


def u12_words(raw: bytes) -> list[int]:
    return [
        int.from_bytes(raw[offset : offset + 2], "little") & 0x0FFF
        for offset in range(0, len(raw) - 1, 2)
    ]


def stats(values: list[int]) -> dict:
    return {
        "samples": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "span": max(values) - min(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
    }


def deinterleave(values: list[int], width: int) -> dict:
    complete = len(values) - len(values) % width
    lanes = [values[lane:complete:width] for lane in range(width)]
    return {
        "width": width,
        "complete_rows": complete // width,
        "tail_values": values[complete:],
        "lanes": [stats(lane) for lane in lanes],
    }


def candidate_views(raw: bytes, enabled_count: int) -> dict:
    words = u12_words(raw)
    complete_4byte_words = len(words) - len(words) % 2
    word0 = words[:complete_4byte_words:2]

    paired_complete = len(words) - len(words) % (2 * enabled_count)
    paired_lanes = [[] for _ in range(enabled_count)]
    for base in range(0, paired_complete, 2 * enabled_count):
        for lane in range(enabled_count):
            paired_lanes[lane].extend(words[base + 2 * lane : base + 2 * lane + 2])

    padded_width = observed_windows_width(enabled_count)
    return {
        "raw_trailing_byte_hex": raw[len(raw) - len(raw) % 2 :].hex(" ").upper(),
        "all_words_enabled_count": deinterleave(words, enabled_count),
        "historical_word0_enabled_count": deinterleave(word0, enabled_count),
        "paired_words_per_enabled_channel": {
            "width": enabled_count,
            "complete_rows": paired_complete // (2 * enabled_count),
            "tail_words": words[paired_complete:],
            "lanes": [stats(lane) for lane in paired_lanes],
        },
        "all_words_triggered_padded_width": deinterleave(words, padded_width),
    }


def transact(scope, payload: bytes, timeout_ms: int) -> bytes:
    return _transact(scope, payload, timeout_ms)


def read_c8_bytes(scope, byte_count: int, timeout_ms: int) -> bytes:
    raw = bytearray()
    while len(raw) < byte_count:
        scope.write(b"\xC8", timeout_ms=timeout_ms)
        packet = scope.read(size=64, timeout_ms=timeout_ms)
        if len(packet) != 64:
            raise HantekUSBError(f"C8: expected 64-byte packet, got {len(packet)}")
        raw.extend(packet[: byte_count - len(raw)])
    return bytes(raw)


def run_experiment(channels: tuple[int, ...], args, stamp: str) -> dict:
    channel_tag = "-".join(str(channel) for channel in channels)
    stem = f"{stamp}_roll-channels-{channel_tag}-a3-{args.a3:02x}"
    txlog = args.output_dir / f"{stem}_transactions.jsonl"
    cfg = DirectADCConfig(
        channel=1,
        a3=args.a3,
        range_id=args.range_id,
        timeout_ms=args.usb_timeout_ms,
    )

    chunks = []
    polls = []
    with Hantek1008C(logger_path=txlog) as scope:
        session = DirectADCSession(scope, cfg)
        calibration = session.initialize()
        device = scope.connection_id

        aa = mask_for_channels(channels)
        for payload in (
            b"\xF3",
            bytes([0xA0, len(channels)]),
            bytes([0xAA, *aa]),
            bytes([0xA2] + [args.range_id] * 8),
            bytes([0xA3, args.a3]),
        ):
            transact(scope, payload, args.usb_timeout_ms)
        time.sleep(0.010)
        for payload in (b"\xF3", bytes.fromhex("A4 02"), b"\xC0", b"\xC2"):
            transact(scope, payload, args.usb_timeout_ms)

        capture_started = time.perf_counter_ns()
        deadline = time.monotonic() + args.capture_s
        while time.monotonic() < deadline:
            transact(scope, b"\xF3", args.usb_timeout_ms)
            reply = transact(scope, b"\xC7", args.usb_timeout_ms)
            if len(reply) != 2:
                raise HantekUSBError(f"C7: expected 2-byte length, got {len(reply)}")
            ready_bytes = int.from_bytes(reply, "big")
            poll = {"ready_bytes": ready_bytes}
            if ready_bytes:
                chunk = read_c8_bytes(scope, ready_bytes, args.usb_timeout_ms)
                chunks.append(chunk)
                poll["drained_bytes"] = len(chunk)
            polls.append(poll)
            if args.poll_ms:
                time.sleep(args.poll_ms / 1000.0)
        capture_ended = time.perf_counter_ns()

    raw = b"".join(chunks)
    raw_path = args.output_dir / f"{stem}.bin"
    raw_path.write_bytes(raw)
    elapsed = (capture_ended - capture_started) / 1_000_000_000.0
    return {
        "status": "ok",
        "logical_channels": list(channels),
        "logical_channel_count": len(channels),
        "a0": len(channels),
        "aa": list(mask_for_channels(channels)),
        "a3_hex": f"{args.a3:02X}",
        "historical_ch1_rate": ROLL_SAMPLE_RATES[args.a3],
        "device": device,
        "range_hex": f"{args.range_id:02X}",
        "capture_elapsed_s": elapsed,
        "raw_bytes": len(raw),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "word_count": len(u12_words(raw)),
        "word_throughput_per_s": len(u12_words(raw)) / elapsed if elapsed else None,
        "c7_poll_count": len(polls),
        "c7_nonzero_count": sum(bool(row["ready_bytes"]) for row in polls),
        "c7_polls": polls,
        "candidate_views": candidate_views(raw, len(channels)),
        "raw_file": str(raw_path),
        "transaction_log": str(txlog),
        "startup_calibration": calibration,
    }


def run_with_retry(channels: tuple[int, ...], args, stamp: str) -> dict:
    started = time.monotonic()
    deadline = started + args.retry_timeout_s
    attempt = 0
    while True:
        attempt += 1
        try:
            result = run_experiment(channels, args, stamp)
            if attempt > 1:
                print("[USB recovery]")
                print("  - Recovery: SUCCESS")
                print(f"  - Ready after: {time.monotonic() - started:.1f} seconds")
                print(f"  - Full experiment attempts: {attempt}\n")
            return result
        except HantekUSBError as exc:
            elapsed = time.monotonic() - started
            if attempt == 1:
                print("[USB recovery]")
                print(f"  - Initial experiment failed: {exc}")
                print(f"  - Retry window: {args.retry_timeout_s:.1f} seconds")
                print(f"  - Retry interval: {args.retry_interval_s:.1f} seconds")
            else:
                print(f"  - Retry {attempt - 1} at +{elapsed:.1f}s: {exc}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print("  - Recovery: FAILED\n")
                return {
                    "status": "error",
                    "logical_channels": list(channels),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            time.sleep(min(args.retry_interval_s, remaining))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--channel-sets", type=parse_channel_sets,
        help="semicolon-separated masks; default runs contiguous 8..1 plus sparse set",
    )
    parser.add_argument("--a3", type=parse_byte, default=0x18)
    parser.add_argument("--range", dest="range_id", type=parse_byte, default=0x03)
    parser.add_argument("--capture-s", type=float, default=2.0)
    parser.add_argument("--poll-ms", type=float, default=5.0)
    parser.add_argument("--usb-timeout-ms", type=int, default=1000)
    parser.add_argument("--retry-timeout-s", type=float, default=15.0)
    parser.add_argument("--retry-interval-s", type=float, default=0.5)
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path("captures/roll-multichannel-a3-18"),
    )
    args = parser.parse_args()

    if args.a3 not in ROLL_SAMPLE_RATES:
        parser.error("--a3 is not a validated CH1 ROLL profile")
    if args.range_id not in (1, 2, 3):
        parser.error("--range must be 01, 02, or 03")
    if args.capture_s <= 0 or args.poll_ms < 0:
        parser.error("--capture-s must be > 0 and --poll-ms must be >= 0")
    if args.retry_timeout_s < 0 or args.retry_interval_s <= 0:
        parser.error("retry timeout must be >= 0 and interval must be > 0")

    channel_sets = args.channel_sets or default_channel_sets()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results = []

    print("Diagnostic only: canonical ROLL, Scan, and Triggered paths are unchanged.")
    print("Both words of every C7/C8 4-byte transport row remain unmodified.\n")
    for index, channels in enumerate(channel_sets, 1):
        names = ",".join(f"CH{channel}" for channel in channels)
        print("=" * 72)
        print(f"ROLL experiment {index}/{len(channel_sets)}")
        print(f"  - Enabled channels: {names}")
        print(f"  - A3={args.a3:02X}")
        print(f"  - Capture duration: {args.capture_s:.1f} seconds\n")
        result = run_with_retry(channels, args, stamp)
        results.append(result)
        if result["status"] == "ok":
            print("Capture result")
            print(f"  - Raw bytes: {result['raw_bytes']}")
            print(f"  - ADC-like words: {result['word_count']}")
            print(f"  - Word throughput: {result['word_throughput_per_s']:.3f} words/s")
            print(f"  - Non-empty C7 polls: {result['c7_nonzero_count']}\n")
        else:
            print(f"ERROR: {result['error']}\n")

    report_path = args.output_dir / f"{stamp}_multichannel-roll.json"
    report_path.write_text(json.dumps({
        "format": "hantek1008c-multichannel-roll-probe-v1",
        "timestamp_utc": stamp,
        "canonical_acquisition_modified": False,
        "results": results,
    }, indent=2) + "\n", encoding="utf-8")
    print("=" * 72)
    print(f"Results: {report_path}")
    return 0 if all(row["status"] == "ok" for row in results) else 4


if __name__ == "__main__":
    raise SystemExit(main())
