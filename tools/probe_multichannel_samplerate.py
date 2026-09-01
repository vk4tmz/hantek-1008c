#!/usr/bin/env python3
"""Protocol-lab matrix for Hantek 1008C multi-channel acquisition geometry.

This tool deliberately keeps unproven multi-channel behaviour out of the
canonical DirectADCSession API. It runs controlled raw A0/AA combinations,
records every frame, and evaluates 1..8 possible interleave widths offline.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession, SAMPLE_RATES, acquire_direct_buffers
from hantek1008c.multichannel import (
    AcquisitionPlan,
    candidate_geometry,
    deinterleave_words,
    estimate_period_generic,
    make_plan,
    observed_windows_width,
    u12_words,
)


def parse_hex_byte(value: str) -> int:
    n = int(value, 16)
    if not 0 <= n <= 0xFF:
        raise argparse.ArgumentTypeError("must be one hex byte")
    return n


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Hantek 1008C multi-channel/sample-rate protocol laboratory")
    p.add_argument("--suite", choices=("rate", "semantics", "partner", "all"), default="rate")
    p.add_argument("--a3", type=parse_hex_byte, default=0x11, help="A3 timebase byte (default: 11)")
    p.add_argument("--range", dest="range_id", type=parse_hex_byte, default=0x03, help="A2 range byte (default: 03)")
    p.add_argument("--repeats", type=int, default=2, help="captures per plan (default: 2)")
    p.add_argument("--ch1-frequency-hz", type=float, default=1000.0)
    p.add_argument("--ch2-frequency-hz", type=float, default=4000.0)
    p.add_argument("--partner-channel", type=int, choices=(4, 6, 8), help="for --suite partner")
    p.add_argument("--partner-frequency-hz", type=float, default=4000.0)
    p.add_argument("--trigger-level-adc", type=lambda x: int(x, 0), default=0x0800)
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--poll-ms", type=float, default=2.0)
    p.add_argument("--tag", default="multichannel-samplerate")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def plans_for(args: argparse.Namespace) -> list[AcquisitionPlan]:
    plans: list[AcquisitionPlan] = []
    if args.suite in ("rate", "all"):
        for n in range(1, 9):
            logical = tuple(range(1, n + 1))
            plans.append(make_plan(
                logical,
                a0_mode="logical",
                aa_mode="logical",
                name=f"rate-n{n}-canonical-mask",
            ))

    if args.suite in ("semantics", "all"):
        # Isolate A0 from AA at each odd boundary. The four combinations answer
        # which field changes physical geometry instead of assuming they are redundant.
        for n in (3, 5, 7):
            logical = tuple(range(1, n + 1))
            for a0_mode, aa_mode in (
                ("logical", "logical"),
                ("width", "logical"),
                ("logical", "width"),
                ("width", "width"),
            ):
                plans.append(make_plan(logical, a0_mode=a0_mode, aa_mode=aa_mode,
                                       name=f"semantics-n{n}-a0-{a0_mode}-aa-{aa_mode}"))
        # Sparse masks prove whether active physical channels are packed rather
        # than requiring contiguous lane numbers.
        for channels in ((1, 8), (1, 3), (1, 4), (1, 6)):
            plans.append(make_plan(channels, a0_mode="logical", aa_mode="logical",
                                   name="sparse-" + "-".join(f"ch{x}" for x in channels)))

    if args.suite in ("partner", "all"):
        if args.partner_channel is None:
            if args.suite == "partner":
                raise SystemExit("ERROR: --suite partner requires --partner-channel 4, 6, or 8")
        else:
            n = args.partner_channel - 1
            logical = tuple(range(1, n + 1))
            # Compare nominal logical mask against the Windows-width mask so a
            # driven partner channel can reveal whether the extra lane is a real ADC.
            plans.append(make_plan(logical, a0_mode="logical", aa_mode="logical", name=f"partner-ch{args.partner_channel}-logical"))
            plans.append(make_plan(logical, a0_mode="width", aa_mode="width", name=f"partner-ch{args.partner_channel}-windows-width"))

    # Stable de-duplication for --suite all.
    unique: list[AcquisitionPlan] = []
    seen = set()
    for plan in plans:
        key = (plan.logical_channels, plan.a0, plan.aa, plan.name)
        if key not in seen:
            unique.append(plan)
            seen.add(key)
    return unique


def tx(scope, payload: bytes, timeout_ms: int) -> bytes:
    t = scope.transact(payload, read_timeout_ms=timeout_ms)
    if t.timed_out:
        raise HantekUSBError(f"{payload.hex(' ').upper()}: timeout")
    return t.rx or b""


def configure_plan(scope, plan: AcquisitionPlan, args: argparse.Namespace) -> None:
    tx(scope, b"\xF3", args.timeout_ms)
    tx(scope, bytes([0xA0, plan.a0]), args.timeout_ms)
    tx(scope, bytes([0xAA, *plan.aa]), args.timeout_ms)
    tx(scope, bytes([0xA2] + [args.range_id] * 8), args.timeout_ms)
    tx(scope, bytes([0xA3, args.a3]), args.timeout_ms)
    tx(scope, bytes.fromhex("C1 00 00"), args.timeout_ms)
    level = args.trigger_level_adc
    tx(scope, bytes([0xAB, (level >> 8) & 0xFF, level & 0xFF]), args.timeout_ms)


def summarize_lane(lane, frequency_hz: float, expected_rate_hz: float | None = None) -> dict:
    est = estimate_period_generic(
        lane, reference_frequency_hz=frequency_hz, expected_rate_hz=expected_rate_hz
    )
    return {
        "samples": len(lane),
        "period_samples": est.period_samples,
        "correlation": est.correlation,
        "derived_rate_hz": est.rate_hz,
        "rms_ac": est.rms_ac,
        "span": est.span,
    }


def run() -> int:
    args = parse_args()
    if args.repeats < 1:
        raise SystemExit("ERROR: --repeats must be >= 1")
    plans = plans_for(args)

    print("Planned experiments:")
    for p in plans:
        print(f"  {p.name:42s} logical={p.logical_channels} A0={p.a0:02X} AA={' '.join(f'{x:02X}' for x in p.aa)}")
    if args.dry_run:
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outdir = Path("captures") / f"{stamp}_{args.tag}"
    outdir.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp_utc": stamp,
        "suite": args.suite,
        "a3_hex": f"{args.a3:02X}",
        "range_hex": f"{args.range_id:02X}",
        "repeats": args.repeats,
        "reference_signals": {
            "ch1_frequency_hz": args.ch1_frequency_hz,
            "ch2_frequency_hz": args.ch2_frequency_hz,
            "partner_channel": args.partner_channel,
            "partner_frequency_hz": args.partner_frequency_hz if args.partner_channel else None,
            "note": "Known frequencies are validation references only; captured samples are not filtered, thresholded, flattened, repaired, or reconstructed.",
        },
        "plans": [],
    }

    try:
        with Hantek1008C(logger_path=outdir / "transactions.jsonl") as scope:
            # Use the already validated canonical initialization/calibration path.
            init_cfg = DirectADCConfig(
                channel=1,
                a3=args.a3,
                range_id=args.range_id,
                timeout_ms=args.timeout_ms,
                trigger_enabled=True,
                trigger_slope_raw=0,
                trigger_level_adc=args.trigger_level_adc,
                trigger_poll_interval_ms=args.poll_ms,
            )
            session = DirectADCSession(scope, init_cfg)
            session.initialize()

            for plan in plans:
                print(f"\n=== {plan.name} ===")
                plan_row = {
                    "name": plan.name,
                    "logical_channels": list(plan.logical_channels),
                    "logical_count": plan.logical_count,
                    "windows_observed_width": observed_windows_width(plan.logical_count),
                    "a0": plan.a0,
                    "aa": list(plan.aa),
                    "aa_channels": list(plan.aa_channels),
                    "captures": [],
                }
                for repeat in range(1, args.repeats + 1):
                    configure_plan(scope, plan, args)
                    b2, b3, state, polls, metrics = acquire_direct_buffers(
                        scope,
                        args.timeout_ms,
                        trigger_enabled=True,
                        poll_interval_ms=args.poll_ms,
                        return_ready_info=True,
                        return_metrics=True,
                    )
                    words = u12_words(b2, b3)
                    stem = f"{plan.name}-r{repeat}"
                    (outdir / f"{stem}-buffer02.bin").write_bytes(b2)
                    (outdir / f"{stem}-buffer03.bin").write_bytes(b3)

                    aa_width = len(plan.aa_channels)
                    plausible_widths = sorted(set((plan.logical_count, plan.a0, aa_width, observed_windows_width(plan.logical_count))))
                    aggregate_rate = SAMPLE_RATES.get(args.a3)
                    geometry = candidate_geometry(
                        words,
                        reference_lane=0,
                        reference_frequency_hz=args.ch1_frequency_hz,
                        lane_counts=plausible_widths,
                        expected_aggregate_rate_hz=aggregate_rate,
                    )
                    capture = {
                        "repeat": repeat,
                        "ready_state": state,
                        "ready_polls": polls,
                        "buffer02_bytes": len(b2),
                        "buffer03_bytes": len(b3),
                        "physical_words": len(words),
                        "metrics": metrics,
                        "candidate_geometry_ch1": geometry,
                    }

                    # Direct summaries for the commanded AA width are useful even
                    # when the candidate sweep later tells us that interpretation was wrong.
                    lanes = deinterleave_words(words, aa_width)
                    capture["aa_width_lane_lengths"] = [len(x) for x in lanes]
                    expected_lane_rate = None if aggregate_rate is None else aggregate_rate / aa_width
                    capture["aa_width_ch1"] = summarize_lane(lanes[0], args.ch1_frequency_hz, expected_lane_rate)
                    if 2 in plan.aa_channels and len(lanes) >= 2:
                        capture["aa_width_ch2"] = summarize_lane(lanes[1], args.ch2_frequency_hz, expected_lane_rate)
                    if args.partner_channel is not None and args.partner_channel in plan.aa_channels:
                        lane_index = list(plan.aa_channels).index(args.partner_channel)
                        if lane_index < len(lanes):
                            capture["aa_width_partner"] = {
                                "physical_channel": args.partner_channel,
                                **summarize_lane(lanes[lane_index], args.partner_frequency_hz, expected_lane_rate),
                            }
                    plan_row["captures"].append(capture)

                    ch1 = capture["aa_width_ch1"]
                    print(
                        f"  repeat={repeat} words={len(words)} AA-width={aa_width} "
                        f"lane-lengths={capture['aa_width_lane_lengths']} "
                        f"CH1 period={ch1['period_samples']} rate={ch1['derived_rate_hz']} corr={ch1['correlation']}"
                    )
                report["plans"].append(plan_row)
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    report_path = outdir / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
