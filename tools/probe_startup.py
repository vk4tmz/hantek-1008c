#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.transport import hex_bytes


KNOWN_STARTUP = {
    "B9": bytes.fromhex("B9 01 BF 04 00 00"),
    "B7": bytes.fromhex("B7 00"),
    "BB": bytes.fromhex("BB 08 00"),
}


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Probe one documented parameterised Hantek 1008C startup command. "
            "No command is sent unless explicitly selected."
        )
    )
    p.add_argument(
        "--command",
        choices=sorted(KNOWN_STARTUP),
        required=True,
        help="startup command to send",
    )
    p.add_argument(
        "--timeout-ms",
        type=int,
        default=250,
        help="bulk-IN timeout (default: 250)",
    )
    p.add_argument(
        "--log",
        default="captures/startup-probes.jsonl",
        help="JSONL transaction log path",
    )
    return p.parse_args()


def main():
    args = parse_args()
    payload = KNOWN_STARTUP[args.command]

    print(f"Selected {args.command}")
    print(f"TX  {hex_bytes(payload)}")
    print(f"Logging transaction to {args.log}")

    try:
        with Hantek1008C(logger_path=args.log) as scope:
            tx = scope.transact(
                payload,
                read_timeout_ms=args.timeout_ms,
            )
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    if tx.timed_out:
        print(f"RX  <timeout after {args.timeout_ms} ms>")
    else:
        print(f"RX  {hex_bytes(tx.rx or b'')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
