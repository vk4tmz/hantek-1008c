#!/usr/bin/env python3
"""Controlled A/B capture for reference-driver F6.

Fixed hardware/setup:
  CH1 -> onboard 1 kHz / nominal 2 Vpp calibration square
  CH1 only, A2=03, A3=0F

Capture A is current initialization.
Capture B differs only by adding F6 at the reference startup/calibration position.
"""
from __future__ import annotations
import subprocess, sys

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
    run([], "f6-ab-current")
    run(["--reference-f6"], "f6-ab-ref")
    print("\nF6 A/B captures complete.")
    print("Zip captures/*_f6-ab-current* and captures/*_f6-ab-ref* and upload them.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
