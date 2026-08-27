#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path
import statistics
import struct

from pathlib import Path as _PathForImport
import sys
sys.path.insert(0, str(_PathForImport(__file__).resolve().parents[1]))
from hantek1008c.analysis import analyze_periodicity
from hantek1008c.decode import decode_buffers


def parse_args():
    p = argparse.ArgumentParser(
        description="First-pass structural analysis of Hantek 1008C captured buffers."
    )
    p.add_argument(
        "capture_json",
        nargs="?",
        help="capture metadata JSON; default: newest captures/*_capture.json",
    )
    p.add_argument(
        "--preview",
        type=int,
        default=32,
        help="number of decoded values to preview (default: 32)",
    )
    return p.parse_args()


def newest_capture():
    files = sorted(Path("captures").glob("*_capture.json"))
    if not files:
        raise SystemExit("ERROR: no captures/*_capture.json found")
    return files[-1]


def resolve_file(meta_path: Path, stored: str) -> Path:
    p = Path(stored)
    if p.exists():
        return p
    # Metadata currently stores a path relative to project cwd.
    candidate = meta_path.parent / p.name
    if candidate.exists():
        return candidate
    raise FileNotFoundError(stored)


def stats(values):
    vals = list(values)
    if not vals:
        return {}
    mean = statistics.fmean(vals)
    rms_ac = math.sqrt(statistics.fmean((x - mean) ** 2 for x in vals))
    return {
        "count": len(vals),
        "min": min(vals),
        "max": max(vals),
        "mean": mean,
        "rms_ac": rms_ac,
        "span": max(vals) - min(vals),
    }


def print_stats(label, values):
    s = stats(values)
    print(
        f"{label:24s} "
        f"n={s['count']:5d} "
        f"min={s['min']:6.0f} "
        f"max={s['max']:6.0f} "
        f"span={s['span']:6.0f} "
        f"mean={s['mean']:9.2f} "
        f"rms_ac={s['rms_ac']:9.2f}"
    )


def u16le(data):
    n = len(data) // 2
    return list(struct.unpack("<" + "H" * n, data[:n * 2]))


def u16be(data):
    n = len(data) // 2
    return list(struct.unpack(">" + "H" * n, data[:n * 2]))


def s16le(data):
    n = len(data) // 2
    return list(struct.unpack("<" + "h" * n, data[:n * 2]))


def nibble12_le(words):
    return [w & 0x0FFF for w in words]


def analyze_buffer(name, data, preview):
    print()
    print(f"=== {name} ===")
    print(f"bytes: {len(data)}")
    print(f"first {min(64, len(data))} bytes:")
    print(" ".join(f"{b:02X}" for b in data[:64]))

    le = u16le(data)
    be = u16be(data)
    sle = s16le(data)
    le12 = nibble12_le(le)

    print()
    print_stats("u8", data)
    print_stats("u16 little-endian", le)
    print_stats("u16 big-endian", be)
    print_stats("s16 little-endian", sle)
    print_stats("u12 from LE low 12b", le12)

    print()
    print(f"u16 LE preview ({min(preview, len(le))}):")
    print(" ".join(str(v) for v in le[:preview]))
    print(f"u12 LE preview ({min(preview, len(le12))}):")
    print(" ".join(str(v) for v in le12[:preview]))

    # Test an 8-channel frame interpretation for both bytes and 16-bit words.
    print()
    print("8-way lane statistics, byte-interleaved:")
    for ch in range(8):
        print_stats(f"lane {ch+1}", data[ch::8])

    print()
    print("8-way lane statistics, u16-LE interleaved:")
    for ch in range(8):
        print_stats(f"lane {ch+1}", le[ch::8])

    print()
    print("8-way lane statistics, u12(low12)-interleaved:")
    for ch in range(8):
        print_stats(f"lane {ch+1}", le12[ch::8])


def main():
    args = parse_args()
    meta_path = Path(args.capture_json) if args.capture_json else newest_capture()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    p2 = resolve_file(meta_path, meta["buffer02"]["file"])
    p3 = resolve_file(meta_path, meta["buffer03"]["file"])

    b2 = p2.read_bytes()
    b3 = p3.read_bytes()

    print(f"capture: {meta_path}")
    print(f"buffer02: {p2} ({len(b2)} bytes)")
    print(f"buffer03: {p3} ({len(b3)} bytes)")
    print(f"combined: {len(b2) + len(b3)} bytes")

    analyze_buffer("buffer02", b2, args.preview)
    analyze_buffer("buffer03", b3, args.preview)

    combined = b2 + b3
    print()
    print("=== Combined 02+03 ===")
    print(f"bytes: {len(combined)}")
    print_stats("u8", combined)

    le = u16le(combined)
    le12 = nibble12_le(le)
    print_stats("u16 little-endian", le)
    print_stats("u12 from LE low 12b", le12)

    print()
    print("Combined 8-way u12(low12) lane statistics:")
    for ch in range(8):
        print_stats(f"lane {ch+1}", le12[ch::8])

    decoded = decode_buffers(b2, b3)
    print()
    print("=== Per-channel periodicity ===")
    for ch_index, samples in enumerate(decoded.channels, start=1):
        result = analyze_periodicity(samples)
        period = (
            str(result.dominant_period_samples)
            if result.dominant_period_samples is not None else "-"
        )
        corr = (
            f"{result.dominant_corr:.3f}"
            if result.dominant_corr is not None else "-"
        )
        events = ",".join(str(i) for i in result.event_indices[:12]) or "-"
        spacings = ",".join(str(i) for i in result.event_spacings[:12]) or "-"
        print(
            f"CH{ch_index}: span={result.span:4d} "
            f"rms_ac={result.rms_ac:7.3f} "
            f"period={period:>4s} samples corr={corr:>6s} "
            f"events=[{events}] spacings=[{spacings}]"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
