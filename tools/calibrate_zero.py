#!/usr/bin/env python3
"""User-assisted zero calibration and onboard-reference validation."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession
from hantek1008c.calibration import (
    DEFAULT_VALIDATION_TRIGGERED_ACQUISITIONS,
    DEFAULT_ZERO_TRIGGERED_ACQUISITIONS,
    build_zero_calibration,
    calibration_path,
    save_reference_validation,
    save_zero_calibration,
    validate_onboard_reference,
)


def parse_byte(value: str) -> int:
    result = int(value, 16)
    if result not in (1, 2, 3):
        raise argparse.ArgumentTypeError("range must be one of 01, 02, 03")
    return result


def prompt(message: str, assume_yes: bool) -> None:
    if assume_yes:
        print(message)
        return
    input(message + "\nPress Enter when ready... ")


def acquire_frames(cfg: DirectADCConfig, triggered_acquisitions: int) -> tuple[str, list[list[int]]]:
    with Hantek1008C() as scope:
        connection_id = scope.connection_id
        session = DirectADCSession(scope, cfg)
        session.initialize()
        frames = [session.acquire_words() for _ in range(triggered_acquisitions)]
    return connection_id, frames


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate Hantek 1008C channel zero from a grounded probe, then "
            "optionally validate against the onboard 1 kHz / 2 Vp-p reference."
        )
    )
    parser.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    parser.add_argument("--range", dest="range_id", type=parse_byte, default=0x03)
    parser.add_argument("--zero-triggered_acquisitions", type=int, default=DEFAULT_ZERO_TRIGGERED_ACQUISITIONS)
    parser.add_argument("--validation-triggered_acquisitions", type=int, default=DEFAULT_VALIDATION_TRIGGERED_ACQUISITIONS)
    parser.add_argument("--max-zero-stddev", type=float, default=5.0)
    parser.add_argument("--max-zero-span", type=int, default=32)
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--yes", action="store_true", help="do not wait for interactive prompts")
    args = parser.parse_args()
    if args.zero_triggered_acquisitions < 1 or args.validation_triggered_acquisitions < 1:
        parser.error("Triggered acquisition counts must be >= 1")

    cfg = DirectADCConfig(channel=args.channel, a3=0x0F, range_id=args.range_id)
    print(f"Calibration store: {calibration_path()}")
    print(f"Target: CH{args.channel}, A2={args.range_id:02X}, {cfg.sample_rate/1e6:.3f} MS/s")
    prompt(
        f"GROUND CH{args.channel}: connect the probe input to scope ground. "
        "This phase establishes the zero ADC offset.",
        args.yes,
    )

    try:
        connection_id, frames = acquire_frames(cfg, args.zero_triggered_acquisitions)
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4
    zero_words = [word for frame in frames for word in frame]
    cal = build_zero_calibration(connection_id, args.channel, args.range_id, zero_words)
    span = cal.zero_max - cal.zero_min
    print(
        f"Zero result: mean={cal.zero_adc:.3f} counts, stddev={cal.zero_stddev:.3f}, "
        f"min={cal.zero_min}, max={cal.zero_max}, span={span}, n={cal.samples}"
    )
    if cal.zero_stddev > args.max_zero_stddev or span > args.max_zero_span:
        print(
            "ERROR: grounded capture is too variable; calibration was NOT saved. "
            "Check the ground connection and retry.",
            file=sys.stderr,
        )
        return 5
    path = save_zero_calibration(cal)
    print(
        f"Saved zero calibration: {path}\n"
        f"Nominal scale for A2={args.range_id:02X}: {cal.volts_per_count:.9g} V/count"
    )

    if args.skip_validation:
        print("Reference validation skipped. Zero calibration is complete.")
        return 0

    prompt(
        f"REFERENCE CHECK: connect CH{args.channel} to the onboard 1 kHz / 2 Vp-p output. "
        "This validates the saved calibration but will NOT modify it.",
        args.yes,
    )
    try:
        validation_connection, reference_frames = acquire_frames(cfg, args.validation_triggered_acquisitions)
    except HantekUSBError as exc:
        print(f"ERROR: validation capture failed: {exc}", file=sys.stderr)
        return 6
    if validation_connection != connection_id:
        print(
            f"ERROR: device moved from {connection_id} to {validation_connection}; "
            "validation was not associated with the saved calibration.",
            file=sys.stderr,
        )
        return 7
    result = validate_onboard_reference(reference_frames, cal, cfg.sample_rate)
    save_reference_validation(cal, result, path)
    freq = "unresolved" if result.measured_frequency_hz is None else f"{result.measured_frequency_hz:.2f} Hz"
    print(f"Reference result: {result.measured_vpp:.3f} Vp-p, {freq}")
    print("Reference validation: PASS" if result.passed else "Reference validation: FAIL")
    print("Validation never changes zero_adc or volts_per_count.")
    return 0 if result.passed else 8


if __name__ == "__main__":
    raise SystemExit(main())
