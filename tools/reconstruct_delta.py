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
        help="absolute delta threshold in ADC counts (default: 6)",
    )
    p.add_argument(
        "--zero-mode",
        choices=("quiet", "balanced", "manual"),
        default="balanced",
        help="delta-zero estimation mode (default: balanced)",
    )
    p.add_argument(
        "--zero",
        type=float,
        help="manual delta-zero value; required with --zero-mode manual",
    )
    p.add_argument(
        "--known-frequency-hz",
        type=float,
        default=1000.0,
        help="known source frequency for provisional horizontal calibration (default: 1000)",
    )
    p.add_argument(
        "--known-vpp",
        type=float,
        default=2.0,
        help="known source peak-to-peak voltage for provisional vertical calibration (default: 2.0)",
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


def estimate_quiet_zero(samples):
    med = statistics.median(samples)
    deviations = [abs(x - med) for x in samples]
    mad = statistics.median(deviations)
    quiet_threshold = max(6.0, 6.0 * mad)
    quiet = [x for x in samples if abs(x - med) < quiet_threshold]
    if not quiet:
        quiet = list(samples)
    return statistics.fmean(quiet), med, mad, quiet_threshold, len(quiet)


def transition_groups(samples, zero, threshold):
    candidates = [
        i for i, raw in enumerate(samples)
        if abs(raw - zero) >= threshold
    ]
    if not candidates:
        return []

    groups = []
    group = [candidates[0]]
    for idx in candidates[1:]:
        if idx <= group[-1] + 1:
            group.append(idx)
        else:
            groups.append(group)
            group = [idx]
    groups.append(group)
    return groups


def group_sign(samples, group, zero):
    total = sum(samples[i] - zero for i in group)
    return 1 if total >= 0 else -1


def estimate_balanced_zero(samples, quiet_zero, threshold):
    """Estimate zero so alternating transition pairs integrate to net zero.

    Detection is anchored by the quiet-zero estimate. Consecutive opposite-sign
    transition groups are paired. For each pair, the zero that makes the total
    selected delta sum exactly zero is:

        zero_pair = sum(raw transition samples) / sample_count

    The median pair value is used for robustness.
    """
    groups = transition_groups(samples, quiet_zero, threshold)
    if len(groups) < 2:
        return quiet_zero, [], groups

    signs = [group_sign(samples, g, quiet_zero) for g in groups]
    pair_zeros = []
    i = 0
    while i + 1 < len(groups):
        if signs[i] == signs[i + 1]:
            i += 1
            continue
        pair = groups[i] + groups[i + 1]
        pair_zeros.append(statistics.fmean(samples[j] for j in pair))
        i += 2

    if not pair_zeros:
        return quiet_zero, [], groups

    return statistics.median(pair_zeros), pair_zeros, groups


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


def plateau_levels(reconstruction, transition_groups_):
    """Estimate alternating low/high plateaus between transition groups."""
    if len(transition_groups_) < 2:
        return []

    levels = []
    for left, right in zip(transition_groups_, transition_groups_[1:]):
        start = left[-1] + 2
        end = right[0] - 1
        if end <= start:
            continue
        segment = reconstruction[start:end]
        if segment:
            levels.append(statistics.median(segment))
    return levels


def provisional_calibration(reconstructed, transition_groups_, known_frequency_hz, known_vpp):
    result = {}

    # Edge-to-edge spacing is half a cycle for a symmetric square wave.
    centers = [
        int(round(statistics.fmean(g)))
        for g in transition_groups_
    ]
    edge_spacings = [b - a for a, b in zip(centers, centers[1:])]
    if edge_spacings and known_frequency_hz > 0:
        median_edge = statistics.median(edge_spacings)
        samples_per_cycle = 2.0 * median_edge
        sample_rate = samples_per_cycle * known_frequency_hz
        result["median_edge_spacing_samples"] = median_edge
        result["samples_per_cycle"] = samples_per_cycle
        result["sample_rate_hz"] = sample_rate
        result["sample_period_s"] = 1.0 / sample_rate if sample_rate > 0 else None

    levels = plateau_levels(reconstructed, transition_groups_)
    if len(levels) >= 2 and known_vpp > 0:
        lows = levels[0::2]
        highs = levels[1::2]

        # Do not assume whether first plateau is physically high or low.
        a = statistics.median(lows) if lows else None
        b = statistics.median(highs) if highs else None
        if a is not None and b is not None:
            pp_counts = abs(b - a)
            result["plateau_a"] = a
            result["plateau_b"] = b
            result["reconstructed_pp_counts"] = pp_counts
            result["volts_per_reconstructed_count"] = (
                known_vpp / pp_counts if pp_counts > 0 else None
            )

    return result


def main():
    args = parse_args()
    if args.threshold < 0:
        raise SystemExit("ERROR: --threshold must be >= 0")
    if args.zero_mode == "manual" and args.zero is None:
        raise SystemExit("ERROR: --zero is required with --zero-mode manual")

    meta_path = Path(args.capture_json) if args.capture_json else newest_capture()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    p2 = resolve(meta_path, meta["buffer02"]["file"])
    p3 = resolve(meta_path, meta["buffer03"]["file"])
    decoded = decode_buffers(p2.read_bytes(), p3.read_bytes())

    ch_index = args.channel - 1 if args.channel else choose_channel(decoded.channels)
    samples = decoded.channels[ch_index]

    quiet_zero, med, mad, quiet_threshold, quiet_count = estimate_quiet_zero(samples)

    pair_zeros = []
    detected_groups = transition_groups(samples, quiet_zero, args.threshold)

    if args.zero_mode == "quiet":
        zero = quiet_zero
    elif args.zero_mode == "manual":
        zero = args.zero
    else:
        zero, pair_zeros, detected_groups = estimate_balanced_zero(
            samples, quiet_zero, args.threshold
        )

    delta = [x - zero for x in samples]
    thresholded_delta = [
        d if abs(d) >= args.threshold else 0.0
        for d in delta
    ]

    reconstructed = cumulative(delta)
    reconstructed_thresholded = cumulative(thresholded_delta)

    recon_display = shifted(reconstructed)
    thresholded_display = shifted(reconstructed_thresholded)

    # Re-detect groups using the final zero for calibration/reporting.
    final_groups = transition_groups(samples, zero, args.threshold)

    cal = provisional_calibration(
        reconstructed_thresholded,
        final_groups,
        args.known_frequency_hz,
        args.known_vpp,
    )

    stem = meta_path.name.replace("_capture.json", "")
    threshold_label = ("%g" % args.threshold).replace(".", "p")
    suffix = f"{args.zero_mode}-th{threshold_label}"

    csv_path = (
        Path(args.csv)
        if args.csv
        else meta_path.parent
        / f"{stem}_ch{ch_index+1}_delta-{suffix}.csv"
    )
    thresholded_png = (
        Path(args.png)
        if args.png
        else meta_path.parent
        / f"{stem}_ch{ch_index+1}_delta-{suffix}.png"
    )

    raw_png = thresholded_png.with_name(thresholded_png.stem + "_raw.png")
    unfiltered_png = thresholded_png.with_name(
        thresholded_png.stem + "_unfiltered.png"
    )

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "sample_index",
            "raw_adc",
            "delta_zero",
            "zero_mode",
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
                args.zero_mode,
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
    ax.axhline(zero, linestyle="--", label=f"{args.zero_mode} delta-zero {zero:.3f}")
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
        f"Hantek 1008C CH{ch_index+1} Unfiltered Delta Reconstruction "
        f"({args.zero_mode} zero)"
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
        f"({args.zero_mode}, threshold={args.threshold:g})"
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
    print(f"Zero mode                : {args.zero_mode}")
    print(f"Raw median               : {med:.3f}")
    print(f"Raw MAD                  : {mad:.3f}")
    print(f"Quiet-estimated zero     : {quiet_zero:.6f}")
    print(f"Selected delta-zero      : {zero:.6f}")
    if pair_zeros:
        print(
            "Balanced pair zeros       : "
            + ", ".join(f"{x:.6f}" for x in pair_zeros)
        )
    print(f"Reconstruction threshold : {args.threshold:.3f} counts")
    print(f"Non-zero filtered deltas : {len(nonzero)}")
    print(f"Filtered delta preview   : {event_preview}")
    print(f"Detected events          : {periodic.event_indices}")
    print(f"Event spacings           : {periodic.event_spacings}")

    print()
    print("=== Provisional calibration from known source ===")
    print(f"Known source frequency   : {args.known_frequency_hz:g} Hz")
    print(f"Known source amplitude   : {args.known_vpp:g} Vpp")
    if "median_edge_spacing_samples" in cal:
        print(f"Median edge spacing      : {cal['median_edge_spacing_samples']:.3f} samples")
        print(f"Samples/cycle            : {cal['samples_per_cycle']:.3f}")
        print(f"Implied sample rate      : {cal['sample_rate_hz']:.3f} samples/s/channel")
        print(f"Implied sample period    : {cal['sample_period_s']*1e6:.6f} us")
    else:
        print("Horizontal calibration   : unavailable")

    if "reconstructed_pp_counts" in cal:
        print(f"Reconstructed p-p        : {cal['reconstructed_pp_counts']:.6f} relative counts")
        print(
            f"Provisional V/count      : "
            f"{cal['volts_per_reconstructed_count']:.9f} V/count"
        )
    else:
        print("Vertical calibration     : unavailable")

    print()
    print(f"Raw plot                 : {raw_png}")
    print(f"Unfiltered reconstruction: {unfiltered_png}")
    print(f"Threshold reconstruction : {thresholded_png}")
    print(f"CSV                      : {csv_path}")
    print()
    print("NOTE: Reconstruction and calibration are still experimental.")
    print("      Factory calibration blocks have not yet been applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
