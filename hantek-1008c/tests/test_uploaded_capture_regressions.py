from pathlib import Path
import json, re, hashlib
import numpy as np
from hantek1008c.offline import estimate_delta_center, square_sample_rate

FIX=Path(__file__).parent/"fixtures"

def load(jf):
    m=json.loads(jf.read_text())
    d=jf.parent
    b2=d/Path(m["buffer02"]["file"]).name
    b3=d/Path(m["buffer03"]["file"]).name
    return m,np.frombuffer(b2.read_bytes()+b3.read_bytes(),dtype="<u2").astype(np.int32)

def test_a2_centers_and_horizontal_timing():
    expected={"00":2005,"03":2005,"01":1975,"02":1985,"04":1985}
    seen=set()
    for jf in sorted((FIX/"a2_1khz").glob("*capture.json")):
        m,w=load(jf)
        a2=m["resolved_configuration"]["a2_ranges_hex"][0]
        seen.add(a2)
        assert estimate_delta_center(w)==expected[a2]
        rate,centers,_,_=square_sample_rate(w,1000)
        assert rate is not None
        assert 2_350_000 <= rate <= 2_450_000
    assert seen==set(expected)

def test_a3_square_rates():
    expected={"11":800_000,"10":800_000,"0F":2_400_000,"0E":2_400_000}
    for jf in sorted((FIX/"a3_1khz").glob("*capture.json")):
        m,w=load(jf)
        a3=m["resolved_configuration"]["a3_hex"]
        # Historical A3 corpus was acquired at A2=03 with center ~2001.
        rate,centers,_,_=square_sample_rate(w,1000,center=2001,threshold=8)
        assert rate is not None
        assert abs(rate-expected[a3]) <= expected[a3]*0.03

def test_sine_fundamentals_and_normalized_amplitude():
    fs=2_400_400.0
    amps=[]
    for jf in sorted((FIX/"sine_2k_8k").glob("*capture.json")):
        m,w=load(jf)
        f=int(re.search(r"sine-(\d+)khz",m["tag"]).group(1))*1000
        n=np.arange(len(w)); t=n/fs
        # For sine data, reject rare encoding discontinuities around the acquisition median.
        # This is deliberately separate from square-edge center estimation.
        med=float(np.median(w))
        mad=float(np.median(np.abs(w-med))) or 1.0
        mask=np.abs(w-med) <= max(8.0, 8.0*mad)
        X=np.column_stack([np.ones(mask.sum()),
                           np.sin(2*np.pi*f*t[mask]),
                           np.cos(2*np.pi*f*t[mask])])
        beta=np.linalg.lstsq(X,w[mask],rcond=None)[0]
        deriv_amp=float(np.hypot(beta[1],beta[2]))
        integ_amp=deriv_amp/(2*np.pi*f/fs)
        amps.append((f,integ_amp))
        assert integ_amp > 90
    vals=[a for _,a in amps]
    assert max(vals)/min(vals) < 1.15
