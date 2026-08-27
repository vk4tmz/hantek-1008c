from __future__ import annotations
import numpy as np

def estimate_delta_center(words):
    """Estimate acquisition-local delta zero from the modal raw word."""
    a=np.asarray(words)
    vals,counts=np.unique(a,return_counts=True)
    return int(vals[np.argmax(counts)])

def cluster_indices(indices, gap=20):
    indices=list(map(int,indices))
    if not indices: return []
    out=[[indices[0]]]
    for x in indices[1:]:
        if x-out[-1][-1] <= gap: out[-1].append(x)
        else: out.append([x])
    return out

def major_transition_centers(words, center=None, threshold=None, gap=20):
    a=np.asarray(words,dtype=np.int32)
    if center is None: center=estimate_delta_center(a)
    d=a-center
    if threshold is None:
        # High quantile adapts to A2 gain while floor keeps low-gain A2=00/03 usable.
        threshold=max(8.0, float(np.percentile(np.abs(d),99))*0.60)
    idx=np.flatnonzero(np.abs(d)>=threshold)
    groups=cluster_indices(idx,gap=gap)
    return [float(np.mean(g)) for g in groups], int(center), float(threshold)

def square_sample_rate(words, tone_hz=1000.0, **kw):
    centers,center,threshold=major_transition_centers(words,**kw)
    if len(centers)<3: return None,centers,center,threshold
    spacing=float(np.median(np.diff(centers)))
    return 2.0*spacing*float(tone_hz),centers,center,threshold
