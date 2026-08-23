#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c.analysis import analyze_periodicity
from hantek1008c.decode import decode_buffers


def parse_args():
    p = argparse.ArgumentParser(
        description="Compare Hantek 1008C captures and periodicity."
    )
    p.add_argument("captures", nargs="+", help="capture JSON files")
    return p.parse_args()


def resolve(meta_path: Path, stored: str) -> Path:
    p = Path(stored)
    if p.exists():
        return p
    candidate = meta_path.parent / p.name
    if candidate.exists():
        return candidate
    raise FileNotFoundError(stored)


def active_channel(decoded):
    results = [analyze_periodicity(ch) for ch in decoded.channels]
    # Driven channel should have the largest AC activity.
    idx = max(range(len(results)), key=lambda i: results[i].rms_ac)
    return idx, results


def main():
    args = parse_args()

    print(
        "capture".ljust(34),
        "A3".rjust(4),
        "active".rjust(7),
        "span".rjust(6),
        "rms_ac".rjust(9),
        "period".rjust(8),
        "corr".rjust(7),
        "event spacings",
    )

    for capture_name in args.captures:
        meta_path = Path(capture_name)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        p2 = resolve(meta_path, meta["buffer02"]["file"])
        p3 = resolve(meta_path, meta["buffer03"]["file"])
        decoded = decode_buffers(p2.read_bytes(), p3.read_bytes())

        active_idx, results = active_channel(decoded)
        r = results[active_idx]

        cfg = meta.get("resolved_configuration", {})
        a3 = cfg.get("a3_hex", "?")
        period = (
            str(r.dominant_period_samples)
            if r.dominant_period_samples is not None else "-"
        )
        corr = (
            f"{r.dominant_corr:.3f}"
            if r.dominant_corr is not None else "-"
        )
        spacings = ",".join(str(x) for x in r.event_spacings[:8]) or "-"

        print(
            meta_path.name[:34].ljust(34),
            str(a3).rjust(4),
            f"CH{active_idx+1}".rjust(7),
            str(r.span).rjust(6),
            f"{r.rms_ac:.3f}".rjust(9),
            period.rjust(8),
            corr.rjust(7),
            spacings,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
