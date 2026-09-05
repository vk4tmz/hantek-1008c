#!/usr/bin/env python3
"""Diagnostic-only probe of the official Hantek Windows Scan Mode transport.

Windows USBPcap evidence captured on 2026-08-29 established that the official
application enters Scan Mode at 500 ms/div:

    200 ms/div -> A3 19 -> triggered C6/A6 family
    500 ms/div -> A3 1A -> Scan Mode C9/CA family
    1 s/div    -> A3 1B -> Scan Mode C9/CA family

The official Scan Mode capture continued to use A4 01.  Linux reproduction at
A3=1A then established two different C9 cases.  In steady state, C9 values
8..14 were followed by a 64-byte CA reply whose C9-sized prefix contained data
and whose remainder was zero padding.  An initial C9=2992 was consumed by one
CA transaction and is therefore quarantined as an oversize/startup condition;
it is not interpreted as FIFO depth or as a multi-CA byte count.

This tool is deliberately diagnostic.  It does NOT modify the canonical
DirectADCSession acquisition path or the existing A4 02 + C7/C8 ROLL lab path.
It stores raw bytes exactly as received (after removing CA USB padding) and
reports simple little-endian 12-bit word statistics and neutral candidate
4-byte row word0/word1 statistics only as observational views.  It performs no smoothing, thresholding, interpolation, integration,
detrending, or waveform-specific processing.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import DirectADCConfig, DirectADCSession, _transact


from hantek1008c.scan_protocol import (
    OFFICIAL_SCAN_PROFILES,
    ScanCandidateRowFramer,
    ca_padding_is_zero,
    ca_valid_prefix,
    classify_c9_count,
    decode_c9_available,
    le_u12_candidate_rows,
    le_u12_words,
    scan_ch1_observations,
    scan_observation_rate,
)
from hantek1008c.multichannel import mask_for_channels, observed_windows_width


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tx(scope, payload: bytes, timeout_ms: int) -> dict:
    started = time.perf_counter_ns()
    reply = _transact(scope, payload, timeout_ms)
    ended = time.perf_counter_ns()
    return {
        "tx_hex": payload.hex(" ").upper(),
        "rx_hex": reply.hex(" ").upper(),
        "elapsed_ms": (ended - started) / 1_000_000.0,
    }


def read_one_ca(scope, timeout_ms: int) -> bytes:
    """Perform exactly one CA transaction and return the complete USB packet."""
    scope.write(b"\xCA", timeout_ms=timeout_ms)
    packet = scope.read(size=64, timeout_ms=timeout_ms)
    if len(packet) != 64:
        raise HantekUSBError(f"CA: expected 64-byte packet, got {len(packet)}")
    return packet


def parse_channel_counts(value: str) -> tuple[int, ...]:
    if value == "all-desc":
        return tuple(range(8, 0, -1))
    try:
        counts = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("channel counts must be comma-separated integers 1..8") from exc
    if not counts or any(count < 1 or count > 8 for count in counts):
        raise argparse.ArgumentTypeError("channel counts must contain values in 1..8")
    if len(set(counts)) != len(counts):
        raise argparse.ArgumentTypeError("channel counts must not contain duplicates")
    return counts


def parse_channel_sets(value: str) -> tuple[tuple[int, ...], ...]:
    sets = []
    try:
        for group in value.split(";"):
            channels = tuple(
                sorted(int(part.strip()) for part in group.split(",") if part.strip())
            )
            if not channels or any(channel < 1 or channel > 8 for channel in channels):
                raise ValueError
            if len(set(channels)) != len(channels):
                raise ValueError
            sets.append(channels)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "channel sets must look like '1,8;2,5;1,2,5,8'"
        ) from exc
    if not sets or len(set(sets)) != len(sets):
        raise argparse.ArgumentTypeError("channel sets must be non-empty and unique")
    return tuple(sets)


def lane_statistics(values: list[int]) -> dict:
    return {
        "samples": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "span": (max(values) - min(values)) if values else None,
        "mean": (sum(values) / len(values)) if values else None,
    }


def multichannel_candidate_views(words: list[int], logical_count: int) -> dict:
    """Expose competing structural views without choosing a Scan layout."""
    width = observed_windows_width(logical_count)

    complete_word_rows = len(words) // width
    word_interleaved = [
        [words[row * width + lane] for row in range(complete_word_rows)]
        for lane in range(width)
    ]

    paired_row_words = 2 * width
    complete_paired_rows = len(words) // paired_row_words
    paired = [[] for _ in range(width)]
    for row in range(complete_paired_rows):
        base = row * paired_row_words
        for lane in range(width):
            paired[lane].extend(words[base + 2 * lane : base + 2 * lane + 2])

    return {
        "physical_width_candidate": width,
        "dummy_lane_candidate": width if width > logical_count else None,
        "word_interleaved": {
            "complete_rows": complete_word_rows,
            "tail_words": len(words) % width,
            "lanes": [lane_statistics(lane) for lane in word_interleaved],
        },
        "paired_observations_per_channel": {
            "complete_rows": complete_paired_rows,
            "tail_words": len(words) % paired_row_words,
            "lanes": [lane_statistics(lane) for lane in paired],
        },
    }


def run_profile(profile_name: str, args, stamp: str, channels: tuple[int, ...]) -> dict:
    profile = OFFICIAL_SCAN_PROFILES[profile_name]
    logical_count = len(channels)
    aa = mask_for_channels(channels)
    cfg = DirectADCConfig(
        channel=1,
        a3=profile["a3"],
        range_id=args.range_id,
        timeout_ms=args.usb_timeout_ms,
    )

    channel_tag = "-".join(str(channel) for channel in channels)
    stem = f"{stamp}_official-scan-channels-{channel_tag}-a3-{profile_name}"
    logger = args.output_dir / f"{stem}_transactions.jsonl"
    with Hantek1008C(logger_path=logger) as scope:
        session = DirectADCSession(scope, cfg)
        calibration = session.initialize()

        setup = [
            tx(scope, b"\xF3", args.usb_timeout_ms),
            tx(scope, bytes([0xA0, logical_count]), args.usb_timeout_ms),
            tx(scope, bytes([0xAA, *aa]), args.usb_timeout_ms),
            tx(scope, bytes([0xA2] + [args.range_id] * 8), args.usb_timeout_ms),
            tx(scope, bytes([0xA3, profile["a3"]]), args.usb_timeout_ms),
            tx(scope, profile["ac"], args.usb_timeout_ms),
            tx(scope, b"\xF3", args.usb_timeout_ms),
            tx(scope, bytes.fromhex("A4 01"), args.usb_timeout_ms),
            tx(scope, bytes.fromhex("E4 01"), args.usb_timeout_ms),
            tx(scope, bytes.fromhex("E6 01"), args.usb_timeout_ms),
            tx(scope, b"\xC0", args.usb_timeout_ms),
        ]

        # The official Windows boundary capture waited ~1.87 s between C0 and
        # C2 at both A3=1A and A3=1B while repeatedly observing A5.  Reproduce
        # that behaviour as evidence-derived timing, but make it configurable.
        pre_c2 = []
        deadline = time.monotonic() + args.pre_c2_ms / 1000.0
        while time.monotonic() < deadline:
            f3 = tx(scope, b"\xF3", args.usb_timeout_ms)
            a5 = tx(scope, bytes.fromhex("A5 5A"), args.usb_timeout_ms)
            state = int(a5["rx_hex"].split()[-1], 16) if a5["rx_hex"] else None
            pre_c2.append({"f3": f3, "a5": a5, "a5_state": state})
            if args.pre_c2_poll_ms:
                time.sleep(args.pre_c2_poll_ms / 1000.0)

        c2 = tx(scope, b"\xC2", args.usb_timeout_ms)

        raw = bytearray()
        oversize_raw = bytearray()
        row_framer = ScanCandidateRowFramer()
        framed_candidate_rows = []
        ca_packets = []
        polls = []
        scan_started_ns = time.perf_counter_ns()
        deadline = time.monotonic() + args.capture_s
        while time.monotonic() < deadline:
            f3 = tx(scope, b"\xF3", args.usb_timeout_ms)
            a5 = tx(scope, bytes.fromhex("A5 5A"), args.usb_timeout_ms)
            c9_start = time.perf_counter_ns()
            c9_reply = _transact(scope, b"\xC9", args.usb_timeout_ms)
            c9_end = time.perf_counter_ns()
            try:
                available = decode_c9_available(c9_reply)
            except ValueError as exc:
                raise HantekUSBError(str(exc)) from exc
            row = {
                "f3": f3,
                "a5": a5,
                "c9_rx_hex": c9_reply.hex(" ").upper(),
                "c9_elapsed_ms": (c9_end - c9_start) / 1_000_000.0,
                "available_bytes": available,
            }
            if available:
                c9_class = classify_c9_count(available)
                ca_start_ns = time.perf_counter_ns()
                packet = read_one_ca(scope, args.usb_timeout_ms)
                ca_end_ns = time.perf_counter_ns()

                packet_row = {
                    "c9_before": available,
                    "c9_class": c9_class,
                    "packet_hex": packet.hex(" ").upper(),
                    "ca_start_offset_s": (ca_start_ns - scan_started_ns) / 1_000_000_000.0,
                    "ca_end_offset_s": (ca_end_ns - scan_started_ns) / 1_000_000_000.0,
                }

                if c9_class == "packet-prefix":
                    try:
                        observed = ca_valid_prefix(packet, available)
                        padding_zero = ca_padding_is_zero(packet, available)
                    except ValueError as exc:
                        raise HantekUSBError(str(exc)) from exc
                    raw.extend(observed)
                    newly_framed = row_framer.feed(observed)
                    framed_candidate_rows.extend(newly_framed)
                    packet_row.update({
                        "observed_bytes": len(observed),
                        "observed_hex": observed.hex(" ").upper(),
                        "padding_zero": padding_zero,
                        "even_payload_bytes": (len(observed) % 2 == 0),
                        "candidate_rows_emitted": len(newly_framed),
                        "candidate_row_carry_bytes_after": len(row_framer.carry),
                    })
                    row["ca_observed_bytes"] = len(observed)
                    row["ca_padding_zero"] = padding_zero
                else:
                    # Preserve the complete returned CA packet separately but do
                    # not mix it into the steady-state sample stream.  The 2992
                    # startup observation proved that C9 > 64 does not have the
                    # same one-packet prefix semantics as steady-state C9.
                    oversize_raw.extend(packet)
                    packet_row.update({
                        "observed_bytes": 0,
                        "quarantined": True,
                    })
                    row["ca_observed_bytes"] = 0
                    row["ca_quarantined"] = True

                # Retain the immediate post-CA C9 observation as evidence.  In
                # the 2026-08-29 A3=1A run it was normally zero, but once was 4;
                # therefore it is recorded, not used as a drain/continuation rule.
                post_start = time.perf_counter_ns()
                post_reply = _transact(scope, b"\xC9", args.usb_timeout_ms)
                post_end = time.perf_counter_ns()
                try:
                    post_count = decode_c9_available(post_reply)
                except ValueError as exc:
                    raise HantekUSBError(str(exc)) from exc

                packet_row["c9_after_one_ca"] = post_count
                ca_packets.append(packet_row)
                row["c9_class"] = c9_class
                row["post_ca_c9_rx_hex"] = post_reply.hex(" ").upper()
                row["post_ca_c9_count"] = post_count
                row["post_ca_c9_elapsed_ms"] = (post_end - post_start) / 1_000_000.0
            polls.append(row)
            if args.poll_ms:
                time.sleep(args.poll_ms / 1000.0)

        scan_ended_ns = time.perf_counter_ns()
        connection_id = scope.connection_id

    raw_bytes = bytes(raw)
    raw_path = args.output_dir / f"{stem}.bin"
    raw_path.write_bytes(raw_bytes)
    oversize_bytes = bytes(oversize_raw)
    oversize_path = None
    if oversize_bytes:
        oversize_path = args.output_dir / f"{stem}_oversize-ca.bin"
        oversize_path.write_bytes(oversize_bytes)
    words = le_u12_words(raw_bytes)
    candidate_rows = framed_candidate_rows
    # Cross-check the stateful transport-boundary framer against the equivalent
    # whole-buffer observational view.  This is an invariant check only; the
    # stateful framer is the source of the row stream reported below.
    whole_buffer_candidate_rows = le_u12_candidate_rows(raw_bytes)
    if candidate_rows != whole_buffer_candidate_rows:
        raise HantekUSBError("stateful Scan row framer disagrees with whole-buffer framing")
    candidate_word0 = [row[0] for row in candidate_rows]
    candidate_word1 = [row[1] for row in candidate_rows]
    # The two-observations-per-row interpretation is proven only for one
    # enabled channel.  Multi-channel runs retain the same neutral 4-byte view
    # for comparison but must not label it as CH1 data.
    ch1_observations = (
        scan_ch1_observations(candidate_rows) if logical_count == 1 else []
    )
    candidate_4byte_rows = len(candidate_rows)
    candidate_4byte_tail_bytes = len(row_framer.carry)
    scan_elapsed_s = (scan_ended_ns - scan_started_ns) / 1_000_000_000.0
    steady_even = all(
        p.get("even_payload_bytes", True)
        for p in ca_packets
        if p["c9_class"] == "packet-prefix"
    )
    steady_padding_zero = all(
        p.get("padding_zero", False)
        for p in ca_packets
        if p["c9_class"] == "packet-prefix"
    )

    return {
        "profile": profile_name,
        "logical_channels": list(channels),
        "logical_channel_count": logical_count,
        "a0": logical_count,
        "aa": list(aa),
        "a3_hex": f"{profile['a3']:02X}",
        "official_time_div": profile["time_div"],
        "official_ac_hex": profile["ac"].hex(" ").upper(),
        "transport": "official-scan-a4-01-c9-ca",
        "device": connection_id,
        "range_a2": f"{args.range_id:02X}",
        "pre_c2_ms_requested": args.pre_c2_ms,
        "setup": setup,
        "pre_c2_poll_count": len(pre_c2),
        "pre_c2_polls": pre_c2,
        "c2": c2,
        "scan_poll_count": len(polls),
        "scan_polls": polls,
        "ca_packet_count": len(ca_packets),
        "ca_packets": ca_packets,
        "steady_state_ca_packet_count": sum(p["c9_class"] == "packet-prefix" for p in ca_packets),
        "oversize_ca_packet_count": sum(p["c9_class"] == "oversize" for p in ca_packets),
        "steady_state_padding_all_zero": steady_padding_zero,
        "steady_state_payloads_all_even_bytes": steady_even,
        "scan_elapsed_s": scan_elapsed_s,
        "raw_file": str(raw_path),
        "raw_bytes": len(raw_bytes),
        "raw_sha256": digest(raw_bytes),
        "oversize_ca_file": str(oversize_path) if oversize_path else None,
        "oversize_ca_bytes": len(oversize_bytes),
        "oversize_ca_sha256": digest(oversize_bytes) if oversize_bytes else None,
        "observational_le_u12_words": len(words),
        "observational_word_throughput_per_s": (len(words) / scan_elapsed_s) if scan_elapsed_s else None,
        "candidate_4byte_rows": candidate_4byte_rows,
        "candidate_4byte_tail_bytes": candidate_4byte_tail_bytes,
        "candidate_row_framer_carry_hex": row_framer.carry.hex(" ").upper(),
        "candidate_row_framer_total_input_bytes": row_framer.total_input_bytes,
        "candidate_row_framer_total_rows": row_framer.total_rows,
        "candidate_4byte_row_throughput_per_s": (candidate_4byte_rows / scan_elapsed_s) if scan_elapsed_s else None,
        "decoded_ch1_observation_count": (
            len(ch1_observations) if logical_count == 1 else None
        ),
        "decoded_ch1_observation_throughput_per_s": (
            scan_observation_rate(candidate_4byte_rows / scan_elapsed_s)
            if scan_elapsed_s and logical_count == 1 else None
        ),
        "decoded_ch1_min": min(ch1_observations) if ch1_observations else None,
        "decoded_ch1_max": max(ch1_observations) if ch1_observations else None,
        "decoded_ch1_span": (max(ch1_observations) - min(ch1_observations)) if ch1_observations else None,
        "candidate_word0_count": len(candidate_word0),
        "candidate_word0_min": min(candidate_word0) if candidate_word0 else None,
        "candidate_word0_max": max(candidate_word0) if candidate_word0 else None,
        "candidate_word0_span": (max(candidate_word0) - min(candidate_word0)) if candidate_word0 else None,
        "candidate_word1_count": len(candidate_word1),
        "candidate_word1_min": min(candidate_word1) if candidate_word1 else None,
        "candidate_word1_max": max(candidate_word1) if candidate_word1 else None,
        "candidate_word1_span": (max(candidate_word1) - min(candidate_word1)) if candidate_word1 else None,
        "candidate_word_pair_absdiff_mean": (
            sum(abs(a - b) for a, b in candidate_rows) / len(candidate_rows)
            if candidate_rows else None
        ),
        "candidate_word_pair_absdiff_max": (
            max(abs(a - b) for a, b in candidate_rows) if candidate_rows else None
        ),
        "observational_u12_min": min(words) if words else None,
        "observational_u12_max": max(words) if words else None,
        "observational_u12_span": (max(words) - min(words)) if words else None,
        "multichannel_candidate_views": multichannel_candidate_views(words, logical_count),
        "initialization_calibration": calibration,
        "transaction_log": str(logger),
    }


def select_profiles(selection: str) -> tuple[str, ...]:
    if selection == "both":
        return ("1a", "1b")
    if selection == "next-four":
        return ("1e", "1f", "20", "21")
    if selection == "all":
        return tuple(OFFICIAL_SCAN_PROFILES)
    if selection not in OFFICIAL_SCAN_PROFILES:
        raise ValueError(f"unknown official Scan profile selection: {selection}")
    return (selection,)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Diagnostic reproduction of official Hantek C9/CA Scan Mode"
    )
    profile_choices = tuple(OFFICIAL_SCAN_PROFILES) + ("both", "next-four", "all")
    ap.add_argument(
        "--profile", choices=profile_choices, default="1a",
        help=(
            "official Scan Mode profile from 1a=500ms/div through 28=20000s/div; "
            "'both' runs 1a+1b, 'next-four' runs 1e+1f+20+21, and 'all' runs "
            "every Scan profile (default: 1a)"
        ),
    )
    ap.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    ap.add_argument(
        "--channel-counts", type=parse_channel_counts, default=(1,),
        metavar="LIST",
        help="contiguous enabled-channel counts, e.g. 8,7,6 or all-desc (default: 1)",
    )
    ap.add_argument(
        "--channel-sets", type=parse_channel_sets,
        metavar="SETS",
        help=(
            "explicit semicolon-separated channel masks, e.g. "
            "'1,8;2,5;1,2,5,8'; overrides --channel-counts"
        ),
    )
    ap.add_argument("--pre-c2-ms", type=float, default=1870.0)
    ap.add_argument("--pre-c2-poll-ms", type=float, default=10.0)
    ap.add_argument("--capture-s", type=float, default=2.0)
    ap.add_argument("--poll-ms", type=float, default=5.0)
    ap.add_argument("--usb-timeout-ms", type=int, default=1000)
    ap.add_argument("--retry-timeout-s", type=float, default=15.0)
    ap.add_argument("--retry-interval-s", type=float, default=0.5)
    ap.add_argument("--output-dir", type=Path, default=Path("captures"))
    args = ap.parse_args()

    if args.range_id not in (1, 2, 3):
        ap.error("--range must be 01, 02, or 03")
    if min(args.pre_c2_ms, args.pre_c2_poll_ms, args.poll_ms) < 0 or args.capture_s <= 0:
        ap.error("timing values must be non-negative and --capture-s must be > 0")
    if args.retry_timeout_s < 0 or args.retry_interval_s <= 0:
        ap.error("--retry-timeout-s must be >= 0 and --retry-interval-s must be > 0")

    profiles = select_profiles(args.profile)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print("Diagnostic only: canonical direct ADC and C7/C8 ROLL paths are unchanged.")
    print("Official Windows evidence: A3=1A..28 Scan region, A4=01, C9/CA family.")
    print("Linux evidence: steady C9<=64 is a valid CA prefix length; C9>64 is quarantined.\n")

    results = []
    channel_sets = args.channel_sets or tuple(
        tuple(range(1, logical_count + 1))
        for logical_count in args.channel_counts
    )
    experiments = [
        (channels, profile)
        for channels in channel_sets
        for profile in profiles
    ]
    for index, (channels, profile) in enumerate(experiments, 1):
        logical_count = len(channels)
        channel_names = ",".join(f"CH{channel}" for channel in channels)
        print("=" * 72)
        print(f"Scan experiment {index}/{len(experiments)}")
        print(f"  - Enabled channels: {channel_names}")
        print(f"  - Candidate physical width: {observed_windows_width(logical_count)}")
        print(f"  - A3={profile.upper()} ({OFFICIAL_SCAN_PROFILES[profile]['time_div']})\n")
        started = time.monotonic()
        deadline = started + args.retry_timeout_s
        attempt = 0
        while True:
            attempt += 1
            try:
                row = run_profile(profile, args, stamp, channels)
                if attempt > 1:
                    print("[USB recovery]")
                    print("  - Recovery: SUCCESS")
                    print(f"  - Ready after: {time.monotonic() - started:.1f} seconds")
                    print(f"  - Full experiment attempts: {attempt}\n")
                break
            except HantekUSBError as exc:
                elapsed = time.monotonic() - started
                if attempt == 1:
                    print("[USB recovery]")
                    print(f"  - Initial experiment failed: {exc}")
                    print(f"  - Retry window: {args.retry_timeout_s:.1f} seconds")
                    print(f"  - Retry interval: {args.retry_interval_s:.1f} seconds")
                else:
                    print(f"  - Retry {attempt - 1} at +{elapsed:.1f}s: {exc}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    row = {
                        "profile": profile,
                        "logical_channel_count": logical_count,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                    print("  - Recovery: FAILED\n")
                    break
                time.sleep(min(args.retry_interval_s, remaining))
            except Exception as exc:
                row = {
                    "profile": profile,
                    "logical_channel_count": logical_count,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                print(f"  ERROR: {row['error']}")
                break
        if row.get("status") != "error":
            print("Capture result")
            print(f"  - C9 polls: {row['scan_poll_count']}")
            print(f"  - CA packets: {row['ca_packet_count']}")
            print(f"  - Steady bytes: {row['raw_bytes']}")
            print(f"  - Observed words: {row['observational_le_u12_words']}")
            print(f"  - Word throughput: {row['observational_word_throughput_per_s']:.3f} words/s")
            print(f"  - Quarantined startup CA packets: {row['oversize_ca_packet_count']}")
            if logical_count == 1:
                print(f"  - Proven CH1 observations: {row['decoded_ch1_observation_count']}")
                print(f"  - Proven CH1 rate: {row['decoded_ch1_observation_throughput_per_s']:.3f} Sa/s")
            views = row["multichannel_candidate_views"]
            print("\nCandidate layout tails")
            print(f"  - Word-interleaved: {views['word_interleaved']['tail_words']} word(s)")
            print(f"  - Paired observations/channel: {views['paired_observations_per_channel']['tail_words']} word(s)\n")
        results.append(row)

    out = args.output_dir / f"{stamp}_official-scan.json"
    out.write_text(json.dumps({
        "format": "hantek1008c-official-scan-probe-v7",
        "timestamp_utc": stamp,
        "canonical_acquisition_modified": False,
        "source_evidence": "official Windows USBPcap 2026-08-29",
        "results": results,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
