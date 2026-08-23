from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import struct
from typing import Iterable


CHANNEL_COUNT = 8


@dataclass
class DecodedCapture:
    channels: list[list[int]]

    @property
    def samples_per_channel(self) -> int:
        return len(self.channels[0]) if self.channels else 0

    def to_rows(self) -> list[list[int]]:
        rows = []
        for i in range(self.samples_per_channel):
            rows.append([i] + [self.channels[ch][i] for ch in range(CHANNEL_COUNT)])
        return rows

    def write_csv(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["sample_index"] + [f"ch{i}" for i in range(1, CHANNEL_COUNT + 1)])
            w.writerows(self.to_rows())
        return path


def decode_interleaved_u12_le(data: bytes) -> DecodedCapture:
    if len(data) % 2:
        raise ValueError("capture byte length must be even")

    words = struct.unpack("<" + "H" * (len(data) // 2), data)
    adc = [w & 0x0FFF for w in words]

    if len(adc) % CHANNEL_COUNT:
        raise ValueError(
            f"decoded word count {len(adc)} is not divisible by {CHANNEL_COUNT} channels"
        )

    channels = [[] for _ in range(CHANNEL_COUNT)]
    for i, value in enumerate(adc):
        channels[i % CHANNEL_COUNT].append(value)

    return DecodedCapture(channels=channels)


def decode_buffers(buffer02: bytes, buffer03: bytes) -> DecodedCapture:
    return decode_interleaved_u12_le(buffer02 + buffer03)
