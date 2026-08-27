#!/usr/bin/env python3
"""Experimental Hantek 1008C capture following mfg92/hantek1008py burst init.

This is deliberately separate from capture_buffers.py.  It exists to answer one
question: does the fuller public-reference initialization make buffers 02+03
contain direct ADC samples rather than the derivative-looking stream seen in the
minimal path?
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse, json, sys, time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.transport import hex_bytes


def parse_byte(s):
    v=int(s,16)
    if not 0 <= v <= 255: raise argparse.ArgumentTypeError('hex byte required')
    return v


def tx(scope,label,payload,timeout=1000):
    print(f'{label}: TX {hex_bytes(payload)}')
    t=scope.transact(payload,read_timeout_ms=timeout)
    if t.timed_out: raise HantekUSBError(f'{label}: timeout')
    data=t.rx or b''
    print(f'{label}: RX {len(data)} byte(s): {hex_bytes(data)}')
    return data


def read_buffer(scope, selector, size, timeout=1000):
    out=bytearray(); packets=(size+63)//64
    for i in range(packets):
        scope.write(bytes([0xA6,selector]),timeout_ms=timeout)
        b=scope.read(size=64,timeout_ms=timeout)
        if len(b)!=64: raise HantekUSBError(f'A6 {selector:02X}: short read {len(b)}')
        out.extend(b)
    return bytes(out[:size])


def c6a6(scope, selector, timeout=1000):
    r=tx(scope,f'C6-{selector:02X}',bytes([0xC6,selector]),timeout)
    if len(r)!=2: raise HantekUSBError('C6 size response not 2 bytes')
    n=int.from_bytes(r,'big')
    print(f'C6-{selector:02X}: size={n}')
    return read_buffer(scope,selector,n,timeout)


def a5_ready(scope, timeout=1000, tries=20):
    for i in range(tries):
        r=tx(scope,f'A5-{i+1}',bytes.fromhex('A5 5A'),timeout)
        state = r[-1] if r else None
        if state in (2,3):
            print(f'A5 ready state={state} after {i+1} poll(s)')
            return state
        time.sleep(0.002)
    raise HantekUSBError(f'A5 never reached ready state 2/3 in {tries} polls')


def burst(scope, timeout=1000, guards=True):
    tx(scope,'BURST-F3',b'\xF3',timeout)
    if guards:
        tx(scope,'BURST-E4-pre',bytes.fromhex('E4 01'),timeout)
        tx(scope,'BURST-E6-pre',bytes.fromhex('E6 01'),timeout)
    tx(scope,'BURST-A4',bytes.fromhex('A4 01'),timeout)
    time.sleep(0.015)
    tx(scope,'BURST-C0',b'\xC0',timeout)
    tx(scope,'BURST-C2',b'\xC2',timeout)
    a5_ready(scope,timeout)
    b2=c6a6(scope,2,timeout); b3=c6a6(scope,3,timeout)
    if guards:
        tx(scope,'BURST-E4-post',bytes.fromhex('E4 01'),timeout)
        tx(scope,'BURST-E6-post',bytes.fromhex('E6 01'),timeout)
    return b2,b3


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--a3',type=parse_byte,default=0x11,
                    help='target final burst timebase byte; default 11 like mfg92 default')
    ap.add_argument('--range',dest='range_id',type=parse_byte,default=0x03)
    ap.add_argument('--timeout-ms',type=int,default=1000)
    ap.add_argument('--tag',default='mfg92-reference')
    args=ap.parse_args(); timeout=args.timeout_ms

    out=Path('captures'); out.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    base=f'{stamp}_{args.tag}'
    log=out/f'{base}_capture-transactions.jsonl'

    with Hantek1008C(logger_path=log) as scope:
        print('=== mfg92 init1 analogue ===')
        tx(scope,'I1-B0-1',b'\xB0',timeout); time.sleep(0.7)
        tx(scope,'I1-B0-2',b'\xB0',timeout)
        tx(scope,'I1-F3',b'\xF3',timeout)
        # mfg92 set_generator_speed(300000): pulse_length 1200 = 0x000004B0 LE
        tx(scope,'I1-B9',bytes.fromhex('B9 01 B0 04 00 00'),timeout)
        tx(scope,'I1-B7',bytes.fromhex('B7 00'),timeout)
        tx(scope,'I1-BB',bytes.fromhex('BB 08 00'),timeout)
        for label,cmd in [('B5','B5'),('B6','B6'),('E5','E5'),('F7','F7'),('F8','F8'),('FA','FA')]:
            tx(scope,'I1-'+label,bytes.fromhex(cmd),timeout)
        tx(scope,'I1-F5',b'\xF5',timeout)
        tx(scope,'I1-A0-all',bytes.fromhex('A0 08'),timeout)
        tx(scope,'I1-AA-all',bytes.fromhex('AA 01 01 01 01 01 01 01 01'),timeout)
        # mfg92 default ns/div=500000 maps to id 0x11 during init1
        tx(scope,'I1-A3-default',bytes.fromhex('A3 11'),timeout)
        tx(scope,'I1-C1',bytes.fromhex('C1 00 00'),timeout)
        tx(scope,'I1-A7',bytes.fromhex('A7 00 00'),timeout)
        tx(scope,'I1-AC',bytes.fromhex('AC 01 F4 00 09 C5 00 09 C5'),timeout)

        print('=== mfg92 init2 zero-calibration hardware passes ===')
        calibration={}
        for rid in (1,2,3):
            tx(scope,f'I2-F3-r{rid}',b'\xF3',timeout)
            tx(scope,f'I2-A2-r{rid}',bytes([0xA2]+[rid]*8),timeout)
            tx(scope,f'I2-A4-r{rid}',bytes.fromhex('A4 01'),timeout)
            tx(scope,f'I2-C0-r{rid}',b'\xC0',timeout); time.sleep(0.0124)
            tx(scope,f'I2-C2-r{rid}',b'\xC2',timeout)
            a5_ready(scope,timeout)
            cb2=c6a6(scope,2,timeout); cb3=c6a6(scope,3,timeout)
            words=[int.from_bytes((cb2+cb3)[i:i+2],'little') for i in range(0,len(cb2+cb3)-1,2)]
            calibration[str(rid)]={'word_count':len(words),'mean':sum(words)/len(words) if words else None,
                                   'min':min(words) if words else None,'max':max(words) if words else None}
            print(f'cal range {rid}: {calibration[str(rid)]}')

        print('=== mfg92 init3 analogue ===')
        tx(scope,'I3-F6',b'\xF6',timeout); time.sleep(0.2132)
        for label,cmd in [('E5','E5'),('F7','F7'),('F8','F8'),('FA','FA')]:
            tx(scope,'I3-'+label,bytes.fromhex(cmd),timeout)
        tx(scope,'I3-A3-pre',bytes([0xA3,args.a3]),timeout)
        tx(scope,'I3-AC-pre',bytes.fromhex('AC 00 C8 00 02 BD 00 02 BD'),timeout)
        tx(scope,'I3-E4',bytes.fromhex('E4 01'),timeout)
        tx(scope,'I3-E6',bytes.fromhex('E6 01'),timeout)
        tx(scope,'I3-F3',b'\xF3',timeout)
        tx(scope,'I3-A0-ch1',bytes.fromhex('A0 01'),timeout)
        tx(scope,'I3-AA-ch1',bytes.fromhex('AA 01 00 00 00 00 00 00 00'),timeout)
        tx(scope,'I3-A2',bytes([0xA2]+[args.range_id]*8),timeout)
        tx(scope,'I3-A3-final',bytes([0xA3,args.a3]),timeout)
        tx(scope,'I3-C1',bytes.fromhex('C1 00 00'),timeout)
        tx(scope,'I3-A7',bytes.fromhex('A7 00 00'),timeout)
        tx(scope,'I3-AC-final',bytes.fromhex('AC 00 00 00 00 01 00 05 79'),timeout)
        tx(scope,'I3-AB-trigger',bytes.fromhex('AB 08 00'),timeout)
        tx(scope,'I3-E9',b'\xE9',timeout)

        print('=== mfg92 burst ===')
        b2,b3=burst(scope,timeout,guards=True)

    (out/f'{base}_buffer02.bin').write_bytes(b2)
    (out/f'{base}_buffer03.bin').write_bytes(b3)
    raw=b2+b3
    words=[int.from_bytes(raw[i:i+2],'little') for i in range(0,len(raw)-1,2)]
    meta={
        'timestamp_utc':stamp,'tag':args.tag,'mode':'mfg92-reference-full-init-experiment',
        'a3_hex':f'{args.a3:02X}','range_hex':f'{args.range_id:02X}',
        'buffer02_bytes':len(b2),'buffer03_bytes':len(b3),'word_count':len(words),
        'raw_word_summary': {'min':min(words) if words else None,'max':max(words) if words else None,
                             'mean':sum(words)/len(words) if words else None},
        'calibration_passes':calibration,
        'transaction_log':str(log),
    }
    (out/f'{base}_capture.json').write_text(json.dumps(meta,indent=2)+'\n')
    print('Capture complete:', out/f'{base}_capture.json')
    print('Direct raw summary:', meta['raw_word_summary'])
    return 0

if __name__=='__main__':
    raise SystemExit(main())
