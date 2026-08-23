#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.transport import hex_bytes


KNOWN_ACQUISITION = {
    "C6_02": bytes.fromhex("C6 02"),
    "A6_02": bytes.fromhex("A6 02"),
    "C6_03": bytes.fromhex("C6 03"),
    "A6_03": bytes.fromhex("A6 03"),
}


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Probe one documented Hantek 1008C acquisition command. "
            "No command is sent unless explicitly selected."
        )
    )
    p.add_argument(
        "--command",
        choices=sorted(KNOWN_ACQUISITION),
        required=True,
        help="acquisition command to send",
    )
    p.add_argument(
        "--timeout-ms",
        type=int,
        default=500,
        help="bulk-IN timeout (default: 500)",
    )
    p.add_argument(
        "--read-size",
        type=int,
        default=64,
        help="maximum bytes to request from bulk IN (default: 64)",
    )
    p.add_argument(
        "--log",
        default="captures/acquisition-probes.jsonl",
        help="JSONL transaction log path",
    )
    return p.parse_args()


def main():
    args = parse_args()
    payload = KNOWN_ACQUISITION[args.command]

    print(f"Selected {args.command}")
    print(f"TX  {hex_bytes(payload)}")
    print(f"Read size: {args.read_size} byte(s)")
    print(f"Logging transaction to {args.log}")

    try:
        with Hantek1008C(logger_path=args.log) as scope:
            tx = scope.transact(
                payload,
                read_size=args.read_size,
                read_timeout_ms=args.timeout_ms,
            )
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    if tx.timed_out:
        print(f"RX  <timeout after {args.timeout_ms} ms>")
    else:
        data = tx.rx or b""
        print(f"RX  {len(data)} byte(s)")
        print(f"RX  {hex_bytes(data)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
