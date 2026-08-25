from pathlib import Path
import json, re
import numpy as np
from hantek1008c.analysis import reconstruct_continuous_delta

FIX=Path(__file__).parent/"fixtures"/"sine_2k_8k"

def load(jf):
    m=json.loads(jf.read_text())
    d=jf.parent
    b=(d/Path(m["buffer02"]["file"]).name).read_bytes()+(d/Path(m["buffer03"]["file"]).name).read_bytes()
    return m,np.frombuffer(b,dtype="<u2").astype(float)

def corr_at_frequency(y,f,fs=2_400_400.0):
    y=np.asarray(y,float)
    t=np.arange(len(y))/fs
    X=np.column_stack([np.sin(2*np.pi*f*t),np.cos(2*np.pi*f*t)])
    beta=np.linalg.lstsq(X,y,rcond=None)[0]
    fit=X@beta
    yc=y-y.mean(); fc=fit-fit.mean()
    return float(np.dot(yc,fc)/(np.linalg.norm(yc)*np.linalg.norm(fc)))

def test_continuous_reconstruction_recovers_uploaded_sines():
    found=[]
    for jf in sorted(FIX.glob("*capture.json")):
        m,w=load(jf)
        f=int(re.search(r"sine-(\d+)khz",m["tag"]).group(1))*1000
        y,_=reconstruct_continuous_delta(w)
        c=corr_at_frequency(y,f)
        found.append((f,c))
        assert c > 0.75, (f,c)
    assert [f for f,_ in found] == [2000,4000,6000,8000]
