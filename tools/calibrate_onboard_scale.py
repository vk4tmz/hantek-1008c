#!/usr/bin/env python3
"""Explicitly estimate/save per-device voltage scale from onboard reference."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession
from hantek1008c.calibration import (
    DEFAULT_VALIDATION_TRIGGERED_ACQUISITIONS, calibration_path, estimate_onboard_reference_scale,
    load_zero_calibration, replace_voltage_scale, save_zero_calibration,
)
from hantek1008c.vertical import nominal_volts_per_count

def parse_range(v: str) -> int:
    r=int(v,16)
    if r not in (2,3):
        raise argparse.ArgumentTypeError("onboard 2 Vp-p scale calibration supports A2 02 or 03; A2 01 clips")
    return r

def main() -> int:
    ap=argparse.ArgumentParser(description="Estimate Hantek 1008C V/count from nominal onboard 1 kHz / 2 Vp-p square reference.")
    ap.add_argument('--channel',type=int,default=1,choices=range(1,9))
    ap.add_argument('--range',dest='range_id',type=parse_range,default=0x03)
    ap.add_argument('--triggered-acquisitions',type=int,default=DEFAULT_VALIDATION_TRIGGERED_ACQUISITIONS)
    ap.add_argument('--expected-vpp',type=float,default=2.0)
    ap.add_argument('--save-scale',action='store_true',help='replace the stored nominal scale; otherwise report only')
    ap.add_argument('--yes',action='store_true')
    args=ap.parse_args()
    if args.triggered_acquisitions < 1: ap.error('--triggered-acquisitions must be >= 1')
    if not args.yes:
        input(f"Connect CH{args.channel} to the onboard 1 kHz / nominal {args.expected_vpp:g} Vp-p reference.\nPress Enter when ready... ")
    cfg=DirectADCConfig(channel=args.channel,a3=0x0F,range_id=args.range_id)
    try:
        with Hantek1008C() as scope:
            cid=scope.connection_id
            old=load_zero_calibration(cid,args.channel,args.range_id)
            if old is None:
                print(f"ERROR: no stored zero calibration for {cid} CH{args.channel} A2={args.range_id:02X}",file=sys.stderr); return 5
            sess=DirectADCSession(scope,cfg); sess.initialize()
            frames=[sess.acquire_words() for _ in range(args.triggered_acquisitions)]
    except HantekUSBError as exc:
        print(f"ERROR: {exc}",file=sys.stderr); return 4
    scale,span=estimate_onboard_reference_scale(frames,args.expected_vpp)
    nominal=nominal_volts_per_count(args.range_id)
    print(f"Device: {cid}")
    print(f"CH{args.channel} A2={args.range_id:02X}: plateau span={span:.3f} counts")
    print(f"Reference nominal scale: {nominal:.9g} V/count")
    print(f"Measured working scale: {scale:.9g} V/count")
    print(f"Difference from nominal: {(scale/nominal-1)*100:+.2f}%")
    if not args.save_scale:
        print("Report only; calibration.ini was not modified. Use --save-scale to persist explicitly.")
        return 0
    source=f"onboard_nominal_{args.expected_vpp:g}Vpp_square"
    new=replace_voltage_scale(old,scale,source)
    path=save_zero_calibration(new)
    print(f"Saved: {path}")
    print(f"scale_source={source}")
    print("zero_adc was preserved unchanged.")
    return 0
if __name__=='__main__': raise SystemExit(main())
