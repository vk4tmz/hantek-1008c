#!/usr/bin/env python3
"""Probe Hantek 1008C AB vertical-trigger threshold behaviour.

Diagnostic protocol-lab tool only. It changes only AB between captures while
holding the acquisition, channel, range, and raw C1 selector constant. Samples
are preserved exactly as returned by the canonical direct-ADC Triggered path.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession


def parse_hex16(value: str) -> int:
    result = int(value, 16)
    if not 0 <= result <= 0xFFFF:
        raise argparse.ArgumentTypeError("hex value must be 0000..FFFF")
    return result


def capture_summary(words: list[int], threshold: int) -> dict:
    if len(words) < 2:
        return {}
    diff = [b - a for a, b in zip(words, words[1:])]
    center = (len(words) - 1) / 2.0
    rise_i = max(range(len(diff)), key=diff.__getitem__)
    fall_i = min(range(len(diff)), key=diff.__getitem__)
    return {
        "sample_count": len(words),
        "min_adc": min(words),
        "max_adc": max(words),
        "span_adc": max(words) - min(words),
        "mean_adc": statistics.fmean(words),
        "threshold_inside_observed_adc_span": min(words) <= threshold <= max(words),
        "strongest_rising": {"index": rise_i, "delta": diff[rise_i], "distance_from_center": rise_i - center},
        "strongest_falling": {"index": fall_i, "delta": diff[fall_i], "distance_from_center": fall_i - center},
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Hantek 1008C AB vertical-trigger threshold probe")
    p.add_argument("--levels", nargs="+", type=parse_hex16,
                   default=[0x07D0, 0x0800, 0x0840, 0x0860, 0x08A0, 0x08E0],
                   help="AB levels as hex words (default: 07D0 0800 0840 0860 08A0 08E0)")
    p.add_argument("--captures-per-level", type=int, default=3)
    p.add_argument("--c1-raw", type=int, choices=(0, 1), default=0,
                   help="hold C1 raw slope selector fixed (default: 0)")
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--tag", default="trigger-level-1khz")
    args = p.parse_args()
    if args.captures_per_level < 1:
        p.error("--captures-per-level must be >= 1")

    print("============================================================")
    print(" Hantek 1008C AB vertical-trigger threshold probe")
    print(" PHYSICAL CONDITION: CONNECT CH1 TO 1 kHz SQUARE-WAVE SOURCE")
    print(" Keep CH1 connected for the entire probe.")
    print("============================================================")
    print("A3=0F, A2=03, CH1 only, canonical direct-ADC Triggered path")
    print(f"C1 held at raw value 00 {args.c1_raw:02X} ({'rising/+' if args.c1_raw == 0 else 'falling/-'})")
    print("AB levels: " + " ".join(f"{v:04X}" for v in args.levels))
    print("No assumption is made that AB numeric values map 1:1 to decoded ADC codes.")

    out = Path("captures")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{args.tag}"
    txlog = out / f"{base}_transactions.jsonl"
    result_path = out / f"{base}.json"

    cfg = DirectADCConfig(channel=1, a3=0x0F, range_id=0x03,
                          timeout_ms=args.timeout_ms,
                          trigger_slope_raw=args.c1_raw,
                          trigger_level_adc=args.levels[0])
    rows = []
    sequence = [level for _ in range(args.captures_per_level) for level in args.levels]

    try:
        with Hantek1008C(logger_path=txlog) as scope:
            session = DirectADCSession(scope, cfg)
            session.initialize()
            for n, level in enumerate(sequence, 1):
                session.set_trigger_level_adc(level)
                words = session.acquire_words()
                raw_path = out / f"{base}_ab-{level:04X}_{n:02d}.bin"
                raw_path.write_bytes(b"".join(v.to_bytes(2, "little") for v in words))
                summary = capture_summary(words, level)
                rows.append({"capture": n, "ab_raw": level, "raw_file": str(raw_path), **summary})
                r = summary.get("strongest_rising", {})
                f = summary.get("strongest_falling", {})
                inside = "yes" if summary.get("threshold_inside_observed_adc_span") else "no"
                print(f"capture={n:02d} AB={level:04X} "
                      f"adc={summary.get('min_adc')}..{summary.get('max_adc')} "
                      f"inside={inside} "
                      f"rise=i{r.get('index')} d{r.get('delta'):+} "
                      f"fall=i{f.get('index')} d{f.get('delta'):+}")
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    result = {
        "timestamp_utc": stamp,
        "purpose": "diagnostic AB vertical-trigger threshold characterization",
        "physical_condition": "CH1 connected to 1 kHz square-wave source",
        "channel": 1,
        "a3_hex": "0F",
        "range_hex": "03",
        "c1_raw": args.c1_raw,
        "ab_levels_raw": args.levels,
        "transaction_log": str(txlog),
        "captures": rows,
        "interpretation_policy": "AB controls vertical trigger level. C1 mapping is now proven from Windows UI chronology: 00=+/rising, 01=-/falling.",
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Results: {result_path}")
    print("Upload the result JSON plus matching *_ab-*.bin files for correlation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
