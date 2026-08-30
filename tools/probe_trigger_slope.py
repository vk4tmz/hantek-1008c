#!/usr/bin/env python3
"""Correlate Hantek 1008C C1 raw Edge-slope values with real waveform edges.

Diagnostic protocol-lab tool only. It does not alter or post-process canonical
samples. The known square wave is used solely to identify which already-proven
C1 raw selector corresponds to each physical edge polarity.
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


def edge_summary(words: list[int]) -> dict:
    """Return raw first-difference edge diagnostics; never modify samples."""
    if len(words) < 2:
        return {}
    diff = [b - a for a, b in zip(words, words[1:])]
    rise_i = max(range(len(diff)), key=diff.__getitem__)
    fall_i = min(range(len(diff)), key=diff.__getitem__)
    center = (len(words) - 1) / 2.0
    return {
        "sample_count": len(words),
        "min_adc": min(words),
        "max_adc": max(words),
        "span_adc": max(words) - min(words),
        "mean_adc": statistics.fmean(words),
        "strongest_rising": {"index": rise_i, "delta": diff[rise_i], "distance_from_center": rise_i - center},
        "strongest_falling": {"index": fall_i, "delta": diff[fall_i], "distance_from_center": fall_i - center},
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Hantek 1008C raw C1 Edge-slope correlation probe")
    p.add_argument("--captures-per-slope", type=int, default=6)
    p.add_argument("--trigger-level", type=parse_hex16, default=0x0800,
                   help="AB ADC threshold in hex (default: 0800)")
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--tag", default="trigger-slope")
    args = p.parse_args()
    if args.captures_per_slope < 1:
        p.error("--captures-per-slope must be >= 1")

    print("============================================================")
    print(" Hantek 1008C C1 Edge-trigger slope correlation")
    print(" PHYSICAL CONDITION: CONNECT CH1 TO 1 kHz SQUARE-WAVE SOURCE")
    print(" Keep CH1 connected for the entire probe.")
    print("============================================================")
    print("A3=0F, A2=03, CH1 only, canonical direct-ADC Triggered path")
    print(f"AB trigger level = 0x{args.trigger_level:04X}")
    print("C1 raw mapping is now proven: 00=+/rising, 01=-/falling.")

    out = Path("captures")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{args.tag}"
    txlog = out / f"{base}_transactions.jsonl"
    result_path = out / f"{base}.json"

    cfg = DirectADCConfig(channel=1, a3=0x0F, range_id=0x03,
                          timeout_ms=args.timeout_ms,
                          trigger_slope_raw=0,
                          trigger_level_adc=args.trigger_level)
    rows = []
    # Alternate values to reduce the chance that slow drift is confused with C1.
    sequence = [v for _ in range(args.captures_per_slope) for v in (0, 1)]

    try:
        with Hantek1008C(logger_path=txlog) as scope:
            session = DirectADCSession(scope, cfg)
            session.initialize()
            for n, raw_slope in enumerate(sequence, 1):
                session.set_trigger_slope_raw(raw_slope)
                words = session.acquire_words()
                raw_path = out / f"{base}_c1-{raw_slope:02X}_{n:02d}.bin"
                raw_path.write_bytes(b"".join(v.to_bytes(2, "little") for v in words))
                summary = edge_summary(words)
                row = {
                    "capture": n,
                    "c1_raw": raw_slope,
                    "raw_file": str(raw_path),
                    **summary,
                }
                rows.append(row)
                r = summary.get("strongest_rising", {})
                f = summary.get("strongest_falling", {})
                print(
                    f"capture={n:02d} C1=00 {raw_slope:02X} "
                    f"span={summary.get('span_adc')} "
                    f"rise=i{r.get('index')} d{r.get('delta'):+} "
                    f"fall=i{f.get('index')} d{f.get('delta'):+}"
                )
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    result = {
        "timestamp_utc": stamp,
        "purpose": "diagnostic C1 raw Edge-slope correlation",
        "physical_condition": "CH1 connected to 1 kHz square-wave source",
        "channel": 1,
        "a3_hex": "0F",
        "range_hex": "03",
        "trigger_level_adc": args.trigger_level,
        "transaction_log": str(txlog),
        "captures": rows,
        "interpretation_policy": (
            "C1 raw values are not assigned rising/falling labels by this tool; "
            "orientation was subsequently resolved from the recorded Windows +/- UI chronology: 00=+/rising, 01=-/falling."
        ),
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Results: {result_path}")
    print("Upload the result JSON plus matching *_c1-*.bin files for correlation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
