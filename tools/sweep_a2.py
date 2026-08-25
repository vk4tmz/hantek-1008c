#!/usr/bin/env python3
"""Controlled CH1 A2/range sweep using the onboard 1 kHz, 2 Vpp square-wave reference.

Keeps active channels and A3 fixed; varies only A2 range.  Captures are deliberately
not interpreted as volts here: the purpose is to measure decoder-domain span/clipping
for later calibration.
"""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

DEFAULT_RANGES = ["03", "00", "01", "02", "04"]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--ranges", nargs="+", default=DEFAULT_RANGES,
                    help="A2 bytes to test (default: 03 00 01 02 04)")
    ap.add_argument("--a3", default="0F", help="fixed A3 byte (default 0F, proven ~2.4 MS/s)")
    ap.add_argument("--frequency-hz", type=int, default=1000)
    ap.add_argument("--channel", type=int, default=1)
    ap.add_argument("--plot-dir", default="captures/a2-range-plots")
    ap.add_argument("--csv-dir", default="captures/a2-range-csv")
    args=ap.parse_args()

    produced=[]
    for r in args.ranges:
        r=r.upper()
        tag=f"square-{args.frequency_hz}hz-ch{args.channel}-a3-{args.a3.lower()}-a2-{r.lower()}"
        cmd=[sys.executable, "tools/capture_buffers.py",
             "--active-channels", str(args.channel),
             "--a3", args.a3,
             "--range", r,
             "--tag", tag]
        print("\nCAPTURE:", " ".join(cmd), flush=True)
        rc=subprocess.run(cmd).returncode
        if rc:
            print(f"WARNING: A2={r} capture failed rc={rc}; continuing", file=sys.stderr)
            continue
        matches=sorted(Path("captures").glob(f"*_{tag}_capture.json"))
        if matches:
            produced.append(matches[-1])

    if not produced:
        raise SystemExit("No captures completed")

    Path(args.plot_dir).mkdir(parents=True, exist_ok=True)
    Path(args.csv_dir).mkdir(parents=True, exist_ok=True)
    cmd=[sys.executable, "tools/analyze_a3_edges.py",
         *map(str,produced),
         "--frequency-hz", str(args.frequency_hz),
         "--channel", str(args.channel),
         "--plot-dir", args.plot_dir,
         "--csv-dir", args.csv_dir]
    print("\nANALYZE:", " ".join(cmd), flush=True)
    raise SystemExit(subprocess.run(cmd).returncode)

if __name__=="__main__":
    main()
