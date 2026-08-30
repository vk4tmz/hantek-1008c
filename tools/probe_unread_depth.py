#!/usr/bin/env python3
"""Diagnostic-only map of Hantek 1008C data beyond the C6-reported depth.

The canonical acquisition path is not modified. This lab fully initializes the
scope, arms exactly one direct-ADC acquisition, drains the C6-reported buffers,
then continues issuing A6 03 reads until the requested limit or the device
refuses further transfers.

The probe preserves the nominal triggered, beyond-C6 bytes, and their concatenation
as raw binary files plus a JSON record. It also performs byte-level structural
checks for exact repetition/overlap. No thresholding, smoothing, triggering,
expected-waveform reconstruction, or waveform-specific cleanup is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hantek1008c import Hantek1008C, HantekUSBError
from hantek1008c.acquire import (
    DirectADCConfig,
    DirectADCSession,
    _query_buffer,
    _transact,
    wait_ready_with_polls,
)
from hantek1008c.transport import EP_IN, EP_OUT


def arm_ready(scope, timeout_ms: int):
    phases = []
    for name, payload in (
        ("f3", b"\xF3"),
        ("e4_pre", bytes.fromhex("E4 01")),
        ("e6_pre", bytes.fromhex("E6 01")),
        ("a4", bytes.fromhex("A4 01")),
        ("c0", b"\xC0"),
        ("c2", b"\xC2"),
    ):
        t0 = time.perf_counter_ns()
        reply = _transact(scope, payload, timeout_ms)
        t1 = time.perf_counter_ns()
        phases.append({
            "phase": name,
            "elapsed_us": (t1 - t0) / 1000.0,
            "reply_hex": reply.hex().upper(),
        })
    metrics = {}
    state, polls = wait_ready_with_polls(scope, timeout_ms, metrics=metrics)
    return {"ready_state": state, "ready_polls": polls, "a5": metrics, "phases": phases}


def c6(scope, selector: int, timeout_ms: int):
    t0 = time.perf_counter_ns()
    reply = _transact(scope, bytes([0xC6, selector]), timeout_ms)
    t1 = time.perf_counter_ns()
    if len(reply) != 2:
        raise HantekUSBError(f"C6 {selector:02X}: expected 2 bytes, got {len(reply)}")
    return {
        "selector": selector,
        "reply_hex": reply.hex().upper(),
        "reported_bytes": int.from_bytes(reply, "big"),
        "elapsed_us": (t1 - t0) / 1000.0,
    }


def extra_a6(scope, selector: int, count: int, write_timeout_ms: int, read_timeout_ms: int):
    """Read up to *count* additional 64-byte packets, stopping at first failure."""
    rows = []
    raw = bytearray()
    for idx in range(count):
        w0 = time.perf_counter_ns()
        try:
            scope.write(bytes([0xA6, selector]), timeout_ms=write_timeout_ms)
            w1 = time.perf_counter_ns()
            data = scope.read(size=64, timeout_ms=read_timeout_ms)
            r1 = time.perf_counter_ns()
            raw.extend(data)
            rows.append({
                "probe": idx + 1,
                "write_ok": True,
                "read_ok": True,
                "timed_out": False,
                "length": len(data),
                "write_us": (w1 - w0) / 1000.0,
                "read_us": (r1 - w1) / 1000.0,
                "data_hex": data.hex().upper(),
            })
            if len(data) != 64:
                rows[-1]["short_packet"] = True
                break
        except usb.core.USBTimeoutError as exc:
            r1 = time.perf_counter_ns()
            rows.append({
                "probe": idx + 1,
                "write_ok": True,
                "read_ok": False,
                "timed_out": True,
                "length": 0,
                "elapsed_us": (r1 - w0) / 1000.0,
                "error": str(exc),
                "data_hex": "",
            })
            break
        except HantekUSBError as exc:
            r1 = time.perf_counter_ns()
            rows.append({
                "probe": idx + 1,
                "write_ok": False,
                "read_ok": False,
                "timed_out": False,
                "length": 0,
                "elapsed_us": (r1 - w0) / 1000.0,
                "error": str(exc),
                "data_hex": "",
            })
            break
    return rows, bytes(raw)


def exact_overlap(a: bytes, b: bytes, max_len: int = 4096) -> dict:
    """Find longest exact suffix(a)==prefix(b), capped for cheap diagnostics."""
    lim = min(len(a), len(b), max_len)
    for n in range(lim, 0, -1):
        if a[-n:] == b[:n]:
            return {"bytes": n, "a_offset": len(a) - n, "b_offset": 0}
    return {"bytes": 0, "a_offset": len(a), "b_offset": 0}


def structural_checks(nominal: bytes, extra: bytes) -> dict:
    """Waveform-agnostic exact byte checks for replay/wrap/continuation clues."""
    checks = {
        "nominal_bytes": len(nominal),
        "extra_bytes": len(extra),
        "combined_bytes": len(nominal) + len(extra),
        "extra_equals_nominal_prefix": extra == nominal[:len(extra)] if extra else False,
        "nominal_equals_extra_prefix": nominal == extra[:len(nominal)] if nominal else False,
        "extra_found_in_nominal_at": nominal.find(extra) if extra else -1,
        "nominal_found_in_extra_at": extra.find(nominal) if nominal else -1,
        "suffix_nominal_to_prefix_extra_exact_overlap": exact_overlap(nominal, extra),
    }
    if len(extra) >= len(nominal) and nominal:
        checks["first_nominal_length_of_extra_equals_nominal"] = extra[:len(nominal)] == nominal
    else:
        checks["first_nominal_length_of_extra_equals_nominal"] = False
    if extra:
        checks["extra_all_zero"] = all(v == 0 for v in extra)
        checks["extra_nonzero_bytes"] = sum(1 for v in extra if v != 0)
    else:
        checks["extra_all_zero"] = False
        checks["extra_nonzero_bytes"] = 0
    return checks


def clear_halts(scope) -> dict:
    """Best-effort endpoint-halt recovery after an expected boundary stall."""
    result = {"attempted": False, "in_ok": None, "out_ok": None, "errors": []}
    if getattr(scope, "dev", None) is None:
        return result
    result["attempted"] = True
    for name, ep in (("in", EP_IN), ("out", EP_OUT)):
        try:
            scope.dev.clear_halt(ep)
            result[f"{name}_ok"] = True
        except Exception as exc:  # diagnostic cleanup only
            result[f"{name}_ok"] = False
            result["errors"].append(f"{name}: {exc}")
    return result


def safe_c6(scope, selector: int, timeout_ms: int) -> dict:
    try:
        value = c6(scope, selector, timeout_ms)
        return {"ok": True, "value": value}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def main() -> int:
    p = argparse.ArgumentParser(description="Map Hantek data beyond the C6-reported triggered depth")
    p.add_argument("--channel", type=int, default=1, choices=range(1, 9))
    p.add_argument("--range", dest="range_id", type=lambda s: int(s, 16), default=0x03)
    p.add_argument("--a3", type=lambda s: int(s, 16), default=0x0F)
    p.add_argument("--extra-packets", type=int, default=256,
                   help="maximum A6 03 packets after nominal drain (default: 256)")
    p.add_argument("--probe-timeout-ms", type=int, default=50,
                   help="read timeout for each beyond-end A6 probe (default: 50)")
    p.add_argument("--output-dir", type=Path, default=Path("captures"))
    args = p.parse_args()

    if args.range_id not in (1, 2, 3):
        p.error("--range must be 01, 02, or 03")
    if args.extra_packets < 1:
        p.error("--extra-packets must be >= 1")
    if args.probe_timeout_ms < 1:
        p.error("--probe-timeout-ms must be >= 1")

    cfg = DirectADCConfig(channel=args.channel, a3=args.a3, range_id=args.range_id)
    print(f"Target: CH{cfg.channel}, A2={cfg.range_id:02X}, A3={cfg.a3:02X}, {cfg.sample_rate/1e6:.3f} MS/s")
    print("One acquisition only. Canonical acquisition code is unchanged.")
    print("Map: C6 -> nominal drain -> C6 -> A6 beyond reported depth until limit/failure.\n")

    recovery = {"attempted": False}
    final02 = final03 = {"ok": False, "error": "not attempted"}

    with Hantek1008C() as scope:
        device = scope.connection_id
        DirectADCSession(scope, cfg).initialize()
        ready = arm_ready(scope, cfg.timeout_ms)

        before02 = c6(scope, 2, cfg.timeout_ms)
        before03 = c6(scope, 3, cfg.timeout_ms)
        print(f"Before drain: C6 02={before02['reported_bytes']} B, C6 03={before03['reported_bytes']} B")

        b2m, b3m = {}, {}
        b2 = _query_buffer(scope, 2, cfg.timeout_ms, metrics=b2m)
        b3 = _query_buffer(scope, 3, cfg.timeout_ms, metrics=b3m)
        nominal = b2 + b3
        print(f"Drained     : buffer02={len(b2)} B, buffer03={len(b3)} B ({len(nominal)//2} u16 words)")

        after02 = c6(scope, 2, cfg.timeout_ms)
        after03 = c6(scope, 3, cfg.timeout_ms)
        print(f"After drain : C6 02={after02['reported_bytes']} B, C6 03={after03['reported_bytes']} B")

        extras, extra_raw = extra_a6(scope, 3, args.extra_packets, cfg.timeout_ms, args.probe_timeout_ms)
        successful = sum(1 for row in extras if row.get("read_ok"))
        print(f"Beyond end  : {successful} successful packet(s), {len(extra_raw)} byte(s) returned")
        for row in extras:
            if row.get("read_ok"):
                status = f"{row['length']} B"
            elif row.get("timed_out"):
                status = "TIMEOUT"
            else:
                status = "ERROR"
            preview = row.get("data_hex", "")[:32]
            print(f"  extra A6 #{row['probe']:03d}: {status}" + (f"  {preview}..." if preview else ""))

        boundary_failure = bool(extras and not extras[-1].get("read_ok"))
        if boundary_failure:
            print("Boundary failure observed; clearing endpoint halt(s) before final diagnostic C6.")
            recovery = clear_halts(scope)
            print(f"  clear_halt: IN={recovery.get('in_ok')} OUT={recovery.get('out_ok')}")

        final02 = safe_c6(scope, 2, cfg.timeout_ms)
        final03 = safe_c6(scope, 3, cfg.timeout_ms)
        if final02["ok"] and final03["ok"]:
            print(f"Final C6    : C6 02={final02['value']['reported_bytes']} B, C6 03={final03['value']['reported_bytes']} B")
        else:
            print(f"Final C6    : 02={'OK' if final02['ok'] else 'ERROR'}, 03={'OK' if final03['ok'] else 'ERROR'}")

    checks = structural_checks(nominal, extra_raw)
    print("\nStructural checks (exact bytes only):")
    print(f"  combined bytes                    : {checks['combined_bytes']}")
    print(f"  extra == nominal prefix           : {checks['extra_equals_nominal_prefix']}")
    print(f"  nominal found inside extra at     : {checks['nominal_found_in_extra_at']}")
    print(f"  exact nominal-suffix/extra-prefix : {checks['suffix_nominal_to_prefix_extra_exact_overlap']['bytes']} B")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.output_dir / f"{stamp}_unread-depth-probe"
    json_out = stem.with_suffix(".json")
    nominal_out = Path(str(stem) + "_nominal.bin")
    extra_out = Path(str(stem) + "_extra.bin")
    combined_out = Path(str(stem) + "_combined.bin")

    nominal_out.write_bytes(nominal)
    extra_out.write_bytes(extra_raw)
    combined_out.write_bytes(nominal + extra_raw)

    payload = {
        "format": "hantek1008c-unread-depth-probe-v2",
        "timestamp_utc": stamp,
        "device": device,
        "channel": cfg.channel,
        "range_a2": f"{cfg.range_id:02X}",
        "a3": f"{cfg.a3:02X}",
        "validated_within_triggered_sample_rate_hz": cfg.sample_rate,
        "ready": ready,
        "c6_before_drain": {"02": before02, "03": before03},
        "drain": {
            "buffer02_bytes": len(b2),
            "buffer03_bytes": len(b3),
            "buffer02_metrics": b2m,
            "buffer03_metrics": b3m,
        },
        "c6_after_drain": {"02": after02, "03": after03},
        "extra_a6_03": extras,
        "extra_successful_packets": successful,
        "extra_returned_bytes": len(extra_raw),
        "endpoint_recovery": recovery,
        "c6_after_extra_probes": {"02": final02, "03": final03},
        "structural_checks": checks,
        "raw_files": {
            "nominal": nominal_out.name,
            "extra": extra_out.name,
            "combined": combined_out.name,
        },
        "note": "Diagnostic-only protocol probe. Exact-byte structural checks only; no waveform-specific processing and no assumption of temporal continuity.",
    }
    json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print("\nSaved:")
    print(f"  {json_out}")
    print(f"  {nominal_out}")
    print(f"  {extra_out}")
    print(f"  {combined_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
