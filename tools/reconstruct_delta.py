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
        "--threshold",
        type=float,
        default=6.0,
        help=(
            "absolute delta-from-zero threshold in ADC counts for the filtered "
            "reconstruction (default: 6)"
        ),
    )
    p.add_argument("--png", help="thresholded reconstruction PNG output path")
    p.add_argument("--csv", help="CSV output path")
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
    med = statistics.median(samples)
    deviations = [abs(x - med) for x in samples]
    mad = statistics.median(deviations)

    # Robust quiet-sample selection. Keep this independent from the user
    # reconstruction threshold so zero estimation remains stable.
    quiet_threshold = max(6.0, 6.0 * mad)

    quiet = [x for x in samples if abs(x - med) < quiet_threshold]
    if not quiet:
        quiet = list(samples)

    return statistics.fmean(quiet), med, mad, quiet_threshold, len(quiet)


def cumulative(values):
    out = []
    acc = 0.0
    for x in values:
        acc += x
        out.append(acc)
    return out


def shifted(values):
    if not values:
        return []
    lo = min(values)
    return [x - lo for x in values]


def main():
    args = parse_args()

    if args.threshold < 0:
        raise SystemExit("ERROR: --threshold must be >= 0")

    meta_path = Path(args.capture_json) if args.capture_json else newest_capture()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    p2 = resolve(meta_path, meta["buffer02"]["file"])
    p3 = resolve(meta_path, meta["buffer03"]["file"])
    decoded = decode_buffers(p2.read_bytes(), p3.read_bytes())

    ch_index = args.channel - 1 if args.channel else choose_channel(decoded.channels)
    samples = decoded.channels[ch_index]

    zero, med, mad, quiet_threshold, quiet_count = estimate_delta_zero(samples)

    delta = [x - zero for x in samples]
    thresholded_delta = [
        d if abs(d) >= args.threshold else 0.0
        for d in delta
    ]

    reconstructed = cumulative(delta)
    reconstructed_thresholded = cumulative(thresholded_delta)

    recon_display = shifted(reconstructed)
    thresholded_display = shifted(reconstructed_thresholded)

    stem = meta_path.name.replace("_capture.json", "")
    threshold_label = ("%g" % args.threshold).replace(".", "p")

    csv_path = (
        Path(args.csv)
        if args.csv
        else meta_path.parent
        / f"{stem}_ch{ch_index+1}_delta-th{threshold_label}.csv"
    )
    thresholded_png = (
        Path(args.png)
        if args.png
        else meta_path.parent
        / f"{stem}_ch{ch_index+1}_delta-th{threshold_label}.png"
    )

    raw_png = thresholded_png.with_name(
        thresholded_png.stem + "_raw.png"
    )
    unfiltered_png = thresholded_png.with_name(
        thresholded_png.stem + "_unfiltered.png"
    )

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "sample_index",
            "raw_adc",
            "estimated_delta_zero",
            "delta_from_zero",
            "threshold",
            "thresholded_delta",
            "integrated_unfiltered",
            "integrated_unfiltered_shifted",
            "integrated_thresholded",
            "integrated_thresholded_shifted",
        ])
        for i, row in enumerate(zip(
            samples,
            delta,
            thresholded_delta,
            reconstructed,
            recon_display,
            reconstructed_thresholded,
            thresholded_display,
        )):
            raw, d, td, ru, rus, rt, rts = row
            w.writerow([
                i,
                raw,
                f"{zero:.9f}",
                f"{d:.9f}",
                f"{args.threshold:.9f}",
                f"{td:.9f}",
                f"{ru:.9f}",
                f"{rus:.9f}",
                f"{rt:.9f}",
                f"{rts:.9f}",
            ])

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("ERROR: matplotlib is required for plotting.", file=sys.stderr)
        return 3

    x = list(range(len(samples)))

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
    ax.plot(x, recon_display)
    ax.set_title(
        f"Hantek 1008C CH{ch_index+1} Unfiltered Delta Reconstruction"
    )
    ax.set_xlabel("Sample index")
    ax.set_ylabel("Integrated relative level (uncalibrated)")
    fig.tight_layout()
    fig.savefig(unfiltered_png, dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(x, thresholded_display)
    ax.set_title(
        f"Hantek 1008C CH{ch_index+1} Thresholded Delta Reconstruction "
        f"(threshold={args.threshold:g})"
    )
    ax.set_xlabel("Sample index")
    ax.set_ylabel("Integrated relative level (uncalibrated)")
    fig.tight_layout()
    fig.savefig(thresholded_png, dpi=150)
    plt.close(fig)

    periodic = analyze_periodicity(samples)

    nonzero = [(i, d) for i, d in enumerate(thresholded_delta) if d != 0]
    event_preview = ", ".join(
        f"{i}:{d:+.1f}" for i, d in nonzero[:16]
    ) or "-"

    print(f"Capture                  : {meta_path}")
    print(f"Channel                  : CH{ch_index+1}")
    print(f"Samples                  : {len(samples)}")
    print(f"Raw median               : {med:.3f}")
    print(f"Raw MAD                  : {mad:.3f}")
    print(f"Quiet-selection threshold: {quiet_threshold:.3f} counts")
    print(f"Quiet samples used       : {quiet_count}")
    print(f"Estimated delta-zero     : {zero:.6f}")
    print(f"Reconstruction threshold : {args.threshold:.3f} counts")
    print(f"Non-zero filtered deltas : {len(nonzero)}")
    print(f"Filtered delta preview   : {event_preview}")
    print(f"Detected events          : {periodic.event_indices}")
    print(f"Event spacings           : {periodic.event_spacings}")
    print(f"Raw plot                 : {raw_png}")
    print(f"Unfiltered reconstruction: {unfiltered_png}")
    print(f"Threshold reconstruction : {thresholded_png}")
    print(f"CSV                      : {csv_path}")
    print()
    print("NOTE: Thresholded integration is an experimental protocol hypothesis.")
    print("      The confirmed raw decoder remains unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
