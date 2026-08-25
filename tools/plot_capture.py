#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c.decode import decode_buffers


def parse_args():
    p = argparse.ArgumentParser(
        description="Decode, export, and plot a Hantek 1008C capture."
    )
    p.add_argument(
        "capture_json",
        nargs="?",
        help="capture metadata JSON; default: newest captures/*_capture.json",
    )
    p.add_argument(
        "--csv",
        help="CSV output path; default derived from capture timestamp",
    )
    p.add_argument(
        "--png",
        help="PNG output path; default derived from capture timestamp",
    )
    p.add_argument(
        "--channel",
        type=int,
        choices=range(1, 9),
        help="plot only one channel (1..8); default: all channels",
    )
    p.add_argument(
        "--center",
        action="store_true",
        help="subtract selected channel mean before plotting",
    )
    p.add_argument(
        "--sample-rate",
        type=float,
        help="per-channel sample rate in samples/s; use time axis when supplied",
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


def main():
    args = parse_args()

    if args.sample_rate is not None and args.sample_rate <= 0:
        raise SystemExit("ERROR: --sample-rate must be > 0")

    meta_path = Path(args.capture_json) if args.capture_json else newest_capture()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    p2 = resolve(meta_path, meta["buffer02"]["file"])
    p3 = resolve(meta_path, meta["buffer03"]["file"])

    active_channels = meta.get("resolved_configuration", {}).get("active_channels", list(range(1, 9)))
    decoded = decode_buffers(p2.read_bytes(), p3.read_bytes(), active_channels=active_channels)

    stem = meta_path.name.replace("_capture.json", "")

    if args.channel:
        suffix = f"_ch{args.channel}"
        if args.center:
            suffix += "_centered"
    else:
        suffix = "_channels"

    csv_path = (
        Path(args.csv)
        if args.csv
        else meta_path.parent / f"{stem}{suffix}.csv"
    )
    png_path = (
        Path(args.png)
        if args.png
        else meta_path.parent / f"{stem}{suffix}.png"
    )

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("ERROR: matplotlib is required for plotting.", file=sys.stderr)
        print("Install it with: pip install matplotlib", file=sys.stderr)
        return 3

    if args.channel:
        if args.channel not in decoded.channel_ids:
            raise SystemExit(f"ERROR: CH{args.channel} was not active in this capture; active={decoded.channel_ids}")
        lane_index = decoded.channel_ids.index(args.channel)
        samples = list(decoded.channels[lane_index])
        mean = statistics.fmean(samples)
        values = [x - mean for x in samples] if args.center else samples

        if args.sample_rate:
            x = [i / args.sample_rate * 1000.0 for i in range(len(values))]
            x_label = "Time (ms)"
        else:
            x = list(range(len(values)))
            x_label = "Sample index"

        # Write a focused CSV for the selected channel.
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8") as fh:
            fh.write("sample_index,time_ms,raw_adc,plotted_value\n")
            for i, (raw, plotted) in enumerate(zip(samples, values)):
                time_ms = (
                    i / args.sample_rate * 1000.0
                    if args.sample_rate
                    else ""
                )
                fh.write(f"{i},{time_ms},{raw},{plotted}\n")

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(x, values)
        ax.set_title(
            f"Hantek 1008C CH{args.channel} "
            + ("Centered Raw Capture" if args.center else "Raw Capture")
        )
        ax.set_xlabel(x_label)
        ax.set_ylabel(
            "ADC counts relative to mean"
            if args.center
            else "ADC counts (12-bit raw)"
        )
        fig.tight_layout()
        fig.savefig(png_path, dpi=150)
        plt.close(fig)

        print(f"Decoded channels       : {len(decoded.channel_ids)} ({decoded.channel_ids})")
        print(f"Selected channel       : CH{args.channel}")
        print(f"Samples                : {len(samples)}")
        print(f"Channel mean           : {mean:.6f} ADC counts")
        if args.sample_rate:
            duration_ms = (len(samples) - 1) / args.sample_rate * 1000.0
            print(f"Sample rate            : {args.sample_rate:.3f} samples/s/channel")
            print(f"Sample period          : {1e6/args.sample_rate:.6f} us")
            print(f"Displayed duration     : {duration_ms:.6f} ms")
        print(f"Centered               : {'yes' if args.center else 'no'}")
        print(f"CSV                    : {csv_path}")
        print(f"PNG                    : {png_path}")
        return 0

    # Existing all-channel behavior.
    decoded.write_csv(csv_path)
    x = list(range(decoded.samples_per_channel))

    fig, ax = plt.subplots(figsize=(12, 8))
    for channel_id, samples in zip(decoded.channel_ids, decoded.channels):
        ax.plot(x, samples, linewidth=0.9, label=f"CH{channel_id}")

    ax.set_title("Hantek 1008C Raw Capture")
    ax.set_xlabel("Sample index")
    ax.set_ylabel("ADC counts (12-bit raw)")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=4)
    fig.tight_layout()
    fig.savefig(png_path, dpi=150)
    plt.close(fig)

    print(f"Decoded channels       : {len(decoded.channel_ids)} ({decoded.channel_ids})")
    print(f"Samples per channel    : {decoded.samples_per_channel}")
    print(f"CSV                    : {csv_path}")
    print(f"PNG                    : {png_path}")
    print("Axes                    : sample index vs raw 12-bit ADC counts")
    print("Voltage/time calibration: not yet applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
