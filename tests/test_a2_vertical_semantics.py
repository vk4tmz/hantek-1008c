from pathlib import Path
import json
import numpy as np
from hantek1008c.offline import estimate_delta_center, square_sample_rate
from hantek1008c.vertical import (
    REFERENCE_VSCALE_BY_A2,
    parse_range,
    range_description,
    range_name,
    reference_volts_per_delta_count,
)

FIX=Path(__file__).parent/"fixtures"/"a2_1khz"

def load(jf):
    m=json.loads(jf.read_text()); d=jf.parent
    b=(d/Path(m["buffer02"]["file"]).name).read_bytes()+(d/Path(m["buffer03"]["file"]).name).read_bytes()
    return m,np.frombuffer(b,dtype="<u2").astype(np.int32)

def edge_area(words, centers, center):
    d=words.astype(float)-center; vals=[]
    for c0 in centers:
        c=int(round(c0)); s=max(0,c-50); e=min(len(words),c+51); idx=np.arange(s,e)
        bias=float(np.median(d[s:e][np.abs(idx-c)>20]))
        vals.append(float(np.sum((d[s:e]-bias)[np.abs(idx-c)<=20])))
    return float(np.median(np.abs(vals)))

def samples():
    out={}
    for jf in FIX.glob("*capture.json"):
        m,w=load(jf); a2=int(m["resolved_configuration"]["a2_ranges_hex"][0],16)
        rate,centers,_,_=square_sample_rate(w,1000)
        out[a2]=(w,rate,centers,estimate_delta_center(w))
    return out

def test_reference_supported_ids_are_exactly_1_2_3():
    assert set(REFERENCE_VSCALE_BY_A2)=={1,2,3}
    assert reference_volts_per_delta_count(1)==0.0002
    assert reference_volts_per_delta_count(2)==0.00125
    assert reference_volts_per_delta_count(3)==0.01

def test_public_range_names_and_raw_aliases():
    assert [range_name(value) for value in (1, 2, 3)] == [
        "Narrow", "Medium", "Wide"
    ]
    assert range_description(2) == "Medium (A2=02)"
    for alias in ("Medium", "medium", "02", "A2=02", "a2=02"):
        assert parse_range(alias) == 2

def test_supported_a2_02_and_03_are_consistent_with_nominal_2vpp():
    s=samples()
    for a2,lo,hi in [(2,1.7,2.6),(3,1.8,2.9)]:
        w,rate,centers,center=s[a2]
        assert 2_350_000 <= rate <= 2_450_000
        volts=edge_area(w,centers,center)*reference_volts_per_delta_count(a2)
        assert lo <= volts <= hi

def test_a2_01_is_overrange_for_this_nominal_2vpp_fixture():
    w,rate,centers,center=samples()[1]
    volts=edge_area(w,centers,center)*reference_volts_per_delta_count(1)
    assert volts < 1.0

def test_unsupported_alias_like_behaviour_is_preserved_but_not_promoted():
    s=samples()
    area={}
    for a2 in (0,2,3,4):
        w,_,centers,center=s[a2]
        area[a2]=edge_area(w,centers,center)
    assert abs(area[0]/area[3]-1) < 0.12
    assert abs(area[4]/area[2]-1) < 0.12
    assert 0 not in REFERENCE_VSCALE_BY_A2
    assert 4 not in REFERENCE_VSCALE_BY_A2
