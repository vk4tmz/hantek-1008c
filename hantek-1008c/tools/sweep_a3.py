#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# Hantek burst-mode A3 uses a 1-2-5 time/div ladder. 0x11 is 500 us/div.
# These adjacent faster values are known-valid members of that ladder.
DEFAULT_A3 = [0x11, 0x10, 0x0F, 0x0E]
A3_NS_PER_DIV = {
    0x11: 500_000,
    0x10: 200_000,
    0x0F: 100_000,
    0x0E: 50_000,
}


def parse_hex_byte(s: str) -> int:
    try:
        value = int(s, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid hex byte: {s}") from exc
    if not 0 <= value <= 0xFF:
        raise argparse.ArgumentTypeError("A3 values must be 00..FF")
    return value


def parse_args():
    p = argparse.ArgumentParser(
        description="Capture CH1-only bursts while stepping known-valid A3 timebase values."
    )
    p.add_argument(
        "--a3-values",
        nargs="+",
        type=parse_hex_byte,
        default=DEFAULT_A3,
        metavar="HEX",
        help="A3 bytes to test (default: 11 10 0F 0E)",
    )
    p.add_argument("--frequency-hz", type=float, default=1000.0,
                   help="known square-wave frequency (default: 1000)")
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9),
                   help="single active/driven channel (default: 1)")
    p.add_argument("--config", default="config/default.toml")
    p.add_argument("--dry-run", action="store_true",
                   help="show capture commands without touching the scope")
    return p.parse_args()


def resolve(meta_path: Path, stored: str) -> Path:
    p = Path(stored)
    if p.exists():
        return p
    q = meta_path.parent / p.name
    if q.exists():
        return q
    raise FileNotFoundError(stored)


def estimate_square_period(samples: list[int], frequency_hz: float):
    # Use the same hardened major-edge detector as the offline analyzer.
    from hantek1008c.analysis import detect_square_edges
    result = detect_square_edges(samples, frequency_hz=frequency_hz)
    span = max(samples) - min(samples) if samples else 0
    return (
        result.period_samples,
        result.sample_rate,
        len(result.edge_indices),
        result.median_half_period,
        span,
    )


def newest_capture_for_tag(before: set[Path], tag: str) -> Path | None:
    candidates = set(Path("captures").glob(f"*_{tag}_capture.json")) - before
    if not candidates:
        candidates = set(Path("captures").glob(f"*_{tag}_capture.json"))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def main():
    args = parse_args()
    tool = Path(__file__).with_name("capture_buffers.py")
    active = str(args.channel)

    results = []
    print("A3 sweep: one channel active, known square-wave timing reference")
    print(f"Driven/active channel: CH{args.channel}; frequency={args.frequency_hz:g} Hz")
    print("Settings: " + " ".join(f"{x:02X}" for x in args.a3_values))
    print()

    for a3 in args.a3_values:
        tag = f"square-{args.frequency_hz:g}hz-1ch-a3-{a3:02x}".replace(".", "p")
        cmd = [
            sys.executable, str(tool),
            "--config", args.config,
            "--active-channels", active,
            "--a3", f"{a3:02X}",
            "--tag", tag,
        ]
        ns = A3_NS_PER_DIV.get(a3)
        human = f" ({ns/1000:g} us/div)" if ns is not None else ""
        print(f"=== A3={a3:02X}{human} ===")
        print("$ " + " ".join(cmd))
        if args.dry_run:
            continue

        before = set(Path("captures").glob(f"*_{tag}_capture.json"))
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            print(f"A3={a3:02X}: CAPTURE FAILED rc={proc.returncode}\n", file=sys.stderr)
            results.append((a3, ns, "FAIL", None, None, None, None, None, None))
            continue

        meta_path = newest_capture_for_tag(before, tag)
        if meta_path is None:
            print(f"A3={a3:02X}: capture completed but metadata file not found\n", file=sys.stderr)
            results.append((a3, ns, "NO-META", None, None, None, None, None, None))
            continue

        from hantek1008c.decode import decode_buffers
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        p2 = resolve(meta_path, meta["buffer02"]["file"])
        p3 = resolve(meta_path, meta["buffer03"]["file"])
        active_channels = meta["resolved_configuration"]["active_channels"]
        dec = decode_buffers(p2.read_bytes(), p3.read_bytes(), active_channels=active_channels)
        lane = dec.channel_ids.index(args.channel)
        samples = dec.channels[lane]
        period, rate, edge_count, half, span = estimate_square_period(samples, args.frequency_hz)
        total_bytes = p2.stat().st_size + p3.stat().st_size
        results.append((a3, ns, "OK", total_bytes, len(samples), period, rate, edge_count, span))

        if rate is None:
            print(f"A3={a3:02X}: {len(samples)} samples/ch, span={span}, edges={edge_count}; rate not measurable")
        else:
            print(f"A3={a3:02X}: {len(samples)} samples/ch, span={span}, edges={edge_count}, "
                  f"period≈{period:.1f} samples => rate≈{rate:,.0f} S/s")
        print()

    if args.dry_run:
        return 0

    print("\nSUMMARY")
    print("A3 | time/div | status | total bytes | samples/ch | period(samples) | measured rate | edges | span")
    print("-" * 105)
    for row in results:
        a3, ns, status, total_bytes, nsamp, period, rate, edges, span = row
        td = f"{ns/1000:g} us" if ns is not None else "?"
        print(f"{a3:02X} | {td:>8} | {status:>7} | "
              f"{str(total_bytes) if total_bytes is not None else '-':>11} | "
              f"{str(nsamp) if nsamp is not None else '-':>10} | "
              f"{f'{period:.1f}' if period is not None else '-':>15} | "
              f"{f'{rate:,.0f}' if rate is not None else '-':>13} | "
              f"{str(edges) if edges is not None else '-':>5} | "
              f"{str(span) if span is not None else '-':>4}")

    print("\nInterpretation: measured rate = 2 × median square-wave edge spacing × known frequency.")
    print("Do not infer a rate from time/div alone; the table reports what the captured waveform actually supports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
