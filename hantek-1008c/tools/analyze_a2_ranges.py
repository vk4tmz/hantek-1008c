#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c.offline import estimate_delta_center, square_sample_rate
from hantek1008c.vertical import REFERENCE_VSCALE_BY_A2, reference_volts_per_delta_count

def load(jf: Path):
    m=json.loads(jf.read_text())
    def resolve(entry):
        p=Path(entry["file"])
        if p.exists(): return p
        local=jf.parent/p.name
        if local.exists(): return local
        raise FileNotFoundError(p)
    b=resolve(m["buffer02"]).read_bytes()+resolve(m["buffer03"]).read_bytes()
    return m,np.frombuffer(b,dtype="<u2").astype(np.int32)

def transition_areas(words, centers, center):
    d=words.astype(float)-center
    out=[]
    for c0 in centers:
        c=int(round(c0)); s=max(0,c-50); e=min(len(words),c+51)
        idx=np.arange(s,e)
        # local baseline from samples away from the transition
        quiet=np.abs(idx-c)>20
        bias=float(np.median(d[s:e][quiet]))
        central=np.abs(idx-c)<=20
        out.append(float(np.sum((d[s:e]-bias)[central])))
    return out

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("captures",nargs="+")
    ap.add_argument("--frequency-hz",type=float,default=1000.0)
    a=ap.parse_args()
    print("capture | A2 | center | rate | median edge area | ref V/div factor | nominal Vpp from reference scale")
    print("-"*125)
    for name in a.captures:
        jf=Path(name); m,w=load(jf)
        a2=int(m["resolved_configuration"]["a2_ranges_hex"][0],16)
        center=estimate_delta_center(w)
        rate,centers,_,_=square_sample_rate(w,a.frequency_hz)
        areas=transition_areas(w,centers,center)
        med=float(np.median(np.abs(areas))) if areas else float("nan")
        if a2 in REFERENCE_VSCALE_BY_A2:
            vf=REFERENCE_VSCALE_BY_A2[a2]
            vpp=med*reference_volts_per_delta_count(a2)
            tail=f"{vf:g} | {vpp:.3f} V"
        else:
            tail="UNSUPPORTED | n/a"
        print(f"{jf.name} | {a2:02X} | {center:4d} | {rate:9.0f} | {med:16.1f} | {tail}")

if __name__=="__main__":
    main()
