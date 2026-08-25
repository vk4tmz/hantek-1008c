#!/usr/bin/env python3
"""Five-run reproducibility test for reference-driver F6.

Sequence:
  control -> F6 -> F6 -> F6 -> control

Fixed:
  CH1 only
  A2=03
  A3=0F
  onboard 1 kHz / nominal 2 Vpp square wave
"""
from __future__ import annotations
import subprocess, sys, time

COMMON=[
    sys.executable, "tools/capture_buffers.py",
    "--active-channels", "1",
    "--a3", "0F",
    "--range", "03",
]

RUNS=[
    ([], "f6-repeat-control-1"),
    (["--reference-f6"], "f6-repeat-f6-1"),
    (["--reference-f6"], "f6-repeat-f6-2"),
    (["--reference-f6"], "f6-repeat-f6-3"),
    ([], "f6-repeat-control-2"),
]

def main():
    for i,(extra,tag) in enumerate(RUNS,1):
        cmd=COMMON+extra+["--tag",tag]
        print(f"\nRUN {i}/{len(RUNS)}:", " ".join(cmd), flush=True)
        subprocess.run(cmd,check=True)
        time.sleep(0.5)
    print("\nF6 reproducibility sequence complete.")
    print("Zip captures/*_f6-repeat-* and upload them.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
