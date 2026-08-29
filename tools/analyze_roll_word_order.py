#!/usr/bin/env python3
"""Waveform-agnostic word-order analysis for diagnostic C7/C8 ROLL rows.

The CH1-only C7/C8 ROLL transport is framed as 4-byte rows.  This tool treats
those rows neutrally as two little-endian 12-bit words and compares continuity
at the two alternating boundaries:

    within row:          word0[n] -> word1[n]
    across row boundary: word1[n] -> word0[n+1]

It also reports the same-position row steps word0[n] -> word0[n+1] and
word1[n] -> word1[n+1].  No waveform recognition, smoothing, thresholding,
interpolation, integration, detrending, or automatic semantic classification is
performed.

Input may be either a capture_roll_adc.py metadata JSON or a raw
*_roll-transport.bin file.  When metadata JSON is supplied, the referenced raw
transport path is resolved relative to the metadata file if necessary.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics


def percentile_nearest(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def metrics(values: list[int]) -> dict:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean_abs_delta": statistics.mean(values),
        "median_abs_delta": statistics.median(values),
        "p90_abs_delta": percentile_nearest(values, 0.90),
        "max_abs_delta": max(values),
        "zero_count": sum(v == 0 for v in values),
        "le1_count": sum(v <= 1 for v in values),
    }


def correlation(xs: list[int], ys: list[int]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = statistics.mean(xs)
    my = statistics.mean(ys)
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sx * sy)


def rows_from_raw(raw: bytes) -> list[tuple[int, int]]:
    return [
        (
            int.from_bytes(raw[i:i + 2], "little") & 0x0FFF,
            int.from_bytes(raw[i + 2:i + 4], "little") & 0x0FFF,
        )
        for i in range(0, len(raw) - 3, 4)
    ]


def load_capture(path: Path) -> tuple[bytes, dict]:
    if path.suffix.lower() == ".bin":
        return path.read_bytes(), {"transport_file": str(path)}

    document = json.loads(path.read_text(encoding="utf-8"))
    raw_name = document.get("roll_transport_file")
    if not raw_name:
        raise ValueError("ROLL capture JSON has no roll_transport_file")

    raw_path = Path(raw_name)
    if not raw_path.is_absolute():
        # capture_roll_adc.py normally records captures/<name>.bin while the
        # metadata itself also lives in captures/.  First try the recorded path
        # exactly as written (for invocation from the project root), then the
        # metadata directory with only the basename.
        if not raw_path.exists():
            raw_path = path.parent / raw_path.name
    if not raw_path.exists():
        raise ValueError(f"ROLL transport file not found: {raw_path}")
    return raw_path.read_bytes(), document


def analyze(raw: bytes) -> dict:
    rows = rows_from_raw(raw)
    if len(rows) < 2:
        raise ValueError("need at least two complete ROLL rows")

    within = [abs(w1 - w0) for w0, w1 in rows]
    across = [abs(rows[i + 1][0] - rows[i][1]) for i in range(len(rows) - 1)]
    word0_step = [abs(rows[i + 1][0] - rows[i][0]) for i in range(len(rows) - 1)]
    word1_step = [abs(rows[i + 1][1] - rows[i][1]) for i in range(len(rows) - 1)]

    within_mean = statistics.mean(within)
    across_mean = statistics.mean(across)

    return {
        "raw_bytes": len(raw),
        "complete_rows": len(rows),
        "trailing_bytes": len(raw) % 4,
        "within_word0_to_word1": metrics(within),
        "across_word1_to_next_word0": metrics(across),
        "word0_to_next_word0": metrics(word0_step),
        "word1_to_next_word1": metrics(word1_step),
        "across_to_within_mean_abs_delta_ratio": (
            None if within_mean == 0 else across_mean / within_mean
        ),
        "corr_word0_word1_same_row": correlation(
            [r[0] for r in rows], [r[1] for r in rows]
        ),
        "corr_word1_next_word0": correlation(
            [rows[i][1] for i in range(len(rows) - 1)],
            [rows[i + 1][0] for i in range(len(rows) - 1)],
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path,
                        help="capture_roll_adc.py metadata JSON or raw ROLL transport .bin")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    try:
        raw, metadata = load_capture(args.capture)
        report = analyze(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc

    report.update({
        "a3_hex": metadata.get("a3_hex"),
        "historical_row_rate": metadata.get("sample_rate"),
        "source": str(args.capture),
    })

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    a3 = report.get("a3_hex") or "??"
    row_rate = report.get("historical_row_rate")
    rate_text = f" historical_row_rate={row_rate:g}/s" if isinstance(row_rate, (int, float)) else ""
    print(f"=== C7/C8 ROLL word-order adjacency A3={a3}{rate_text} ===")
    print(f"raw_bytes={report['raw_bytes']} rows={report['complete_rows']} tail={report['trailing_bytes']}B")
    for label, key in [
        ("within  w0[n] -> w1[n]", "within_word0_to_word1"),
        ("across  w1[n] -> w0[n+1]", "across_word1_to_next_word0"),
        ("rowstep w0[n] -> w0[n+1]", "word0_to_next_word0"),
        ("rowstep w1[n] -> w1[n+1]", "word1_to_next_word1"),
    ]:
        m = report[key]
        print(
            f"{label}: n={m['count']} mean|d|={m['mean_abs_delta']:.6g} "
            f"median={m['median_abs_delta']:.6g} p90={m['p90_abs_delta']} "
            f"max={m['max_abs_delta']} zero={m['zero_count']} <=1={m['le1_count']}"
        )
    ratio = report["across_to_within_mean_abs_delta_ratio"]
    print(f"across/within mean-|delta| ratio={ratio:.6g}" if ratio is not None else "across/within ratio=undefined")
    print(f"corr(w0[n],w1[n])={report['corr_word0_word1_same_row']}")
    print(f"corr(w1[n],w0[n+1])={report['corr_word1_next_word0']}")
    print("Interpretation is intentionally not automated; compare the two alternating adjacency classes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
