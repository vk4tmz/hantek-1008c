#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c.analysis import (
    detect_delta_impulse_edges,
    detect_square_edges,
    normalize_reconstructed_waveform,
    reconstruct_thresholded_delta,
)
from hantek1008c.decode import decode_buffers

A3_NS_PER_DIV = {
    0x11: 500_000,
    0x10: 200_000,
    0x0F: 100_000,
    0x0E: 50_000,
}


def resolve(meta_path: Path, stored: str) -> Path:
    p = Path(stored)
    if p.exists():
        return p
    q = meta_path.parent / p.name
    if q.exists():
        return q
    raise FileNotFoundError(stored)


def parse_args():
    p = argparse.ArgumentParser(
        description="Analyze major square-wave transitions in one or more Hantek captures."
    )
    p.add_argument("captures", nargs="+", type=Path)
    p.add_argument("--frequency-hz", type=float, default=1000.0)
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--persistence", type=int, default=8)
    p.add_argument("--min-separation", type=int, default=None)
    p.add_argument("--plot-dir", type=Path, default=None,
                   help="optional directory for normalized waveform PNGs with detected major edges")
    p.add_argument("--csv-dir", type=Path, default=None,
                   help="optional directory for per-sample diagnostic CSV files")
    p.add_argument("--reference-rate", type=float, default=800000.0,
                   help="reference rate for normalized decoder counts (default: 800000)")
    return p.parse_args()


def a3_value(meta):
    rc = meta.get("resolved_configuration", {})
    raw = rc.get("a3_hex", rc.get("a3", rc.get("A3")))
    if raw is None:
        raw = meta.get("a3", meta.get("A3"))
    if raw is None:
        raw = meta.get("resolved", {}).get("a3")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        return int(raw, 16)
    return None


def main():
    args = parse_args()
    print("capture | A3 | time/div | samples | plateau low/high | major edges | spacings | period | measured rate")
    print("-" * 150)
    for meta_path in args.captures:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        p2 = resolve(meta_path, meta["buffer02"]["file"])
        p3 = resolve(meta_path, meta["buffer03"]["file"])
        active = meta["resolved_configuration"]["active_channels"]
        dec = decode_buffers(p2.read_bytes(), p3.read_bytes(), active_channels=active)
        if args.channel not in dec.channel_ids:
            print(f"{meta_path.name} | -- | -- | -- | requested CH{args.channel} not active")
            continue
        samples = dec.channels[dec.channel_ids.index(args.channel)]
        reconstructed, delta_zero = reconstruct_thresholded_delta(samples)
        raw_edges = detect_delta_impulse_edges(samples, frequency_hz=args.frequency_hz)
        measured_rate = raw_edges.sample_rate
        if measured_rate is None:
            print(f"{meta_path.name} | -- | -- | {len(samples):7d} | raw timing INSUFFICIENT")
            continue
        normalized = normalize_reconstructed_waveform(
            reconstructed, measured_rate=measured_rate, reference_rate=args.reference_rate
        )
        result = detect_square_edges(
            normalized.values,
            frequency_hz=args.frequency_hz,
            persistence=args.persistence,
            min_separation=args.min_separation,
        )
        a3 = a3_value(meta)
        ns = A3_NS_PER_DIV.get(a3) if a3 is not None else None
        td = f"{ns/1000:g}us" if ns is not None else "?"
        edges = ",".join(map(str, result.edge_indices)) or "-"
        spacings = ",".join(map(str, result.edge_spacings)) or "-"
        period = f"{result.period_samples:.1f}" if result.period_samples is not None else "INSUFFICIENT"
        rate = f"{measured_rate:,.0f}"
        print(
            f"{meta_path.name} | {(f'{a3:02X}' if a3 is not None else '--'):>2} | {td:>6} | {len(samples):7d} | "
            f"{result.low_level:.1f}/{result.high_level:.1f} | {edges} | {spacings} | {period} | {rate}"
        )

        if args.plot_dir is not None:
            try:
                import matplotlib.pyplot as plt
            except ImportError:
                raise SystemExit("ERROR: matplotlib is required for --plot-dir")
            args.plot_dir.mkdir(parents=True, exist_ok=True)
            fig, ax = plt.subplots(figsize=(12, 5))
            ax.plot(range(len(normalized.values)), normalized.values, linewidth=0.9)
            ax.axhline(result.low_threshold, linestyle="--", linewidth=0.8)
            ax.axhline(result.high_threshold, linestyle="--", linewidth=0.8)
            for edge in result.edge_indices:
                ax.axvline(edge, linewidth=0.8)
            ax.set_title(f"{meta_path.name} CH{args.channel} major-edge detection")
            ax.set_xlabel("Sample index")
            ax.set_ylabel(f"Normalized decoder counts @ {args.reference_rate/1000:g} kS/s reference")
            fig.tight_layout()
            out = args.plot_dir / f"{meta_path.stem}_ch{args.channel}_edges.png"
            fig.savefig(out, dpi=150)
            plt.close(fig)
            print(f"  plot: {out}")

        if args.csv_dir is not None:
            args.csv_dir.mkdir(parents=True, exist_ok=True)
            out_csv = args.csv_dir / f"{meta_path.stem}_ch{args.channel}_normalized.csv"
            edge_set = set(result.edge_indices)
            with out_csv.open("w", newline="", encoding="utf-8") as fp:
                writer = csv.writer(fp)
                writer.writerow([
                    "sample_index", "raw_word", "delta_from_zero",
                    "integrated_delta", "normalized_centered", "edge_flag"
                ])
                for i, (raw, integ, norm) in enumerate(zip(samples, reconstructed, normalized.values)):
                    writer.writerow([i, raw, raw - delta_zero, integ, norm, int(i in edge_set)])
            print(f"  csv : {out_csv}")
    print("\nTiming rate comes from raw delta-impulse clusters. Plot/CSV amplitudes are rate-normalized, centered decoder counts; they are not volts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
