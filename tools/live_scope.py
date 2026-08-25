#!/usr/bin/env python3
"""Experimental live viewer for the reverse-engineered Hantek 1008C.

The device is opened and configured once. Each frame re-arms the acquisition,
reads buffers 02/03, reconstructs the selected channel, and updates one
Matplotlib window. Vertical units are decoder counts, NOT volts.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import numpy as np
    import matplotlib.pyplot as plt
except ImportError as exc:
    raise SystemExit("live_scope.py requires numpy and matplotlib") from exc

from hantek1008c.transport import Hantek1008C, HantekUSBError
from hantek1008c.decode import decode_buffers
from hantek1008c.analysis import reconstruct_thresholded_delta, reconstruct_continuous_delta, normalize_reconstructed_waveform

SAMPLE_RATES = {
    0x11: 800_000.0,
    0x10: 800_000.0,
    0x0F: 2_400_000.0,
    0x0E: 2_400_000.0,
}

def byte_value(s):
    try:
        v=int(s,16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected hexadecimal byte, e.g. 0F or 03") from exc
    if not 0 <= v <= 255:
        raise argparse.ArgumentTypeError("byte must be 00..FF")
    return v

def args():
    p=argparse.ArgumentParser()
    p.add_argument("--channel", type=int, required=True, choices=range(1,9))
    p.add_argument("--a3", type=byte_value, default=0x0F)
    p.add_argument("--range", dest="a2", type=byte_value, default=0x03)
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--delay-ms", type=int, default=5,
                   help="delay between re-arm commands; default 5 ms")
    p.add_argument("--refresh-ms", type=int, default=30,
                   help="minimum GUI pause between frames")
    p.add_argument("--raw", action="store_true",
                   help="plot raw 12-bit words instead of reconstructed waveform")
    p.add_argument("--reconstruction", choices=["continuous","square"], default="continuous",
                   help="waveform reconstruction mode; continuous preserves small sine-wave deltas (default), square suppresses small deltas for square-wave viewing")
    p.add_argument("--no-trigger", action="store_true",
                   help="do not align reconstructed trace on a rising midpoint crossing")
    return p.parse_args()

def transact(scope,payload,timeout):
    t=scope.transact(payload,read_timeout_ms=timeout)
    if t.timed_out:
        raise HantekUSBError(f"{payload.hex(' ').upper()}: timeout")
    return t.rx or b""

def send(scope,payload,timeout,delay):
    transact(scope,payload,timeout)
    if delay:
        time.sleep(delay/1000.0)

def query_size(scope,selector,timeout):
    b=transact(scope,bytes([0xC6,selector]),timeout)
    if len(b)!=2:
        raise HantekUSBError(f"C6 {selector:02X}: expected 2-byte size, got {len(b)}")
    return int.from_bytes(b,"big")

def read_buffer(scope,selector,size,timeout):
    out=bytearray()
    packets=(size+63)//64
    for _ in range(packets):
        scope.write(bytes([0xA6,selector]),timeout_ms=timeout)
        b=scope.read(size=64,timeout_ms=timeout)
        if len(b)!=64:
            raise HantekUSBError(f"A6 {selector:02X}: short packet {len(b)}")
        out.extend(b)
    return bytes(out[:size])

def configure(scope,ch,a3,a2,timeout,delay):
    aa=[0]*8
    aa[ch-1]=1
    ranges=[a2]*8
    # Known-good project startup, with one active lane.
    startup=[
        bytes.fromhex("B9 01 BF 04 00 00"), bytes.fromhex("B7 00"),
        bytes.fromhex("BB 08 00"), b"\xB0", b"\xF3", b"\xB5", b"\xB6",
        b"\xE5", b"\xF7", b"\xF8", b"\xFA", b"\xF5",
        bytes([0xA0,1]), bytes([0xAA]+aa), bytes([0xA3,a3]),
        bytes.fromhex("C1 00 00"), bytes.fromhex("A7 00 00"),
        bytes.fromhex("AC 00 00"),
    ]
    for cmd in startup:
        send(scope,cmd,timeout,delay)
    return ranges

def acquire(scope,ranges,timeout,delay):
    # Re-arm only; do not replay full initialization every frame.
    for cmd in [
        b"\xF3",
        bytes([0xA2]+ranges),
        bytes.fromhex("A4 01"),
        b"\xC0", b"\xC2",
        bytes.fromhex("A5 5A"), bytes.fromhex("A5 5A"),
    ]:
        send(scope,cmd,timeout,delay)
    n2=query_size(scope,2,timeout)
    b2=read_buffer(scope,2,n2,timeout)
    n3=query_size(scope,3,timeout)
    b3=read_buffer(scope,3,n3,timeout)
    return b2,b3

def trigger_align(y):
    if len(y)<32:
        return y
    a=np.asarray(y,float)
    lo=np.percentile(a,20); hi=np.percentile(a,80)
    mid=(lo+hi)/2
    start=max(1,len(a)//10)
    stop=min(len(a)-1,len(a)//2)
    cross=np.where((a[start-1:stop-1] < mid) & (a[start:stop] >= mid))[0]
    if not len(cross):
        return a
    idx=int(cross[0]+start)
    target=len(a)//4
    return np.roll(a,target-idx)

def main():
    a=args()
    fs=SAMPLE_RATES.get(a.a3)
    if fs is None:
        raise SystemExit(f"A3={a.a3:02X} has no validated sample-rate mapping; use 11,10,0F,0E")

    plt.ion()
    fig,ax=plt.subplots(figsize=(12,6))
    line,=ax.plot([],[],lw=1)
    ax.grid(True,alpha=.3)
    ax.set_xlabel("Time (ms)")
    ylabel="Raw 12-bit word" if a.raw else "Normalized decoder counts (not volts)"
    ax.set_ylabel(ylabel)
    title=ax.set_title("")
    status=ax.text(.01,.98,"",transform=ax.transAxes,va="top",ha="left")
    fig.canvas.manager.set_window_title(f"Hantek 1008C - CH{a.channel}")
    plt.show(block=False)

    frame=0
    t0=time.monotonic()
    try:
        with Hantek1008C() as scope:
            ranges=configure(scope,a.channel,a.a3,a.a2,a.timeout_ms,a.delay_ms)
            while plt.fignum_exists(fig.number):
                b2,b3=acquire(scope,ranges,a.timeout_ms,a.delay_ms)
                dec=decode_buffers(b2,b3,active_channels=[a.channel])
                raw=np.asarray(dec.channels[0],dtype=float)

                if a.raw:
                    y=raw
                    zero=float(statistics.median(raw))
                else:
                    if a.reconstruction == "square":
                        rec,zero=reconstruct_thresholded_delta(raw.tolist())
                    else:
                        rec,zero=reconstruct_continuous_delta(raw.tolist())
                    norm=normalize_reconstructed_waveform(
                        rec,measured_rate=fs,reference_rate=800_000.0)
                    y=np.asarray(norm.values,float)
                    if not a.no_trigger:
                        y=trigger_align(y)

                x=np.arange(len(y))/fs*1000.0
                line.set_data(x,y)
                ax.set_xlim(x[0],x[-1] if len(x)>1 else 1)
                if len(y):
                    lo,hi=np.percentile(y,[1,99])
                    pad=max((hi-lo)*.15,1.0)
                    ax.set_ylim(lo-pad,hi+pad)

                frame+=1
                elapsed=max(time.monotonic()-t0,1e-6)
                fps=frame/elapsed
                title.set_text(
                    f"Hantek 1008C  CH{a.channel}   A2={a.a2:02X}   A3={a.a3:02X}   "
                    f"{fs/1e6:.3f} MS/s   {len(raw)} samples   recon={a.reconstruction}")
                status.set_text(
                    f"capture {frame}   {fps:.1f} frame/s   delta centre≈{zero:.2f}")
                fig.canvas.draw_idle()
                fig.canvas.flush_events()
                plt.pause(max(a.refresh_ms,1)/1000.0)
    except KeyboardInterrupt:
        pass
    except HantekUSBError as exc:
        print(f"USB ERROR: {exc}",file=sys.stderr)
        return 4
    finally:
        plt.close("all")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
