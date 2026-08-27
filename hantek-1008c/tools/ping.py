#!/usr/bin/env python3
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hantek1008c import Hantek1008C,HantekUSBError
from hantek1008c.transport import hex_bytes

def main():
    print('Opening Hantek 1008C 0783:5725...')
    try:
        with Hantek1008C(logger_path='captures/transactions.jsonl') as scope:
            print('Claimed interface 0')
            command=bytes.fromhex('F3')
            print(f'TX endpoint 0x02: {hex_bytes(command)}')
            tx=scope.transact(command,read_timeout_ms=250)
            print(f'TX complete: {len(command)} byte(s)')
            if tx.timed_out:
                print('No IN response within 250 ms.')
            else:
                print(f'RX endpoint 0x81: {len(tx.rx or b"")} byte(s)')
                print(f'RX data: {hex_bytes(tx.rx or b"")}')
            print()
            if tx.rx==command:
                print('F3 probe completed successfully (echo confirmed).'); return 0
            print('F3 transaction completed, but reply was not an exact echo.'); return 5
    except HantekUSBError as exc:
        print(f'ERROR: {exc}',file=sys.stderr); return 4
if __name__=='__main__': raise SystemExit(main())
