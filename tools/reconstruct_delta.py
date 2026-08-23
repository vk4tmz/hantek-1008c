#!/usr/bin/env python3

import argparse
import csv
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c.decode import decode_buffers
from hantek1008c.analysis import analyze_periodicity


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Experimental Hantek 1008C delta/integrated waveform reconstruction. "
            "This tests a hypothesis; it does not replace the confirmed raw decoder."
        )
    )
    p.add_argument(
        "capture_json",
        nargs="?",
        help="capture metadata JSON; default: newest captures/*_capture.json",
    )
    p.add_argument(
        "--channel",
        type=int,
        choices=range(1, 9),
        help="channel to reconstruct; default: channel with greatest AC RMS",
    )
    p.add_argument(
        "--png",
        help="PNG output path; default derived from capture timestamp",
    )
    p.add_argument(
        "--csv",
        help="CSV output path; default derived from capture timestamp",
    )
    return p.parse_args()


def newest_capture():
    files = sorted(Path("captures").glob("*_capture.json"))
    if not files:
        raise SystemExit("ERROR: no captures/*_capture.json found")
    return files[-1]


def resolve(meta_path: Path, stored: str) -> Path:
    p = Path(stored)
    if p.exists():
        return p
    candidate = meta_path.parent / p.name
    if candidate.exists():
        return candidate
    raise FileNotFoundError(stored)


def rms_ac(values):
    mean = statistics.fmean(values)
    return math.sqrt(statistics.fmean((x - mean) ** 2 for x in values))


def choose_channel(channels):
    return max(range(8), key=lambda i: rms_ac(channels[i]))


def estimate_delta_zero(samples):
    """Estimate the raw code corresponding to 'no change'.

    Use median/MAD to exclude the large transition impulses, then average only
    the quiet samples. This reduces cumulative integration drift.
    """
    med = statistics.median(samples)
    deviations = [abs(x - med) for x in samples]
    mad = statistics.median(deviations)
    threshold = max(6.0, 6.0 * mad)

    quiet = [x for x in samples if abs(x - med) < threshold]
    if not quiet:
        quiet = list(samples)

    return statistics.fmean(quiet), med, mad, threshold, len(quiet)


def main():
    args = parse_args()
    meta_path = Path(args.capture_json) if args.capture_json else newest_capture()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    p2 = resolve(meta_path, meta["buffer02"]["file"])
    p3 = resolve(meta_path, meta["buffer03"]["file"])
    decoded = decode_buffers(p2.read_bytes(), p3.read_bytes())

    ch_index = args.channel - 1 if args.channel else choose_channel(decoded.channels)
    samples = decoded.channels[ch_index]

    zero, med, mad, threshold, quiet_count = estimate_delta_zero(samples)

    delta = [x - zero for x in samples]
    reconstructed = []
    acc = 0.0
    for d in delta:
        acc += d
        reconstructed.append(acc)

    # Shift only for display; preserve shape and relative level.
    recon_min = min(reconstructed)
    reconstructed_display = [x - recon_min for x in reconstructed]

    stem = meta_path.name.replace("_capture.json", "")
    csv_path = Path(args.csv) if args.csv else meta_path.parent / f"{stem}_ch{ch_index+1}_delta-reconstruction.csv"
    png_path = Path(args.png) if args.png else meta_path.parent / f"{stem}_ch{ch_index+1}_delta-reconstruction.png"

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "sample_index",
            "raw_adc",
            "estimated_delta_zero",
            "delta_from_zero",
            "integrated_reconstruction",
            "integrated_reconstruction_shifted",
        ])
        for i, (raw, d, r, rs) in enumerate(
            zip(samples, delta, reconstructed, reconstructed_display)
        ):
            w.writerow([i, raw, f"{zero:.9f}", f"{d:.9f}", f"{r:.9f}", f"{rs:.9f}"])

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("ERROR: matplotlib is required for plotting.", file=sys.stderr)
        return 3

    x = list(range(len(samples)))

    # Use separate figures rather than subplots so raw evidence and hypothesis
    # reconstruction remain visually distinct.
    raw_png = png_path.with_name(png_path.stem + "_raw.png")
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(x, samples)
    ax.axhline(zero, linestyle="--", label=f"estimated delta-zero {zero:.3f}")
    ax.set_title(f"Hantek 1008C CH{ch_index+1} Raw Acquisition")
    ax.set_xlabel("Sample index")
    ax.set_ylabel("Raw ADC code")
    ax.legend()
    fig.tight_layout()
    fig.savefig(raw_png, dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(x, reconstructed_display)
    ax.set_title(
        f"Hantek 1008C CH{ch_index+1} Experimental Delta Reconstruction"
    )
    ax.set_xlabel("Sample index")
    ax.set_ylabel("Integrated relative level (uncalibrated)")
    fig.tight_layout()
    fig.savefig(png_path, dpi=150)
    plt.close(fig)

    periodic = analyze_periodicity(samples)

    print(f"Capture                : {meta_path}")
    print(f"Channel                : CH{ch_index+1}")
    print(f"Samples                : {len(samples)}")
    print(f"Raw median             : {med:.3f}")
    print(f"Raw MAD                : {mad:.3f}")
    print(f"Quiet threshold        : {threshold:.3f} counts")
    print(f"Quiet samples used     : {quiet_count}")
    print(f"Estimated delta-zero   : {zero:.6f}")
    print(f"Raw span               : {max(samples)-min(samples)} counts")
    print(f"Raw RMS AC             : {rms_ac(samples):.6f}")
    print(f"Detected events        : {periodic.event_indices}")
    print(f"Event spacings         : {periodic.event_spacings}")
    print(f"Raw plot               : {raw_png}")
    print(f"Reconstruction plot    : {png_path}")
    print(f"Reconstruction CSV     : {csv_path}")
    print()
    print("NOTE: The integrated trace is an experimental protocol hypothesis.")
    print("      Voltage scaling and physical waveform meaning are not yet confirmed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
