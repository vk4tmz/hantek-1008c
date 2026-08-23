#!/usr/bin/env python3

from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.transport import hex_bytes


STARTUP_SEQUENCE = [
    ("B9", bytes.fromhex("B9 01 BF 04 00 00")),
    ("B7", bytes.fromhex("B7 00")),
    ("BB", bytes.fromhex("BB 08 00")),
    ("B0", bytes.fromhex("B0")),
    ("F3", bytes.fromhex("F3")),
    ("B5", bytes.fromhex("B5")),
    ("B6", bytes.fromhex("B6")),
    ("E5", bytes.fromhex("E5")),
    ("F7", bytes.fromhex("F7")),
    ("F8", bytes.fromhex("F8")),
    ("FA", bytes.fromhex("FA")),
    ("F5", bytes.fromhex("F5")),
    ("A0", bytes.fromhex("A0 08")),
    ("AA", bytes.fromhex("AA 01 01 01 01 01 01 01 01")),
    ("A3", bytes.fromhex("A3 11")),
    ("C1", bytes.fromhex("C1 00 00")),
    ("A7", bytes.fromhex("A7 00 00")),
    ("AC", bytes.fromhex("AC 01 F4 00 09 C5 00 09 C5")),
]

WAIT_SEQUENCE = [
    ("F3", bytes.fromhex("F3")),
    ("A2", bytes.fromhex("A2 03 03 03 03 03 03 03 03")),
    ("A4", bytes.fromhex("A4 01")),
    ("C0", bytes.fromhex("C0")),
    ("C2", bytes.fromhex("C2")),
    ("A5-1", bytes.fromhex("A5 5A")),
    ("A5-2", bytes.fromhex("A5 5A")),
]


def tx(scope, label, payload, timeout_ms=1000):
    print(f"{label}: TX {hex_bytes(payload)}")
    t = scope.transact(payload, read_timeout_ms=timeout_ms)
    if t.timed_out:
        raise HantekUSBError(f"{label}: timed out waiting for reply")
    data = t.rx or b""
    print(f"{label}: RX {len(data)} byte(s): {hex_bytes(data)}")
    return data


def query_size(scope, selector):
    data = tx(scope, f"C6_{selector:02X}", bytes([0xC6, selector]))
    if len(data) != 2:
        raise HantekUSBError(
            f"C6 {selector:02X}: expected 2-byte size response, got {len(data)}"
        )

    # Observed C6 02 response 0F A0 corresponds to 4000 bytes.
    size = int.from_bytes(data, byteorder="big", signed=False)
    print(f"C6_{selector:02X}: interpreted size = {size} byte(s)")
    return size, data


def read_buffer(scope, selector, expected_size):
    payload = bytes([0xA6, selector])
    collected = bytearray()

    # A6 returns fixed 64-byte packets. For logical sizes not divisible by 64,
    # request ceil(size/64) full packets and trim the concatenated result.
    packet_count = (expected_size + 63) // 64

    print(
        f"Reading buffer selector {selector:02X}; "
        f"target={expected_size} byte(s), packets={packet_count}"
    )

    for packet_index in range(packet_count):
        scope.write(payload, timeout_ms=1000)

        try:
            chunk = scope.read(size=64, timeout_ms=1000)
        except Exception as exc:
            raise HantekUSBError(
                f"A6 {selector:02X}: read failed after {len(collected)} byte(s): {exc}"
            ) from exc

        if not chunk:
            raise HantekUSBError(
                f"A6 {selector:02X}: zero-length packet after {len(collected)} byte(s)"
            )

        if len(chunk) != 64:
            raise HantekUSBError(
                f"A6 {selector:02X}: expected 64-byte packet, got {len(chunk)}"
            )

        collected.extend(chunk)
        print(
            f"A6_{selector:02X}: packet {packet_index + 1}/{packet_count}, "
            f"+{len(chunk)} byte(s) (raw={len(collected)})"
        )

    raw_length = len(collected)
    trimmed = bytes(collected[:expected_size])
    discarded = raw_length - expected_size

    print(
        f"A6_{selector:02X}: raw={raw_length} byte(s), "
        f"logical={len(trimmed)} byte(s), discarded_tail={discarded}"
    )

    return trimmed


def main():
    out_dir = Path("captures")
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    txlog = out_dir / f"{stamp}_capture-transactions.jsonl"

    try:
        with Hantek1008C(logger_path=txlog) as scope:
            print("=== Startup/configuration ===")
            for label, payload in STARTUP_SEQUENCE:
                tx(scope, label, payload)
                time.sleep(0.03)

            print()
            print("=== Waiting/acquisition sequence ===")
            for label, payload in WAIT_SEQUENCE:
                tx(scope, label, payload)
                time.sleep(0.03)

            print()
            print("=== Buffer 02 ===")
            size02, raw_size02 = query_size(scope, 0x02)
            if size02 <= 0:
                raise HantekUSBError("buffer 02 reported zero length")
            buf02 = read_buffer(scope, 0x02, size02)

            print()
            print("=== Buffer 03 ===")
            size03, raw_size03 = query_size(scope, 0x03)
            if size03 <= 0:
                raise HantekUSBError("buffer 03 reported zero length")
            buf03 = read_buffer(scope, 0x03, size03)

    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    path02 = out_dir / f"{stamp}_buffer02.bin"
    path03 = out_dir / f"{stamp}_buffer03.bin"
    meta = out_dir / f"{stamp}_capture.json"

    path02.write_bytes(buf02)
    path03.write_bytes(buf03)

    metadata = {
        "timestamp_utc": stamp,
        "vid_pid": "0783:5725",
        "buffer02": {
            "selector": 2,
            "reported_size_raw_hex": raw_size02.hex().upper(),
            "reported_size_bytes": size02,
            "file": str(path02),
            "bytes_written": len(buf02),
        },
        "buffer03": {
            "selector": 3,
            "reported_size_raw_hex": raw_size03.hex().upper(),
            "reported_size_bytes": size03,
            "file": str(path03),
            "bytes_written": len(buf03),
        },
        "transaction_log": str(txlog),
    }
    meta.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    print()
    print("Capture complete.")
    print(f"Buffer 02: {path02} ({len(buf02)} bytes)")
    print(f"Buffer 03: {path03} ({len(buf03)} bytes)")
    print(f"Metadata : {meta}")
    print(f"TX log   : {txlog}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
