#!/usr/bin/env python3
"""Controlled A/B capture for public hantek1008py burst guard commands.

Hardware setup:
  CH1 -> onboard 1 kHz / nominal 2 Vpp calibration square wave

Both captures are CH1-only, A2=03, A3=0F.  The second capture differs only by
adding E4 01 / E6 01 immediately before and after the burst acquisition.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

COMMON=[
    sys.executable, "tools/capture_buffers.py",
    "--active-channels", "1",
    "--a3", "0F",
    "--range", "03",
]

def run(extra, tag):
    cmd=COMMON + extra + ["--tag", tag]
    print("\nRUN:", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)

def main():
    run([], "ref-ab-current")
    run(["--reference-burst-guards"], "ref-ab-e4e6")
    print("\nA/B captures complete.")
    print("Zip the matching ref-ab-* capture JSON/BIN/transaction files and upload them.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
