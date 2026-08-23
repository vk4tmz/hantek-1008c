#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
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
    meta_path = Path(args.capture_json) if args.capture_json else newest_capture()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    p2 = resolve(meta_path, meta["buffer02"]["file"])
    p3 = resolve(meta_path, meta["buffer03"]["file"])

    decoded = decode_buffers(p2.read_bytes(), p3.read_bytes())

    stem = meta_path.name.replace("_capture.json", "")
    csv_path = Path(args.csv) if args.csv else meta_path.parent / f"{stem}_decoded.csv"
    png_path = Path(args.png) if args.png else meta_path.parent / f"{stem}_channels.png"

    decoded.write_csv(csv_path)

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("ERROR: matplotlib is required for plotting.", file=sys.stderr)
        print("Install it with: pip install matplotlib", file=sys.stderr)
        return 3

    x = list(range(decoded.samples_per_channel))

    fig, ax = plt.subplots(figsize=(12, 8))
    for ch_index, samples in enumerate(decoded.channels, start=1):
        ax.plot(x, samples, linewidth=0.9, label=f"CH{ch_index}")

    ax.set_title("Hantek 1008C Raw Capture")
    ax.set_xlabel("Sample index")
    ax.set_ylabel("ADC counts (12-bit raw)")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=4)
    fig.tight_layout()
    fig.savefig(png_path, dpi=150)
    plt.close(fig)

    print(f"Decoded channels       : 8")
    print(f"Samples per channel    : {decoded.samples_per_channel}")
    print(f"CSV                    : {csv_path}")
    print(f"PNG                    : {png_path}")
    print("Axes                    : sample index vs raw 12-bit ADC counts")
    print("Voltage/time calibration: not yet applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
