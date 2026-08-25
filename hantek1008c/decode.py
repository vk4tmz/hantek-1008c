from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import struct


CHANNEL_COUNT = 8


@dataclass
class DecodedCapture:
    channel_ids: list[int]
    channels: list[list[int]]

    @property
    def samples_per_channel(self) -> int:
        return len(self.channels[0]) if self.channels else 0

    def to_rows(self) -> list[list[int]]:
        rows = []
        for i in range(self.samples_per_channel):
            rows.append([i] + [samples[i] for samples in self.channels])
        return rows

    def write_csv(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["sample_index"] + [f"ch{i}" for i in self.channel_ids])
            w.writerows(self.to_rows())
        return path


def decode_interleaved_u12_le(data: bytes, active_channels: list[int] | None = None) -> DecodedCapture:
    if len(data) % 2:
        raise ValueError("capture byte length must be even")

    if active_channels is None:
        active_channels = list(range(1, CHANNEL_COUNT + 1))
    active_channels = sorted(active_channels)
    if not active_channels or any(ch < 1 or ch > CHANNEL_COUNT for ch in active_channels):
        raise ValueError("active_channels must contain one or more channels in 1..8")
    if len(set(active_channels)) != len(active_channels):
        raise ValueError("active_channels contains duplicates")

    words = struct.unpack("<" + "H" * (len(data) // 2), data)
    adc = [w & 0x0FFF for w in words]
    lane_count = len(active_channels)

    if len(adc) % lane_count:
        raise ValueError(
            f"decoded word count {len(adc)} is not divisible by {lane_count} active channels"
        )

    channels = [adc[i::lane_count] for i in range(lane_count)]
    return DecodedCapture(channel_ids=active_channels, channels=channels)


def decode_buffers(buffer02: bytes, buffer03: bytes, active_channels: list[int] | None = None) -> DecodedCapture:
    return decode_interleaved_u12_le(buffer02 + buffer03, active_channels=active_channels)
