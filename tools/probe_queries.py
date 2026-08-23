#!/usr/bin/env python3
import argparse,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hantek1008c import Hantek1008C,HantekUSBError
from hantek1008c.transport import hex_bytes
DEFAULT_COMMANDS=['B0','B5','B6','E5','F7','F8','FA','F5']

def parse_args():
    p=argparse.ArgumentParser(description='Conservatively probe documented Hantek 1008C query-like commands.')
    p.add_argument('--command',action='append',dest='commands',help='hex command; may be repeated')
    p.add_argument('--timeout-ms',type=int,default=250)
    p.add_argument('--delay-ms',type=int,default=150)
    p.add_argument('--log',default='captures/query-probes.jsonl')
    return p.parse_args()

def main():
    a=parse_args(); commands=a.commands or DEFAULT_COMMANDS
    try:
        with Hantek1008C(logger_path=a.log) as scope:
            print('Hantek 1008C opened; interface 0 claimed.')
            print(f'Logging transactions to {a.log}\n')
            for text in commands:
                try: payload=bytes.fromhex(text)
                except ValueError:
                    print(f'ERROR: invalid hex command {text!r}',file=sys.stderr); return 2
                print(f'TX  {hex_bytes(payload)}')
                tx=scope.transact(payload,read_timeout_ms=a.timeout_ms)
                if tx.timed_out: print(f'RX  <timeout after {a.timeout_ms} ms>')
                else: print(f'RX  {hex_bytes(tx.rx or b"")}')
                print(); time.sleep(a.delay_ms/1000.0)
        return 0
    except HantekUSBError as exc:
        print(f'ERROR: {exc}',file=sys.stderr); return 4
if __name__=='__main__': raise SystemExit(main())
