#!/usr/bin/env python3
"""Probe the official Hantek 1008C Normal-style trigger wait state.

Protocol-lab diagnostic only.  Windows USBPcap evidence from the Trigger Sweep
shows the official application arms with A4 01 + C0, polls F3/A5 while A5=00,
and does *not* immediately send C2.  C2 appears in Auto-style paths after a
host-side wait and transitions the device into A5=01 before completion.

This probe therefore asks one narrow question: with a known crossing signal and
AB inside the waveform, can A5 reach ready state 2/3 after C0 *without* C2?
If not, C2 is sent only as cleanup/forced completion so the device is left in a
known readable state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import (
    DirectADCConfig,
    DirectADCSession,
    _query_buffer,
    _transact,
    decode_direct_u12,
)


def capture_summary(words: list[int]) -> dict:
    if len(words) < 2:
        return {}
    diff = [b - a for a, b in zip(words, words[1:])]
    center = (len(words) - 1) / 2.0
    rise_i = max(range(len(diff)), key=diff.__getitem__)
    fall_i = min(range(len(diff)), key=diff.__getitem__)
    return {
        "sample_count": len(words),
        "min_adc": min(words),
        "max_adc": max(words),
        "span_adc": max(words) - min(words),
        "mean_adc": statistics.fmean(words),
        "strongest_rising": {
            "index": rise_i,
            "delta": diff[rise_i],
            "distance_from_center": rise_i - center,
        },
        "strongest_falling": {
            "index": fall_i,
            "delta": diff[fall_i],
            "distance_from_center": fall_i - center,
        },
    }


def poll_a5_until(scope, timeout_ms: int, wait_ms: float, poll_ms: float) -> tuple[bool, int | None, int, float, list[dict]]:
    started = time.perf_counter()
    deadline = started + wait_ms / 1000.0
    rows: list[dict] = []
    polls = 0
    last_state = None
    while time.perf_counter() < deadline:
        _transact(scope, b"\xF3", timeout_ms)
        reply = _transact(scope, bytes.fromhex("A5 5A"), timeout_ms)
        polls += 1
        state = reply[-1] if reply else None
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if state != last_state:
            rows.append({"elapsed_ms": elapsed_ms, "state": state})
            last_state = state
        if state in (2, 3):
            return True, int(state), polls, elapsed_ms, rows
        time.sleep(poll_ms / 1000.0)
    return False, (int(last_state) if last_state is not None else None), polls, (time.perf_counter() - started) * 1000.0, rows


def drain(scope, timeout_ms: int) -> list[int]:
    return decode_direct_u12((
        _query_buffer(scope, 2, timeout_ms),
        _query_buffer(scope, 3, timeout_ms),
    ))


def main() -> int:
    p = argparse.ArgumentParser(description="Hantek 1008C official C0/A5 trigger-wait probe")
    p.add_argument("--captures", type=int, default=6)
    p.add_argument("--wait-ms", type=float, default=1200.0,
                   help="wait after C0 for hardware-trigger completion before cleanup C2")
    p.add_argument("--poll-ms", type=float, default=15.0,
                   help="F3/A5 polling interval, matching the official Windows cadence approximately")
    p.add_argument("--timeout-ms", type=int, default=1000)
    p.add_argument("--trigger-level", type=lambda s: int(s, 16), default=0x0860)
    p.add_argument("--c1-raw", type=int, choices=(0, 1), default=0)
    p.add_argument("--ground-control", action="store_true",
                   help="grounded no-crossing control; changes only operator instructions/metadata")
    p.add_argument("--tag", default="trigger-wait-1khz")
    args = p.parse_args()
    if args.captures < 1:
        p.error("--captures must be >= 1")
    if not 0 <= args.trigger_level <= 0xFFFF:
        p.error("--trigger-level must be 0000..FFFF")

    print("============================================================")
    print(" Hantek 1008C official C0/A5 hardware-trigger wait probe")
    if args.ground_control:
        physical_condition = "CH1 grounded"
        print(" PHYSICAL CONDITION: GROUND CH1")
        print(" Keep CH1 grounded for the entire probe.")
    else:
        physical_condition = "CH1 connected to 1 kHz square-wave source"
        print(" PHYSICAL CONDITION: CONNECT CH1 TO 1 kHz SQUARE-WAVE SOURCE")
        print(" Keep CH1 connected for the entire probe.")
    print("============================================================")
    print("Official Trigger regime: A3=15 (10 ms/div), C6/A6 buffer family")
    print("Horizontal trigger position: centred AC left/right = 49991/49991")
    print(f"AB={args.trigger_level:04X}; C1 raw=00 {args.c1_raw:02X} ({'rising/+' if args.c1_raw == 0 else 'falling/-'})")
    print("Critical experiment: A4 01 -> C0 -> F3/A5 polling WITHOUT C2")
    print(f"If not ready after {args.wait_ms:.0f} ms, C2 is sent only for forced cleanup.")

    out = Path("captures")
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{stamp}_{args.tag}"
    txlog = out / f"{base}_transactions.jsonl"
    result_path = out / f"{base}.json"

    cfg = DirectADCConfig(
        channel=1,
        a3=0x15,
        range_id=0x03,
        timeout_ms=args.timeout_ms,
        trigger_slope_raw=args.c1_raw,
        trigger_level_adc=args.trigger_level,
    )
    rows = []

    try:
        with Hantek1008C(logger_path=txlog) as scope:
            session = DirectADCSession(scope, cfg)
            session.initialize()

            # Replay the evidence-derived 10 ms/div Trigger configuration after
            # generic initialization.  AC uses the observed centred 10 ms/div
            # partition: u16=0, left=49991, right=49991.
            session._tx(bytes.fromhex("A3 15"))
            session._tx(bytes.fromhex("AC 00 00 00 C3 47 00 C3 47"))
            session.set_trigger_slope_raw(args.c1_raw)
            session.set_trigger_level_adc(args.trigger_level)

            for n in range(1, args.captures + 1):
                _transact(scope, b"\xF3", args.timeout_ms)
                _transact(scope, bytes.fromhex("E4 01"), args.timeout_ms)
                _transact(scope, bytes.fromhex("E6 01"), args.timeout_ms)
                _transact(scope, bytes.fromhex("A4 01"), args.timeout_ms)
                _transact(scope, b"\xC0", args.timeout_ms)

                ready, state, polls, elapsed_ms, state_changes = poll_a5_until(
                    scope, args.timeout_ms, args.wait_ms, args.poll_ms
                )
                forced_cleanup = not ready
                if forced_cleanup:
                    _transact(scope, b"\xC2", args.timeout_ms)
                    cleanup_ready, cleanup_state, cleanup_polls, cleanup_ms, cleanup_changes = poll_a5_until(
                        scope, args.timeout_ms, 1800.0, args.poll_ms
                    )
                    if not cleanup_ready:
                        raise HantekUSBError("cleanup C2 did not produce A5 ready state 2/3")
                    state = cleanup_state
                else:
                    cleanup_polls = 0
                    cleanup_ms = 0.0
                    cleanup_changes = []

                words = drain(scope, args.timeout_ms)
                _transact(scope, bytes.fromhex("E4 01"), args.timeout_ms)
                _transact(scope, bytes.fromhex("E6 01"), args.timeout_ms)

                raw_path = out / f"{base}_{n:02d}_{'hardware' if ready else 'forced'}.bin"
                raw_path.write_bytes(b"".join(v.to_bytes(2, "little") for v in words))
                summary = capture_summary(words)
                row = {
                    "capture": n,
                    "pre_c2_ready": ready,
                    "pre_c2_last_state": state if ready else state_changes[-1]["state"] if state_changes else None,
                    "pre_c2_polls": polls,
                    "pre_c2_elapsed_ms": elapsed_ms,
                    "pre_c2_state_changes": state_changes,
                    "c2_forced_cleanup": forced_cleanup,
                    "cleanup_ready_state": state if forced_cleanup else None,
                    "cleanup_polls": cleanup_polls,
                    "cleanup_elapsed_ms": cleanup_ms,
                    "cleanup_state_changes": cleanup_changes,
                    "raw_file": str(raw_path),
                    **summary,
                }
                rows.append(row)
                r = summary.get("strongest_rising", {})
                f = summary.get("strongest_falling", {})
                print(
                    f"capture={n:02d} preC2={'READY' if ready else 'WAITING'} "
                    f"state={row['pre_c2_last_state']} polls={polls} wait={elapsed_ms:.1f}ms "
                    f"path={'HARDWARE' if ready else 'C2-FORCED'} "
                    f"adc={summary.get('min_adc')}..{summary.get('max_adc')} "
                    f"rise=i{r.get('index')} d{r.get('delta'):+} "
                    f"fall=i{f.get('index')} d{f.get('delta'):+}"
                )
    except HantekUSBError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4

    hardware_count = sum(1 for r in rows if r["pre_c2_ready"])
    result = {
        "timestamp_utc": stamp,
        "purpose": "test evidence-derived Normal-style C0/A5 hardware-trigger wait without immediate C2",
        "physical_condition": physical_condition,
        "channel": 1,
        "a3_hex": "15",
        "ui_time_div": "10 ms/div",
        "range_hex": "03",
        "ac_hex": "00 00 00 C3 47 00 C3 47",
        "ac_left": 49991,
        "ac_right": 49991,
        "trigger_level_hex": f"{args.trigger_level:04X}",
        "c1_raw": args.c1_raw,
        "pre_c2_wait_ms": args.wait_ms,
        "poll_interval_ms": args.poll_ms,
        "hardware_ready_count": hardware_count,
        "capture_count": len(rows),
        "transaction_log": str(txlog),
        "captures": rows,
        "interpretation_policy": (
            "A5 ready before C2 is evidence for genuine hardware-trigger completion. "
            "C2 is used only after the diagnostic wait expires, as forced cleanup; "
            "C1 polarity was subsequently resolved from Windows UI chronology: 00=+/rising, 01=-/falling."
        ),
    }
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    print("------------------------------------------------------------")
    print(f"Hardware-ready before C2: {hardware_count}/{len(rows)}")
    print(f"Results: {result_path}")
    print("Upload the result JSON and matching *_hardware.bin / *_forced.bin files if requested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
