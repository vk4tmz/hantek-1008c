#!/usr/bin/env python3
"""Guide calibration of multiple Hantek 1008C channels and A2 ranges."""
from __future__ import annotations

import argparse
from configparser import ConfigParser
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c.calibration import calibration_path, section_name
from hantek1008c.vertical import parse_range as parse_range_name
from hantek1008c.vertical import range_description, range_name


ROOT = Path(__file__).resolve().parents[1]
CALIBRATE_ZERO = ROOT / "tools" / "calibrate_zero.py"


def parse_range(value: str) -> int:
    try:
        return parse_range_name(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def load_store() -> ConfigParser:
    parser = ConfigParser(interpolation=None)
    parser.optionxform = str
    path = calibration_path()
    if path.exists():
        parser.read(path, encoding="utf-8")
    return parser


def has_zero(connection_id: str, channel: int, range_id: int) -> bool:
    parser = load_store()
    section = section_name(connection_id, channel, range_id)
    if not parser.has_section(section):
        return False
    required = ("zero_adc", "volts_per_count", "samples")
    if not all(parser.has_option(section, key) for key in required):
        return False
    return True


def has_validation(connection_id: str, channel: int, range_id: int) -> bool:
    parser = load_store()
    section = section_name(connection_id, channel, range_id)
    return parser.has_section(section) and parser.getboolean(
        section, "validation_passed", fallback=False
    )


def calibrate(channel: int, range_id: int, *, validation_only: bool) -> int:
    command = [
        sys.executable,
        str(CALIBRATE_ZERO),
        "--channel",
        str(channel),
        "--range",
        range_name(range_id),
    ]
    if validation_only:
        command.extend(
            ("--validation-only", "--yes", "--suppress-connection-instructions")
        )
    else:
        command.extend(
            ("--skip-validation", "--yes", "--suppress-connection-instructions")
        )
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def run_with_retry(channel: int, range_id: int, *, validation_only: bool) -> int:
    operation = "reference validation" if validation_only else "grounded zero"
    while True:
        result = calibrate(channel, range_id, validation_only=validation_only)
        if result == 0:
            return 0
        print("\n[Calibration task failed]")
        print(f"  - Channel: CH{channel}")
        print(f"  - Range: {range_description(range_id)}")
        print(f"  - Operation: {operation}")
        print(f"  - Exit code: {result}")
        while True:
            choice = input(
                "\nChoose [R] to retry this operation or [S] to stop safely: "
            ).strip().lower()
            if choice in ("r", "retry"):
                print(f"\nRetrying {operation} from the beginning...")
                break
            if choice in ("s", "stop"):
                print("\nStopping without attempting later operations.")
                return result
            print("Please enter R or S.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Interactively calibrate selected Hantek 1008C channels and A2 "
            "ranges. Existing complete entries are skipped by default."
        )
    )
    parser.add_argument(
        "--channels",
        type=int,
        nargs="+",
        choices=range(1, 9),
        default=list(range(1, 9)),
        metavar="N",
        help="channels to process (default: 1 2 3 4 5 6 7 8)",
    )
    parser.add_argument(
        "--ranges",
        type=parse_range,
        nargs="+",
        default=[1, 2, 3],
        metavar="RANGE",
        help="ranges to process (default: Narrow Medium Wide)",
    )
    parser.add_argument(
        "--recalibrate",
        action="store_true",
        help="process entries that are already complete",
    )
    args = parser.parse_args()

    from hantek1008c import Hantek1008C, HantekUSBError

    channels = list(dict.fromkeys(args.channels))
    ranges = list(dict.fromkeys(args.ranges))

    try:
        with Hantek1008C() as scope:
            connection_id = scope.connection_id
    except HantekUSBError as exc:
        print(f"ERROR: unable to identify Hantek 1008C: {exc}", file=sys.stderr)
        return 4

    work = []
    for channel in channels:
        zero_ranges = [
            range_id
            for range_id in ranges
            if args.recalibrate or not has_zero(connection_id, channel, range_id)
        ]
        validation_ranges = [
            range_id
            for range_id in ranges
            if range_id in (2, 3)
            and (
                args.recalibrate
                or not has_validation(connection_id, channel, range_id)
            )
        ]
        if zero_ranges or validation_ranges:
            work.append((channel, zero_ranges, validation_ranges))

    print("\nCalibration session")
    print(f"  - Device: {connection_id}")
    print(f"  - Store: {calibration_path()}\n")
    if not work:
        print("All selected calibration and validation work is already complete.")
        return 0

    print("Pending work, grouped by physical connection")
    for channel, zero_ranges, validation_ranges in work:
        print(f"  - CH{channel}")
        if zero_ranges:
            joined = ", ".join(range_description(range_id) for range_id in zero_ranges)
            print(f"      Grounded zero: {joined}")
        if validation_ranges:
            joined = ", ".join(
                range_description(range_id) for range_id in validation_ranges
            )
            print(f"      Onboard reference: {joined}")
    print(
        "\nNarrow (A2=01) deliberately skips the onboard 2 Vp-p reference because that "
        "signal over-ranges the sensitive input state."
    )
    input("\nPress Enter to begin, or Ctrl-C to stop... ")

    total = len(work)
    for number, (channel, zero_ranges, validation_ranges) in enumerate(work, start=1):
        print("\n" + "=" * 72)
        print(f"Channel {number}/{total}")
        print(f"  - Channel: CH{channel}")

        if zero_ranges:
            joined = ", ".join(range_description(range_id) for range_id in zero_ranges)
            print("\n[Connection 1: scope ground]")
            print(f"  Connect the CH{channel} probe input to scope ground.")
            print(f"  The following ranges will run without another cable move: {joined}")
            input("\nPress Enter when CH%d is grounded, or Ctrl-C to stop... " % channel)
            for range_id in zero_ranges:
                print(f"\n--- CH{channel} grounded zero, "
                      f"{range_description(range_id)} ---")
                result = run_with_retry(
                    channel, range_id, validation_only=False
                )
                if result != 0:
                    return result

        if validation_ranges:
            joined = ", ".join(
                range_description(range_id) for range_id in validation_ranges
            )
            print("\n[Connection 2: onboard reference]")
            print(
                f"  Move the CH{channel} probe to the onboard 1 kHz / 2 Vp-p output."
            )
            print(f"  The following ranges will run without another cable move: {joined}")
            input("\nPress Enter when CH%d is on the reference, or Ctrl-C to stop... " % channel)
            for range_id in validation_ranges:
                print(f"\n--- CH{channel} reference validation, "
                      f"{range_description(range_id)} ---")
                result = run_with_retry(
                    channel, range_id, validation_only=True
                )
                if result != 0:
                    return result

    print("\nAll requested grouped calibrations completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCalibration stopped by user; completed entries remain saved.", file=sys.stderr)
        raise SystemExit(130)
