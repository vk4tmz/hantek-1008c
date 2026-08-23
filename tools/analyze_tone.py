#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c.analysis import analyze_periodicity, normalized_autocorr
from hantek1008c.decode import decode_buffers


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Analyse a known-frequency tone in a Hantek 1008C capture without "
            "blindly trusting the single strongest autocorrelation peak."
        )
    )
    p.add_argument("capture_json")
    p.add_argument("--frequency-hz", type=float, required=True)
    p.add_argument(
        "--candidate-rate",
        type=float,
        default=100000.0,
        help="candidate per-channel sample rate in samples/s (default: 100000)",
    )
    p.add_argument(
        "--channel",
        type=int,
        choices=range(1, 9),
        help="channel to inspect; default: channel with greatest AC RMS",
    )
    return p.parse_args()


def resolve(meta_path: Path, stored: str) -> Path:
    p = Path(stored)
    if p.exists():
        return p
    q = meta_path.parent / p.name
    if q.exists():
        return q
    raise FileNotFoundError(stored)


def main():
    args = parse_args()

    meta_path = Path(args.capture_json)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    p2 = resolve(meta_path, meta["buffer02"]["file"])
    p3 = resolve(meta_path, meta["buffer03"]["file"])
    decoded = decode_buffers(p2.read_bytes(), p3.read_bytes())

    results = [analyze_periodicity(ch) for ch in decoded.channels]

    if args.channel:
        ch_index = args.channel - 1
    else:
        ch_index = max(range(8), key=lambda i: results[i].rms_ac)

    samples = decoded.channels[ch_index]
    generic = results[ch_index]

    expected = args.candidate_rate / args.frequency_hz
    nearest = max(1, round(expected))

    print(f"Capture               : {meta_path}")
    print(f"Channel               : CH{ch_index+1}")
    print(f"Known frequency       : {args.frequency_hz:g} Hz")
    print(f"Candidate sample rate : {args.candidate_rate:g} samples/s/channel")
    print(f"Expected period       : {expected:.6f} samples")
    print(f"Nearest integer lag   : {nearest}")
    print(f"Raw span              : {generic.span}")
    print(f"Raw RMS AC            : {generic.rms_ac:.6f}")
    print(f"Generic best period   : {generic.dominant_period_samples}")
    print(f"Generic best corr     : {generic.dominant_corr:.6f}")
    print()
    print("Correlation around expected fundamental:")
    lo = max(1, nearest - 3)
    hi = min(len(samples) - 1, nearest + 3)
    for lag in range(lo, hi + 1):
        corr = normalized_autocorr(samples, lag)
        print(f"  lag {lag:4d}: {corr:+.6f}")

    print()
    print("Expected-period harmonics/multiples:")
    for mult in range(1, 9):
        lag = round(expected * mult)
        if lag <= 0 or lag >= len(samples):
            continue
        corr = normalized_autocorr(samples, lag)
        print(f"  {mult}x  lag {lag:4d}: {corr:+.6f}")

    print()
    print("Half-period / edge-related candidates:")
    for div in (2, 4):
        lag = round(expected / div)
        if lag > 0:
            corr = normalized_autocorr(samples, lag)
            print(f"  period/{div:<2d} lag {lag:4d}: {corr:+.6f}")

    # Also show the strongest local peaks, but do not call them the physical
    # fundamental automatically.
    scored = []
    max_lag = min(len(samples)//2, 250)
    for lag in range(4, max_lag + 1):
        corr = normalized_autocorr(samples, lag)
        if corr is not None:
            scored.append((corr, lag))
    scored.sort(reverse=True)

    print()
    print("Top autocorrelation lags:")
    shown = 0
    used = []
    for corr, lag in scored:
        if any(abs(lag - x) <= 1 for x in used):
            continue
        used.append(lag)
        print(f"  lag {lag:4d}: {corr:+.6f}")
        shown += 1
        if shown >= 10:
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
