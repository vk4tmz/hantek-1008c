#!/usr/bin/env python3

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
import time
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.transport import hex_bytes


def hex_payload(value):
    return bytes.fromhex(value.strip())


def parse_byte(value):
    n = int(value, 16)
    if not 0 <= n <= 255:
        raise argparse.ArgumentTypeError("must be one hex byte (00..FF)")
    return n


def parse_args():
    p = argparse.ArgumentParser(description="Stateful Hantek 1008C acquisition capture.")
    p.add_argument("--config", default="config/default.toml")
    p.add_argument("--a3", type=parse_byte, help="override A3 byte, e.g. 11")
    p.add_argument("--range", dest="all_range", type=parse_byte,
                   help="override A2 range for all channels, e.g. 03")
    for ch in range(1, 9):
        p.add_argument(f"--ch{ch}-range", type=parse_byte,
                       help=f"override A2 range for CH{ch}")
    p.add_argument("--a4", type=parse_byte, help="override A4 byte")
    p.add_argument("--ac", help='override AC payload as hex bytes, e.g. "01 F4 00 09 C5 00 09 C5"')
    p.add_argument("--delay-ms", type=int, help="inter-command delay")
    p.add_argument("--timeout-ms", type=int, help="USB read/write timeout")
    p.add_argument("--tag", help="short label added to output filenames")
    p.add_argument("--dry-run", action="store_true", help="print resolved configuration and exit")
    return p.parse_args()


def load_settings(args):
    path = Path(args.config)
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    acq = cfg["acquisition"]
    cap = cfg.get("capture", {})

    ranges = [int(x, 16) for x in acq["ranges"]]
    if len(ranges) != 8:
        raise SystemExit("ERROR: acquisition.ranges must contain exactly 8 bytes")

    if args.all_range is not None:
        ranges = [args.all_range] * 8
    for i in range(8):
        v = getattr(args, f"ch{i+1}_range")
        if v is not None:
            ranges[i] = v

    return {
        "config_file": str(path),
        "a3": args.a3 if args.a3 is not None else int(acq["a3"], 16),
        "ranges": ranges,
        "a4": args.a4 if args.a4 is not None else int(acq["a4"], 16),
        "ac": hex_payload(args.ac) if args.ac else hex_payload(acq["ac"]),
        "delay_ms": args.delay_ms if args.delay_ms is not None else int(cap.get("inter_command_delay_ms", 30)),
        "timeout_ms": args.timeout_ms if args.timeout_ms is not None else int(cap.get("read_timeout_ms", 1000)),
        "tag": args.tag,
    }


def tx(scope, label, payload, settings):
    print(f"{label}: TX {hex_bytes(payload)}")
    t = scope.transact(payload, read_timeout_ms=settings["timeout_ms"])
    if t.timed_out:
        raise HantekUSBError(f"{label}: timed out waiting for reply")
    data = t.rx or b""
    print(f"{label}: RX {len(data)} byte(s): {hex_bytes(data)}")
    return data


def query_size(scope, selector, settings):
    data = tx(scope, f"C6_{selector:02X}", bytes([0xC6, selector]), settings)
    if len(data) != 2:
        raise HantekUSBError(f"C6 {selector:02X}: expected 2-byte size response, got {len(data)}")
    size = int.from_bytes(data, "big")
    print(f"C6_{selector:02X}: interpreted size = {size} byte(s)")
    return size, data


def read_buffer(scope, selector, expected_size, settings):
    payload = bytes([0xA6, selector])
    collected = bytearray()
    packet_count = (expected_size + 63) // 64
    print(f"Reading buffer selector {selector:02X}; target={expected_size} byte(s), packets={packet_count}")
    for packet_index in range(packet_count):
        scope.write(payload, timeout_ms=settings["timeout_ms"])
        chunk = scope.read(size=64, timeout_ms=settings["timeout_ms"])
        if len(chunk) != 64:
            raise HantekUSBError(f"A6 {selector:02X}: expected 64-byte packet, got {len(chunk)}")
        collected.extend(chunk)
        print(f"A6_{selector:02X}: packet {packet_index+1}/{packet_count}, +64 byte(s) (raw={len(collected)})")
    trimmed = bytes(collected[:expected_size])
    print(f"A6_{selector:02X}: raw={len(collected)} byte(s), logical={len(trimmed)} byte(s), discarded_tail={len(collected)-expected_size}")
    return trimmed


def main():
    args = parse_args()
    s = load_settings(args)

    print("Resolved acquisition configuration:")
    print(f"  config : {s['config_file']}")
    print(f"  A3     : {s['a3']:02X}")
    print("  A2     : " + " ".join(f"{x:02X}" for x in s["ranges"]))
    print(f"  A4     : {s['a4']:02X}")
    print(f"  AC     : {hex_bytes(s['ac'])}")
    print(f"  delay  : {s['delay_ms']} ms")
    print(f"  timeout: {s['timeout_ms']} ms")
    if args.dry_run:
        return 0

    startup = [
        ("B9", bytes.fromhex("B9 01 BF 04 00 00")), ("B7", bytes.fromhex("B7 00")),
        ("BB", bytes.fromhex("BB 08 00")), ("B0", b"\xB0"), ("F3", b"\xF3"),
        ("B5", b"\xB5"), ("B6", b"\xB6"), ("E5", b"\xE5"), ("F7", b"\xF7"),
        ("F8", b"\xF8"), ("FA", b"\xFA"), ("F5", b"\xF5"), ("A0", bytes.fromhex("A0 08")),
        ("AA", bytes.fromhex("AA 01 01 01 01 01 01 01 01")),
        ("A3", bytes([0xA3, s["a3"]])), ("C1", bytes.fromhex("C1 00 00")),
        ("A7", bytes.fromhex("A7 00 00")), ("AC", bytes([0xAC]) + s["ac"]),
    ]
    wait = [
        ("F3", b"\xF3"),
        ("A2", bytes([0xA2] + s["ranges"])),
        ("A4", bytes([0xA4, s["a4"]])),
        ("C0", b"\xC0"), ("C2", b"\xC2"),
        ("A5-1", bytes.fromhex("A5 5A")), ("A5-2", bytes.fromhex("A5 5A")),
    ]

    out_dir = Path("captures")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"_{args.tag}" if args.tag else ""
    base = stamp + suffix
    txlog = out_dir / f"{base}_capture-transactions.jsonl"

    try:
        with Hantek1008C(logger_path=txlog) as scope:
            print("\n=== Startup/configuration ===")
            for label, payload in startup:
                tx(scope, label, payload, s)
                time.sleep(s["delay_ms"] / 1000)
            print("\n=== Waiting/acquisition sequence ===")
            for label, payload in wait:
                tx(scope, label, payload, s)
                time.sleep(s["delay_ms"] / 1000)

            print("\n=== Buffer 02 ===")
            size02, raw02 = query_size(scope, 2, s)
            buf02 = read_buffer(scope, 2, size02, s)
            print("\n=== Buffer 03 ===")
            size03, raw03 = query_size(scope, 3, s)
            buf03 = read_buffer(scope, 3, size03, s)
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    p2 = out_dir / f"{base}_buffer02.bin"
    p3 = out_dir / f"{base}_buffer03.bin"
    meta = out_dir / f"{base}_capture.json"
    p2.write_bytes(buf02); p3.write_bytes(buf03)

    metadata = {
        "timestamp_utc": stamp,
        "tag": args.tag,
        "vid_pid": "0783:5725",
        "resolved_configuration": {
            "config_file": s["config_file"],
            "a3_hex": f"{s['a3']:02X}",
            "a2_ranges_hex": [f"{x:02X}" for x in s["ranges"]],
            "a4_hex": f"{s['a4']:02X}",
            "ac_hex": s["ac"].hex().upper(),
            "inter_command_delay_ms": s["delay_ms"],
            "timeout_ms": s["timeout_ms"],
        },
        "buffer02": {"selector": 2, "reported_size_raw_hex": raw02.hex().upper(),
                     "reported_size_bytes": size02, "file": str(p2), "bytes_written": len(buf02)},
        "buffer03": {"selector": 3, "reported_size_raw_hex": raw03.hex().upper(),
                     "reported_size_bytes": size03, "file": str(p3), "bytes_written": len(buf03)},
        "transaction_log": str(txlog),
    }
    meta.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print("\nCapture complete.")
    print(f"Metadata : {meta}")
    print(
        "Resolved: "
        f"A3={s['a3']:02X} "
        f"A2={'/'.join(f'{x:02X}' for x in s['ranges'])} "
        f"A4={s['a4']:02X} "
        f"tag={args.tag or '-'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
