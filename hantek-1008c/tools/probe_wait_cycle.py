#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.transport import hex_bytes


KNOWN_WAIT_CYCLE = {
    "F3": bytes.fromhex("F3"),
    "A2": bytes.fromhex("A2 01 01 01 01 01 01 01 01"),
    "A4": bytes.fromhex("A4 01"),
    "C0": bytes.fromhex("C0"),
    "C2": bytes.fromhex("C2"),
    "A5": bytes.fromhex("A5 5A"),
}


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Probe one documented Hantek 1008C acquisition waiting-cycle command. "
            "No command is sent unless explicitly selected."
        )
    )
    p.add_argument(
        "--command",
        choices=sorted(KNOWN_WAIT_CYCLE),
        required=True,
        help="waiting-cycle command to send",
    )
    p.add_argument(
        "--timeout-ms",
        type=int,
        default=500,
        help="bulk-IN timeout (default: 500)",
    )
    p.add_argument(
        "--log",
        default="captures/wait-cycle-probes.jsonl",
        help="JSONL transaction log path",
    )
    return p.parse_args()


def main():
    args = parse_args()
    payload = KNOWN_WAIT_CYCLE[args.command]

    print(f"Selected {args.command}")
    print(f"TX  {hex_bytes(payload)}")
    print(f"Logging transaction to {args.log}")

    try:
        with Hantek1008C(logger_path=args.log) as scope:
            tx = scope.transact(payload, read_timeout_ms=args.timeout_ms)
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
