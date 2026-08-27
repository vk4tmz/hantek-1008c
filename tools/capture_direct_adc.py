#!/usr/bin/env python3
"""Canonical direct-ADC capture utility for the Hantek 1008C."""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hantek1008c.acquire import DirectADCConfig, DirectADCSession
from hantek1008c import Hantek1008C, HantekUSBError


def parse_byte(value):
    result = int(value, 16)
    if not 0 <= result <= 255:
        raise argparse.ArgumentTypeError("hex byte must be 00..FF")
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--a3", type=parse_byte, default=0x0F)
    p.add_argument("--range", dest="range_id", type=parse_byte, default=0x03)
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--tag", default="direct-adc")
    args = p.parse_args()

    out = Path("captures")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{args.tag}"
    txlog = out / f"{base}_capture-transactions.jsonl"
    cfg = DirectADCConfig(args.channel, args.a3, args.range_id, args.timeout_ms)

    try:
        with Hantek1008C(logger_path=txlog) as scope:
            session = DirectADCSession(scope, cfg)
            calibration = session.initialize()
            words = session.acquire_words()
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    raw = b"".join(int(v & 0x0FFF).to_bytes(2, "little") for v in words)
    buf = out / f"{base}_buffer03.bin"
    meta = out / f"{base}_capture.json"
    buf.write_bytes(raw)
    metadata = {
        "timestamp_utc": stamp,
        "tag": args.tag,
        "mode": "canonical-direct-adc",
        "channel": args.channel,
        "a3_hex": f"{args.a3:02X}",
        "sample_rate": cfg.sample_rate,
        "range_hex": f"{args.range_id:02X}",
        "buffer02_bytes": 0,
        "buffer03_bytes": len(raw),
        "word_count": len(words),
        "raw_word_summary": {
            "min": min(words) if words else None,
            "max": max(words) if words else None,
            "mean": sum(words) / len(words) if words else None,
        },
        "calibration_passes": calibration,
        "transaction_log": str(txlog),
    }
    meta.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Capture complete: {meta}")
    print(f"Direct ADC: {len(words)} samples @ {cfg.sample_rate / 1e6:.3f} MS/s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
