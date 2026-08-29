#!/usr/bin/env python3
"""Waveform-agnostic adjacency analysis for official C9/CA Scan rows.

The official Scan transport is framed as neutral 4-byte rows containing two
little-endian 12-bit values, word0 and word1.  This tool does not assign either
word a device meaning.  It compares numerical continuity at the two alternating
boundaries in the raw interleaved stream:

    within row:          word0[n] -> word1[n]
    across row boundary: word1[n] -> word0[n+1]

If the words are consecutive observations of one stream, the two boundary
classes should have similar change statistics for a sufficiently varying input.
If they are two representations of one observation, within-row changes would
normally be systematically smaller than cross-row changes.  The tool reports
measurements only; it deliberately applies no waveform-dependent threshold or
classification.
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


def raw_from_result(result: dict) -> bytes:
    parts = []
    for packet in result.get("ca_packets", []):
        if packet.get("c9_class") != "packet-prefix":
            continue
        observed_hex = packet.get("observed_hex")
        if observed_hex:
            parts.append(bytes.fromhex(observed_hex))
    if not parts:
        raise ValueError("JSON contains no steady-state CA observed_hex payloads")
    return b"".join(parts)


def rows_from_raw(raw: bytes) -> list[tuple[int, int]]:
    return [
        (
            int.from_bytes(raw[i:i+2], "little") & 0x0FFF,
            int.from_bytes(raw[i+2:i+4], "little") & 0x0FFF,
        )
        for i in range(0, len(raw) - 3, 4)
    ]


def analyze(result: dict) -> dict:
    raw = raw_from_result(result)
    rows = rows_from_raw(raw)
    if len(rows) < 2:
        raise ValueError("need at least two complete candidate rows")

    within = [abs(w1 - w0) for w0, w1 in rows]
    across = [abs(rows[i + 1][0] - rows[i][1]) for i in range(len(rows) - 1)]
    word0_step = [abs(rows[i + 1][0] - rows[i][0]) for i in range(len(rows) - 1)]
    word1_step = [abs(rows[i + 1][1] - rows[i][1]) for i in range(len(rows) - 1)]

    within_mean = statistics.mean(within)
    across_mean = statistics.mean(across)
    ratio = None if within_mean == 0 else across_mean / within_mean

    return {
        "profile": result.get("profile"),
        "a3_hex": result.get("a3_hex"),
        "official_time_div": result.get("official_time_div"),
        "raw_bytes": len(raw),
        "complete_candidate_rows": len(rows),
        "trailing_bytes": len(raw) % 4,
        "within_word0_to_word1": metrics(within),
        "across_word1_to_next_word0": metrics(across),
        "word0_to_next_word0": metrics(word0_step),
        "word1_to_next_word1": metrics(word1_step),
        "across_to_within_mean_abs_delta_ratio": ratio,
        "corr_word0_word1_same_row": correlation([r[0] for r in rows], [r[1] for r in rows]),
        "corr_word1_next_word0": correlation(
            [rows[i][1] for i in range(len(rows) - 1)],
            [rows[i + 1][0] for i in range(len(rows) - 1)],
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_json", type=Path)
    parser.add_argument("--profile", help="analyze only one profile name, e.g. 1c")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    document = json.loads(args.capture_json.read_text())
    results = document.get("results")
    if not isinstance(results, list):
        raise SystemExit("not an official Scan probe JSON: missing results[]")

    selected = [r for r in results if args.profile is None or r.get("profile") == args.profile]
    if not selected:
        raise SystemExit(f"profile {args.profile!r} not found")

    reports = [analyze(r) for r in selected]
    if args.json:
        print(json.dumps(reports, indent=2))
        return 0

    for report in reports:
        print(f"=== Scan word-order adjacency A3={report['a3_hex']} ({report['official_time_div']}) ===")
        print(f"raw_bytes={report['raw_bytes']} rows={report['complete_candidate_rows']} tail={report['trailing_bytes']}B")
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
