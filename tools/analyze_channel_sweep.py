#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hantek1008c.analysis import analyze_periodicity, normalized_autocorr
from hantek1008c.decode import decode_buffers


def resolve(meta_path: Path, stored: str) -> Path:
    p = Path(stored)
    if p.exists():
        return p
    q = meta_path.parent / p.name
    if q.exists():
        return q
    raise FileNotFoundError(stored)


def parse_args():
    p = argparse.ArgumentParser(description="Analyse an 8/4/2/1 active-channel Hantek burst sweep.")
    p.add_argument("captures", nargs="+", help="capture JSON files")
    p.add_argument("--frequency-hz", type=float, required=True)
    p.add_argument("--baseline-8ch-rate", type=float, default=100000.0,
                   help="known 8-channel per-channel rate (default: 100000)")
    p.add_argument("--signal-channel", type=int, choices=range(1,9),
                   help="physical channel carrying the known waveform; otherwise pick greatest AC RMS")
    return p.parse_args()


def main():
    args = parse_args()
    print("capture | active | bytes02+03 | samples/ch | model rate | period | corr(period) | corr(half)")
    print("-" * 108)
    for name in args.captures:
        mp = Path(name)
        meta = json.loads(mp.read_text(encoding="utf-8"))
        active = meta.get("resolved_configuration", {}).get("active_channels", list(range(1,9)))
        n = len(active)
        p2 = resolve(mp, meta["buffer02"]["file"])
        p3 = resolve(mp, meta["buffer03"]["file"])
        b2 = p2.read_bytes(); b3 = p3.read_bytes()
        dec = decode_buffers(b2, b3, active_channels=active)

        if args.signal_channel is not None:
            if args.signal_channel not in dec.channel_ids:
                sig = None
            else:
                sig = dec.channel_ids.index(args.signal_channel)
        else:
            stats = [analyze_periodicity(ch) for ch in dec.channels]
            sig = max(range(len(stats)), key=lambda i: stats[i].rms_ac)

        model_rate = args.baseline_8ch_rate * (8.0 / n)
        period = model_rate / args.frequency_hz
        pi = round(period)
        half = max(1, round(period / 2))
        if sig is None:
            cp = ch = float('nan')
        else:
            samples = dec.channels[sig]
            cp = normalized_autocorr(samples, pi)
            ch = normalized_autocorr(samples, half)

        print(f"{mp.name} | {n:>2} {active!s:<22} | {len(b2):>4}+{len(b3):<4} | "
              f"{dec.samples_per_channel:>10} | {model_rate:>10.0f} | {period:>6.1f} | "
              f"{cp:+.6f} | {ch:+.6f}")

    print("\nModel: per-channel rate = baseline_8ch_rate * 8 / active_channel_count")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
