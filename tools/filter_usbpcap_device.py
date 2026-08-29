#!/usr/bin/env python3
"""Filter a USBPcap pcapng to one USB device address.

The tool can either accept --device-address explicitly or discover the address
from a USB device descriptor matching --vid/--pid.  USB device addresses are
session/bus enumeration values and must not be treated as persistent device
identity.

This is intentionally a small dependency-free pcapng block copier for the
Windows USBPcap evidence used by this project.  It preserves all non-packet
pcapng blocks and retains Enhanced Packet Blocks whose USBPcap pseudo-header
has the selected device address.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

PCAPNG_EPB = 0x00000006
USBPCAP_MIN_HEADER = 27


def iter_blocks(blob: bytes):
    off = 0
    while off + 12 <= len(blob):
        block_type, block_len = struct.unpack_from("<II", blob, off)
        if block_len < 12 or block_len % 4 or off + block_len > len(blob):
            raise ValueError(f"invalid pcapng block at offset {off}: len={block_len}")
        tail_len = struct.unpack_from("<I", blob, off + block_len - 4)[0]
        if tail_len != block_len:
            raise ValueError(f"pcapng block length mismatch at offset {off}")
        yield block_type, blob[off : off + block_len]
        off += block_len
    if off != len(blob):
        raise ValueError(f"trailing {len(blob) - off} byte(s) after final pcapng block")


def epb_packet(block: bytes) -> bytes | None:
    if len(block) < 32:
        return None
    cap_len = struct.unpack_from("<I", block, 20)[0]
    start = 28
    end = start + cap_len
    if end > len(block) - 4:
        return None
    return block[start:end]


def usbpcap_device(packet: bytes) -> int | None:
    if len(packet) < USBPCAP_MIN_HEADER:
        return None
    header_len = struct.unpack_from("<H", packet, 0)[0]
    if header_len < USBPCAP_MIN_HEADER or header_len > len(packet):
        return None
    return struct.unpack_from("<H", packet, 19)[0]


def descriptor_vid_pid(packet: bytes) -> tuple[int, int] | None:
    if len(packet) < USBPCAP_MIN_HEADER:
        return None
    header_len = struct.unpack_from("<H", packet, 0)[0]
    if header_len < USBPCAP_MIN_HEADER or header_len > len(packet):
        return None
    payload = packet[header_len:]
    # Standard USB device descriptor: length=18, type=DEVICE(1), VID/PID at 8/10.
    if len(payload) < 18 or payload[0] != 18 or payload[1] != 1:
        return None
    return struct.unpack_from("<HH", payload, 8)


def discover_address(blocks, vid: int, pid: int) -> int:
    found = set()
    for block_type, block in blocks:
        if block_type != PCAPNG_EPB:
            continue
        packet = epb_packet(block)
        if packet is None:
            continue
        ids = descriptor_vid_pid(packet)
        if ids == (vid, pid):
            dev = usbpcap_device(packet)
            if dev is not None:
                found.add(dev)
    if not found:
        raise SystemExit(f"no USB device descriptor found for {vid:04x}:{pid:04x}")
    if len(found) != 1:
        vals = ", ".join(str(x) for x in sorted(found))
        raise SystemExit(f"multiple device addresses matched {vid:04x}:{pid:04x}: {vals}")
    return next(iter(found))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--device-address", type=int)
    ap.add_argument("--vid", type=lambda s: int(s, 0), default=0x0783)
    ap.add_argument("--pid", type=lambda s: int(s, 0), default=0x5725)
    args = ap.parse_args()

    blob = args.input.read_bytes()
    blocks = list(iter_blocks(blob))
    device = args.device_address
    if device is None:
        device = discover_address(blocks, args.vid, args.pid)

    kept_packets = 0
    total_packets = 0
    out = bytearray()
    for block_type, block in blocks:
        if block_type == PCAPNG_EPB:
            total_packets += 1
            packet = epb_packet(block)
            if packet is None or usbpcap_device(packet) != device:
                continue
            kept_packets += 1
        out += block

    args.output.write_bytes(out)
    print(f"device_address={device}")
    print(f"kept_packets={kept_packets}/{total_packets}")
    print(f"input_bytes={len(blob)} output_bytes={len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
