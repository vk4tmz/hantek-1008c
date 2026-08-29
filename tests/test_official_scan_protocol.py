from __future__ import annotations

import pytest

from hantek1008c.scan_protocol import (
    OFFICIAL_SCAN_PROFILES,
    ScanCandidateRowFramer,
    ca_padding_is_zero,
    ca_valid_prefix,
    classify_c9_count,
    decode_c9_available,
    le_u12_candidate_rows,
    le_u12_words,
    trim_ca_packet,
)


def test_official_scan_profiles_match_windows_boundary_evidence():
    assert OFFICIAL_SCAN_PROFILES["1a"]["a3"] == 0x1A
    assert OFFICIAL_SCAN_PROFILES["1a"]["time_div"] == "500ms/div"
    assert OFFICIAL_SCAN_PROFILES["1b"]["a3"] == 0x1B
    assert OFFICIAL_SCAN_PROFILES["1b"]["time_div"] == "1s/div"
    assert OFFICIAL_SCAN_PROFILES["1c"]["a3"] == 0x1C
    assert OFFICIAL_SCAN_PROFILES["1c"]["time_div"] == "2s/div"
    assert OFFICIAL_SCAN_PROFILES["28"]["a3"] == 0x28
    assert OFFICIAL_SCAN_PROFILES["28"]["time_div"] == "20000s/div"
    assert all(
        row["ac"] == bytes.fromhex("AC 00 00 00 00 01 00 00 01")
        for row in OFFICIAL_SCAN_PROFILES.values()
    )
    assert OFFICIAL_SCAN_PROFILES["1a"]["ac"] == bytes.fromhex(
        "AC 00 00 00 00 01 00 00 01"
    )


def test_c9_value_is_big_endian_two_bytes():
    assert decode_c9_available(bytes.fromhex("00 00")) == 0
    assert decode_c9_available(bytes.fromhex("00 0A")) == 10
    assert decode_c9_available(bytes.fromhex("0B B0")) == 2992
    with pytest.raises(ValueError):
        decode_c9_available(b"\x1a")


def test_c9_classification_quarantines_oversize_values():
    assert classify_c9_count(0) == "empty"
    assert classify_c9_count(10) == "packet-prefix"
    assert classify_c9_count(64) == "packet-prefix"
    assert classify_c9_count(2992) == "oversize"
    with pytest.raises(ValueError):
        classify_c9_count(-1)


def test_ca_valid_prefix_is_only_defined_for_one_packet_counts():
    packet = bytes(range(64))
    assert ca_valid_prefix(packet, 10) == bytes(range(10))
    assert ca_valid_prefix(packet, 64) == packet
    assert trim_ca_packet(packet, 10) == bytes(range(10))
    with pytest.raises(ValueError):
        ca_valid_prefix(packet, 0)
    with pytest.raises(ValueError):
        ca_valid_prefix(packet, 2992)
    with pytest.raises(ValueError):
        ca_valid_prefix(packet[:-1], 10)


def test_ca_padding_check_matches_observed_steady_state_shape():
    good = bytes(range(10)) + bytes(54)
    bad = bytes(range(10)) + b"\x01" + bytes(53)
    assert ca_padding_is_zero(good, 10)
    assert not ca_padding_is_zero(bad, 10)
    with pytest.raises(ValueError):
        ca_padding_is_zero(good, 2992)


def test_observational_u12_view_does_not_invent_odd_tail_word():
    data = bytes.fromhex("D3 07 97 08 FF")
    assert le_u12_words(data) == [0x7D3, 0x897]


def test_candidate_4byte_rows_expose_neutral_word0_word1_only():
    data = bytes.fromhex("D3 07 97 08 D0 07 9A 08 FF EE")
    assert le_u12_candidate_rows(data) == [(0x7D3, 0x897), (0x7D0, 0x89A)]
    # Incomplete trailing bytes are preserved in the original buffer but are
    # not invented into a partial candidate row.
    assert len(data) % 4 == 2


def test_stateful_candidate_row_framer_carries_across_ca_boundaries():
    framer = ScanCandidateRowFramer()
    # First transport chunk ends halfway through a logical candidate row.
    assert framer.feed(bytes.fromhex("D3 07")) == []
    assert framer.carry == bytes.fromhex("D3 07")

    # The next chunk completes that row and contains half of the following row.
    assert framer.feed(bytes.fromhex("97 08 D0 07")) == [(0x7D3, 0x897)]
    assert framer.carry == bytes.fromhex("D0 07")

    # A third chunk completes the second row without inventing packet alignment.
    assert framer.feed(bytes.fromhex("9A 08")) == [(0x7D0, 0x89A)]
    assert framer.carry == b""
    assert framer.total_input_bytes == 8
    assert framer.total_rows == 2


def test_stateful_candidate_row_framer_preserves_capture_end_tail():
    framer = ScanCandidateRowFramer()
    rows = framer.feed(bytes.fromhex("D3 07 97 08 FF EE"))
    assert rows == [(0x7D3, 0x897)]
    assert framer.carry == bytes.fromhex("FF EE")
    assert framer.total_input_bytes == 6
    assert framer.total_rows == 1
