#!/usr/bin/env python3

from pathlib import Path
import sys
import time

import usb.core

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.transport import hex_bytes, Transaction


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

C6_02 = bytes.fromhex("C6 02")


def show_reply(label, tx):
    if tx.timed_out:
        print(f"{label}: RX <timeout>")
    else:
        data = tx.rx or b""
        print(f"{label}: RX {len(data)} byte(s): {hex_bytes(data)}")


def transact(scope, label, payload, *, timeout_ms=500, tolerate_pipe=False):
    print(f"{label}: TX {hex_bytes(payload)}")
    try:
        tx = scope.transact(payload, read_timeout_ms=timeout_ms)
        show_reply(label, tx)
        return True
    except HantekUSBError as exc:
        msg = str(exc)
        if tolerate_pipe and ("Pipe error" in msg or "Errno 32" in msg):
            print(f"{label}: RX/USB STALL observed and tolerated: {exc}")
            try:
                scope.dev.clear_halt(scope.ep_in)
                print(f"{label}: cleared halt on IN endpoint 0x{scope.ep_in:02X}")
            except Exception as clear_exc:
                print(f"{label}: warning: unable to clear IN halt: {clear_exc}")
            try:
                scope.dev.clear_halt(scope.ep_out)
                print(f"{label}: cleared halt on OUT endpoint 0x{scope.ep_out:02X}")
            except Exception:
                pass
            return True
        print(f"{label}: ERROR {exc}", file=sys.stderr)
        return False


def main():
    print("Opening Hantek 1008C for one continuous startup/acquisition session...")

    try:
        with Hantek1008C(logger_path="captures/acquisition-sequence.jsonl") as scope:
            print("Interface 0 claimed.")
            print()

            print("=== Startup/configuration ===")
            for label, payload in STARTUP_SEQUENCE:
                if not transact(scope, label, payload):
                    return 4
                time.sleep(0.05)

            print()
            print("=== Baseline buffer query ===")
            if not transact(scope, "C6_02-baseline", C6_02):
                return 4

            print()
            print("=== Waiting/acquisition sequence ===")
            for label, payload in WAIT_SEQUENCE:
                tolerate_pipe = (label == "A4")
                if not transact(scope, label, payload, tolerate_pipe=tolerate_pipe):
                    return 4
                time.sleep(0.05)

            print()
            print("=== Post-sequence buffer query ===")
            if not transact(scope, "C6_02-after", C6_02, timeout_ms=1000):
                return 4

            print()
            print("Sequence completed.")
            print("Log: captures/acquisition-sequence.jsonl")
            return 0

    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
