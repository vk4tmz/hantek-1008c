from __future__ import annotations

"""Pure helpers for the evidence-backed official C9/CA Scan Mode lab path.

This module contains no USB access and does not alter canonical acquisition.
"""

OFFICIAL_SCAN_PROFILES = {
    # Official Windows UI time/div -> A3 map for the proven Scan Mode region.
    # The Trigger/Scan boundary is 200 ms/div (A3=19) -> 500 ms/div (A3=1A).
    # The captured horizontal sweep showed the same AC value below for A3>=18;
    # this table intentionally starts only at the proven Scan Mode boundary.
    "1a": {"a3": 0x1A, "time_div": "500ms/div", "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "1b": {"a3": 0x1B, "time_div": "1s/div",    "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "1c": {"a3": 0x1C, "time_div": "2s/div",    "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "1d": {"a3": 0x1D, "time_div": "5s/div",    "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "1e": {"a3": 0x1E, "time_div": "10s/div",   "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "1f": {"a3": 0x1F, "time_div": "20s/div",   "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "20": {"a3": 0x20, "time_div": "50s/div",   "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "21": {"a3": 0x21, "time_div": "100s/div",  "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "22": {"a3": 0x22, "time_div": "200s/div",  "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "23": {"a3": 0x23, "time_div": "500s/div",  "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "24": {"a3": 0x24, "time_div": "1000s/div", "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "25": {"a3": 0x25, "time_div": "2000s/div", "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "26": {"a3": 0x26, "time_div": "5000s/div", "ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "27": {"a3": 0x27, "time_div": "10000s/div","ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
    "28": {"a3": 0x28, "time_div": "20000s/div","ac": bytes.fromhex("AC 00 00 00 00 01 00 00 01")},
}


def decode_c9_available(reply: bytes) -> int:
    """Decode the two-byte big-endian value returned by C9."""
    if len(reply) != 2:
        raise ValueError(f"C9: expected 2-byte value, got {len(reply)}")
    return int.from_bytes(reply, "big")


def classify_c9_count(count: int) -> str:
    """Classify a C9 result using only presently observed semantics.

    Steady-state Linux evidence at A3=1A shows even counts in 8..14 where the
    count-sized CA prefix is data and the remainder of the 64-byte reply is
    zero padding.  A startup C9 value of 2992 was consumed by one CA read and
    is deliberately quarantined as ``oversize`` rather than interpreted as a
    byte/FIFO depth.
    """
    if count < 0:
        raise ValueError(f"C9 count must be non-negative, got {count}")
    if count == 0:
        return "empty"
    if count <= 64:
        return "packet-prefix"
    return "oversize"


def ca_valid_prefix(packet: bytes, c9_count: int) -> bytes:
    """Return the evidence-backed valid prefix for a steady-state CA packet.

    Only C9 values 1..64 have a demonstrated prefix-length interpretation.
    Values above 64 are intentionally rejected here so callers cannot silently
    treat the anomalous startup value as a multi-packet byte count.
    """
    if len(packet) != 64:
        raise ValueError(f"CA: expected 64-byte packet, got {len(packet)}")
    if classify_c9_count(c9_count) != "packet-prefix":
        raise ValueError(
            f"CA: C9={c9_count} has no proven one-packet prefix semantics"
        )
    return packet[:c9_count]


def ca_padding_is_zero(packet: bytes, c9_count: int) -> bool:
    """Check the zero-padding property observed after a valid CA prefix."""
    if len(packet) != 64:
        raise ValueError(f"CA: expected 64-byte packet, got {len(packet)}")
    if classify_c9_count(c9_count) != "packet-prefix":
        raise ValueError(
            f"CA: C9={c9_count} has no proven one-packet prefix semantics"
        )
    return not any(packet[c9_count:])


# Compatibility alias retained for older diagnostic callers/tests.  Unlike the
# former implementation it deliberately refuses C9 > 64 rather than truncating
# an unproven oversize condition to one packet.
def trim_ca_packet(packet: bytes, available: int) -> bytes:
    return ca_valid_prefix(packet, available)



class ScanCandidateRowFramer:
    """Statefully frame arbitrary Scan payload chunks into neutral 4-byte rows.

    C9/CA transaction boundaries are transport boundaries, not proven logical-row
    boundaries.  ``feed()`` therefore carries 0..3 bytes between calls and emits
    only complete rows.  No bytes are synthesized, discarded, averaged, selected,
    or otherwise waveform-processed.  ``carry`` remains available to the caller
    at capture end so an arbitrary wall-clock stop cannot silently lose a partial
    row.
    """

    def __init__(self) -> None:
        self._carry = bytearray()
        self.total_input_bytes = 0
        self.total_rows = 0

    @property
    def carry(self) -> bytes:
        return bytes(self._carry)

    def feed(self, data: bytes) -> list[tuple[int, int]]:
        self.total_input_bytes += len(data)
        self._carry.extend(data)
        rows: list[tuple[int, int]] = []
        complete = len(self._carry) - (len(self._carry) % 4)
        for i in range(0, complete, 4):
            word0 = int.from_bytes(self._carry[i : i + 2], "little") & 0x0FFF
            word1 = int.from_bytes(self._carry[i + 2 : i + 4], "little") & 0x0FFF
            rows.append((word0, word1))
        if complete:
            del self._carry[:complete]
        self.total_rows += len(rows)
        return rows


def le_u12_candidate_rows(data: bytes) -> list[tuple[int, int]]:
    """Return complete candidate 4-byte rows as two neutral u12 words.

    The 2026-08-29 C9/CA Scan experiments strongly support a 4-byte logical
    cadence for CH1-only acquisition, but the semantics of the two 16-bit
    words are not yet proven.  This helper therefore exposes them only as
    ``word0`` and ``word1`` and ignores any incomplete trailing bytes without
    modifying the source buffer.
    """
    rows: list[tuple[int, int]] = []
    for i in range(0, len(data) - 3, 4):
        word0 = int.from_bytes(data[i : i + 2], "little") & 0x0FFF
        word1 = int.from_bytes(data[i + 2 : i + 4], "little") & 0x0FFF
        rows.append((word0, word1))
    return rows

def le_u12_words(data: bytes) -> list[int]:
    """Observational view of complete little-endian 16-bit words in raw data."""
    return [
        int.from_bytes(data[i : i + 2], "little") & 0x0FFF
        for i in range(0, len(data) - 1, 2)
    ]
