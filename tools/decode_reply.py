#!/usr/bin/env python3

import argparse
import struct


def parse_args():
    p = argparse.ArgumentParser(
        description="Decode a Hantek 1008C USB reply as raw bytes and 16-bit little-endian values."
    )
    p.add_argument(
        "hex",
        nargs="+",
        help='reply bytes, e.g. "00 08 CE 07" or 0008CE07',
    )
    p.add_argument(
        "--group",
        type=int,
        default=8,
        help="values per displayed group (default: 8)",
    )
    return p.parse_args()


def normalise_hex(parts):
    text = "".join(parts).replace("0x", "").replace("0X", "")
    for ch in " :-_,\t\n":
        text = text.replace(ch, "")
    if len(text) % 2:
        raise ValueError("hex input has an odd number of digits")
    return bytes.fromhex(text)


def groups(values, n):
    for i in range(0, len(values), n):
        yield i // n, values[i:i+n]


def main():
    args = parse_args()

    try:
        data = normalise_hex(args.hex)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")

    print(f"length: {len(data)} byte(s)")
    print("raw:")
    print(" ".join(f"{b:02X}" for b in data))

    if len(data) % 2:
        print()
        print("16-bit decode unavailable: reply length is odd")
        return 0

    count = len(data) // 2
    u16 = list(struct.unpack("<" + "H" * count, data))
    s16 = list(struct.unpack("<" + "h" * count, data))

    print()
    print("u16 little-endian:")
    for idx, vals in groups(u16, args.group):
        start = idx * args.group
        print(f"  [{start:02d}] " + " ".join(f"{v:6d}" for v in vals))

    print()
    print("s16 little-endian:")
    for idx, vals in groups(s16, args.group):
        start = idx * args.group
        print(f"  [{start:02d}] " + " ".join(f"{v:6d}" for v in vals))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
