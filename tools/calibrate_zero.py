#!/usr/bin/env python3
"""User-assisted zero calibration and onboard-reference validation."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession
from hantek1008c.calibration import (
    DEFAULT_VALIDATION_TRIGGERED_ACQUISITIONS,
    DEFAULT_ZERO_TRIGGERED_ACQUISITIONS,
    build_zero_calibration,
    calibration_path,
    load_max_zero_shift_counts,
    load_zero_calibration,
    save_max_zero_shift_counts,
    save_reference_validation,
    save_zero_calibration,
    validate_zero_candidate,
    validate_onboard_reference,
)
from hantek1008c.vertical import parse_range, range_description


def parse_byte(value: str) -> int:
    try:
        return parse_range(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def prompt(message: str, assume_yes: bool) -> None:
    if assume_yes:
        print(message)
        return
    input(message + "\nPress Enter when ready... ")


def prompt_with_keepalive(scope: Hantek1008C, message: str, assume_yes: bool) -> None:
    """Keep the USB session alive while waiting for an operator action."""
    if assume_yes:
        print(message)
        return

    stop = threading.Event()
    failures: list[HantekUSBError] = []

    def keepalive() -> None:
        while not stop.is_set():
            try:
                transaction = scope.transact(b"\xF3", read_timeout_ms=1000)
                if transaction.timed_out or transaction.rx != b"\xF3":
                    raise HantekUSBError("F3 keepalive did not return its expected echo")
            except HantekUSBError as exc:
                failures.append(exc)
                stop.set()
                return
            stop.wait(0.5)

    worker = threading.Thread(target=keepalive, name="hantek-keepalive", daemon=True)
    worker.start()
    try:
        input(message + "\nPress Enter when ready... ")
    finally:
        stop.set()
        worker.join()
    if failures:
        raise failures[0]


def open_initialized_session(
    cfg: DirectADCConfig,
    *,
    retry_timeout_s: float = 15.0,
    retry_interval_s: float = 0.5,
) -> tuple[Hantek1008C, DirectADCSession]:
    """Open and initialize, tolerating a temporary USB re-enumeration."""
    started = time.monotonic()
    deadline = started + retry_timeout_s
    attempt = 0
    recovery_announced = False
    last_error: HantekUSBError | None = None

    while True:
        attempt += 1
        scope = Hantek1008C()
        try:
            scope.open()
            session = DirectADCSession(scope, cfg)
            session.initialize()
            if recovery_announced:
                elapsed = time.monotonic() - started
                print("  - Recovery: SUCCESS")
                print(f"  - Ready after: {elapsed:.1f} seconds")
                print(f"  - Open/initialize attempts: {attempt}\n")
            return scope, session
        except HantekUSBError as exc:
            last_error = exc
            scope.close()
            elapsed = time.monotonic() - started
            if not recovery_announced:
                print("\n[USB recovery]")
                print(f"  - Initial open/initialize failed: {exc}")
                print(f"  - Retry window: {retry_timeout_s:.1f} seconds")
                print(f"  - Retry interval: {retry_interval_s:.1f} seconds")
                recovery_announced = True
            else:
                print(f"  - Retry {attempt - 1} at +{elapsed:.1f}s: {exc}")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print("  - Recovery: FAILED")
                print(f"  - Attempts: {attempt}\n")
                raise HantekUSBError(
                    f"device did not become ready within {retry_timeout_s:.1f} seconds; "
                    f"last error: {last_error}"
                ) from last_error
            time.sleep(min(retry_interval_s, remaining))


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
    parser.add_argument(
        "--max-zero-shift-counts",
        type=float,
        help=(
            "maximum permitted change from an existing zero calibration; "
            "a successful grounded calibration persists this device policy "
            "(default: saved policy or 20 counts)"
        ),
    )
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument(
        "--validation-only",
        action="store_true",
        help="validate an existing saved zero/scale without replacing it",
    )
    parser.add_argument(
        "--suppress-connection-instructions",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--yes", action="store_true", help="do not wait for interactive prompts")
    args = parser.parse_args()
    if args.skip_validation and args.validation_only:
        parser.error("--skip-validation and --validation-only are mutually exclusive")
    if args.validation_only and args.range_id == 1:
        parser.error("A2=01 cannot use the onboard 2 Vp-p reference")
    if args.suppress_connection_instructions and not args.yes:
        parser.error("--suppress-connection-instructions requires --yes")
    if args.zero_triggered_acquisitions < 1 or args.validation_triggered_acquisitions < 1:
        parser.error("Triggered acquisition counts must be >= 1")
    if args.max_zero_shift_counts is not None and (
        not math.isfinite(args.max_zero_shift_counts)
        or args.max_zero_shift_counts <= 0
    ):
        parser.error("--max-zero-shift-counts must be > 0")

    cfg = DirectADCConfig(channel=args.channel, a3=0x0F, range_id=args.range_id)
    print("\nCalibration target")
    print(f"  - Channel: CH{args.channel}")
    print(f"  - Range: {range_description(args.range_id)}")
    print(f"  - Sample rate: {cfg.sample_rate/1e6:.3f} MS/s")
    print(f"  - Store: {calibration_path()}\n")

    if args.validation_only:
        if not args.suppress_connection_instructions:
            prompt(
                f"[Reference validation]\n"
                f"  Connect CH{args.channel} to the onboard 1 kHz / 2 Vp-p output.\n"
                "  Connect the reference only to this target channel.\n"
                "  Disconnect or ground every other scope input.\n"
                "  The existing saved zero and voltage scale will not be modified.",
                args.yes,
            )
        scope = None
        try:
            scope, session = open_initialized_session(cfg)
            connection_id = scope.connection_id
            try:
                cal = load_zero_calibration(
                    connection_id, args.channel, args.range_id
                )
                if cal is None:
                    print(
                        f"ERROR: no saved zero calibration for {connection_id} "
                        f"CH{args.channel} {range_description(args.range_id)}.",
                        file=sys.stderr,
                    )
                    return 7
                reference_frames = [
                    session.acquire_words()
                    for _ in range(args.validation_triggered_acquisitions)
                ]
            finally:
                scope.close()
        except HantekUSBError as exc:
            print(f"ERROR: validation acquisition failed: {exc}", file=sys.stderr)
            return 4

        result = validate_onboard_reference(reference_frames, cal, cfg.sample_rate)
        save_reference_validation(cal, result, calibration_path())
        freq = (
            "unresolved"
            if result.measured_frequency_hz is None
            else f"{result.measured_frequency_hz:.2f} Hz"
        )
        print("\n  Reference result")
        print(f"    - Amplitude: {result.measured_vpp:.3f} Vp-p")
        print(f"    - Frequency: {freq}")
        print(f"    - Validation: {'PASS' if result.passed else 'FAIL'}")
        print("    - Existing zero_adc and volts_per_count were preserved")
        print("\nValidation complete.\n" if result.passed else "\nValidation failed.\n")
        return 0 if result.passed else 8

    if not args.suppress_connection_instructions:
        prompt(
            f"[Phase 1: grounded zero]\n"
            f"  - Connect the CH{args.channel} probe input to scope ground.\n"
            "  - Disconnect or ground every other scope input.\n"
            "  - Do not leave the onboard reference connected to another channel.\n"
            "  - This establishes the zero ADC offset.",
            args.yes,
        )

    scope = None
    try:
        scope, session = open_initialized_session(cfg)
        connection_id = scope.connection_id
        try:
            frames = [
                session.acquire_words()
                for _ in range(args.zero_triggered_acquisitions)
            ]

            zero_words = [word for frame in frames for word in frame]
            cal = build_zero_calibration(
                connection_id, args.channel, args.range_id, zero_words
            )
            span = cal.zero_max - cal.zero_min
            print("\n  Grounded-zero result")
            print(f"    - Mean: {cal.zero_adc:.3f} counts")
            print(f"    - Standard deviation: {cal.zero_stddev:.3f} counts")
            print(f"    - Minimum: {cal.zero_min} counts")
            print(f"    - Maximum: {cal.zero_max} counts")
            print(f"    - Span: {span} counts")
            print(f"    - Samples: {cal.samples}")
            if cal.zero_stddev > args.max_zero_stddev or span > args.max_zero_span:
                print(
                    "ERROR: grounded capture is too variable; calibration was NOT saved. "
                    "Check the ground connection and retry.",
                    file=sys.stderr,
                )
                return 5
            previous = load_zero_calibration(
                connection_id, args.channel, args.range_id
            )
            if args.max_zero_shift_counts is None:
                max_shift, policy_source = load_max_zero_shift_counts(connection_id)
            else:
                max_shift = args.max_zero_shift_counts
                policy_source = "command line"

            print("\n  Zero-calibration safeguard")
            if previous is None:
                print("    - Existing zero: none (first calibration for this entry)")
            else:
                print(f"    - Existing zero: {previous.zero_adc:.3f} counts")
            print(f"    - Candidate zero: {cal.zero_adc:.3f} counts")
            print(f"    - Maximum permitted shift: +/-{max_shift:g} counts")
            print(f"    - Policy source: {policy_source}")
            try:
                shift = validate_zero_candidate(cal, previous, max_shift)
            except ValueError as exc:
                print(f"    - Result: REJECTED\n\nERROR: {exc}.", file=sys.stderr)
                print(
                    "The existing calibration and saved policy were not modified. "
                    "Verify that the probe input is grounded and retry.",
                    file=sys.stderr,
                )
                return 9
            if shift is not None:
                print(f"    - Change: {shift:+.3f} counts")
            print("    - Result: PASS")

            if args.max_zero_shift_counts is not None:
                save_max_zero_shift_counts(connection_id, max_shift)
                print(f"    - Saved device policy: +/-{max_shift:g} counts")
            path = save_zero_calibration(cal)
            print("\n  Saved zero calibration")
            print(f"    - Path: {path}")
            print(
                f"    - Nominal {range_description(args.range_id)} scale: "
                f"{cal.volts_per_count:.9g} V/count\n"
            )

            if args.skip_validation:
                print("  Reference validation: skipped for this range")
                print("\nCalibration complete.\n")
                return 0

            prompt_with_keepalive(
                scope,
                f"[Phase 2: reference validation]\n"
                f"  Connect CH{args.channel} to the onboard 1 kHz / 2 Vp-p output.\n"
                "  Connect the reference only to this target channel.\n"
                "  Disconnect or ground every other scope input.\n"
                "  This validates the saved calibration but does not modify it.",
                args.yes,
            )
            reference_frames = [
                session.acquire_words()
                for _ in range(args.validation_triggered_acquisitions)
            ]
        finally:
            scope.close()
    except HantekUSBError as exc:
        print(f"ERROR: acquisition failed: {exc}", file=sys.stderr)
        return 4
    result = validate_onboard_reference(reference_frames, cal, cfg.sample_rate)
    save_reference_validation(cal, result, path)
    freq = "unresolved" if result.measured_frequency_hz is None else f"{result.measured_frequency_hz:.2f} Hz"
    print("\n  Reference result")
    print(f"    - Amplitude: {result.measured_vpp:.3f} Vp-p")
    print(f"    - Frequency: {freq}")
    print(f"    - Validation: {'PASS' if result.passed else 'FAIL'}")
    print("    - zero_adc and volts_per_count were not changed")
    print("\nCalibration complete.\n" if result.passed else "\nCalibration failed.\n")
    return 0 if result.passed else 8


if __name__ == "__main__":
    raise SystemExit(main())
