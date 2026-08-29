#!/usr/bin/env python3
"""Validate official C9/CA Scan timing with a known periodic reference tone.

This tool is validation-only.  It reconstructs the evidence-backed official
Scan CH1 order ``word0, word1, next-word0, next-word1, ...`` without changing
sample values, then estimates the frequency of the controlled reference tone.
It performs no smoothing, threshold cleanup, interpolation of acquired values,
or production waveform reconstruction.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c.scan_protocol import (
    le_u12_candidate_rows,
    scan_ch1_observations,
    scan_observation_rate,
)
from hantek1008c.scan_timing import estimate_reference_frequency


def raw_from_result(result: dict) -> bytes:
    parts: list[bytes] = []
    for packet in result.get("ca_packets", []):
        if packet.get("c9_class") != "packet-prefix":
            continue
        observed_hex = packet.get("observed_hex")
        if observed_hex:
            parts.append(bytes.fromhex(observed_hex))
    if not parts:
        raise ValueError("JSON contains no steady-state CA observed_hex payloads")
    return b"".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture_json", type=Path)
    ap.add_argument("--profile", required=True, help="profile to analyze, e.g. 1a")
    ap.add_argument("--expected-hz", type=float, required=True)
    args = ap.parse_args()
    if args.expected_hz <= 0:
        ap.error("--expected-hz must be > 0")

    document = json.loads(args.capture_json.read_text())
    results = document.get("results")
    if not isinstance(results, list):
        raise SystemExit("not an official Scan probe JSON: missing results[]")
    matches = [r for r in results if r.get("profile") == args.profile]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one profile {args.profile!r}, found {len(matches)}")
    result = matches[0]

    raw = raw_from_result(result)
    rows = le_u12_candidate_rows(raw)
    observations = scan_ch1_observations(rows)
    row_rate = result.get("candidate_4byte_row_throughput_per_s")
    if not isinstance(row_rate, (int, float)) or row_rate <= 0:
        raise SystemExit("capture JSON has no valid candidate_4byte_row_throughput_per_s")
    observation_rate = scan_observation_rate(float(row_rate))

    freq, period_samples, intervals = estimate_reference_frequency(observations, observation_rate)
    error_hz = freq - args.expected_hz
    error_pct = (error_hz / args.expected_hz * 100.0) if args.expected_hz else float("nan")

    word0 = [row[0] for row in rows]
    word1 = [row[1] for row in rows]
    w0_freq, w0_period, w0_intervals = estimate_reference_frequency(word0, float(row_rate))
    w1_freq, w1_period, w1_intervals = estimate_reference_frequency(word1, float(row_rate))

    print(f"=== Scan reference-tone timing A3={result.get('a3_hex')} ({result.get('official_time_div')}) ===")
    print(f"rows={len(rows)} row_rate={row_rate:.6f}/s observations={len(observations)} observation_rate={observation_rate:.6f}/s")
    print(f"interleaved: estimated={freq:.6f} Hz expected={args.expected_hz:.6f} Hz error={error_hz:+.6f} Hz ({error_pct:+.3f}%) median_period={period_samples:.6f} obs intervals={intervals}")
    print(f"word0-only control: estimated={w0_freq:.6f} Hz median_period={w0_period:.6f} rows intervals={w0_intervals}")
    print(f"word1-only control: estimated={w1_freq:.6f} Hz median_period={w1_period:.6f} rows intervals={w1_intervals}")
    print("Validation only: no acquired sample values were altered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
