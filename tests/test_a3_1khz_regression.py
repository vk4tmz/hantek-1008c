from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hantek1008c.analysis import detect_delta_impulse_edges
from hantek1008c.decode import decode_buffers


FIXTURES = Path(__file__).parent / "fixtures" / "a3_1khz"

# The timing values are empirical anchors from the fixed onboard 1 kHz source.
EXPECTED = {
    "11": {"half_period": 400.0, "rate": 800_000.0, "edge_count": 10},
    "10": {"half_period": 400.0, "rate": 800_000.0, "edge_count": 10},
    "0F": {"half_period": 1200.0, "rate": 2_400_000.0, "edge_count": 3},
    "0E": {"half_period": 1200.0, "rate": 2_400_000.0, "edge_count": 4},
}

# Guard against silent fixture mutation/corruption.  The tests intentionally
# use the original raw payload bytes, not synthesized samples.
EXPECTED_SHA256 = {
    "20260825T080051Z_square-1000hz-1ch-a3-11_buffer02.bin": "6d51a8f79d7f43e23c5fe960e2459c6bcf31d517f47759ae28a1465be8ab9a47",
    "20260825T080051Z_square-1000hz-1ch-a3-11_buffer03.bin": "e78b3f471a765b7c123c5ce28784c3c45843fd56538164edde97c6c4d88b3865",
    "20260825T080053Z_square-1000hz-1ch-a3-10_buffer02.bin": "596690094b1a24a7902f5a2ce5c8f5bbda41091eac760dd2b700ae6334d29d0d",
    "20260825T080053Z_square-1000hz-1ch-a3-10_buffer03.bin": "8c7c39dc5871233bebdd4b492b87f7fc15c2ee67575b8f77ccea17b7c573be6d",
    "20260825T080054Z_square-1000hz-1ch-a3-0f_buffer02.bin": "c71cc3c35d1a4d2c94f954ee5b579f7beb2ef8fc708feba022784ac681830d15",
    "20260825T080054Z_square-1000hz-1ch-a3-0f_buffer03.bin": "dbd500e22e0944722a45a6d0cd9797181482ce7f8de370d4491c9191354ddc80",
    "20260825T080055Z_square-1000hz-1ch-a3-0e_buffer02.bin": "884c7deb59d4d14157c45717fa84505489e0a48f601ff6b62e5c9af08b816d87",
    "20260825T080055Z_square-1000hz-1ch-a3-0e_buffer03.bin": "d5619f611a84a8e48655e942f4d817abb66abc7dadc5d7876f71fb212c3dca05",
}


def _capture_paths():
    return sorted(FIXTURES.glob("*_capture.json"))


def _resolve(meta_path: Path, stored: str) -> Path:
    return meta_path.parent / Path(stored).name


def _load(meta_path: Path):
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    p2 = _resolve(meta_path, meta["buffer02"]["file"])
    p3 = _resolve(meta_path, meta["buffer03"]["file"])
    active = meta["resolved_configuration"]["active_channels"]
    decoded = decode_buffers(p2.read_bytes(), p3.read_bytes(), active_channels=active)
    return meta, p2, p3, decoded


def test_fixture_set_is_complete():
    captures = _capture_paths()
    assert len(captures) == 4
    assert {json.loads(p.read_text())["resolved_configuration"]["a3_hex"].upper() for p in captures} == set(EXPECTED)


@pytest.mark.parametrize("meta_path", _capture_paths(), ids=lambda p: p.stem)
def test_ch1_payload_layout_is_stable(meta_path: Path):
    meta, p2, p3, decoded = _load(meta_path)
    rc = meta["resolved_configuration"]

    assert rc["a0_active_channel_count"] == 1
    assert rc["active_channels"] == [1]
    assert [x.upper() for x in rc["aa_values_hex"]] == ["01", "00", "00", "00", "00", "00", "00", "00"]
    assert meta["buffer02"]["reported_size_bytes"] == 500
    assert meta["buffer03"]["reported_size_bytes"] == 7500
    assert p2.stat().st_size == 500
    assert p3.stat().st_size == 7500
    assert decoded.channel_ids == [1]
    assert decoded.samples_per_channel == 4000


@pytest.mark.parametrize("meta_path", _capture_paths(), ids=lambda p: p.stem)
def test_raw_delta_impulses_recover_known_sample_rate(meta_path: Path):
    meta, _p2, _p3, decoded = _load(meta_path)
    a3 = meta["resolved_configuration"]["a3_hex"].upper()
    expected = EXPECTED[a3]

    result = detect_delta_impulse_edges(decoded.channels[0], frequency_hz=1000.0)

    assert result.baseline == pytest.approx(2001.0, abs=0.5)
    assert len(result.cluster_centers) == expected["edge_count"]
    assert result.median_half_period == pytest.approx(expected["half_period"], abs=3.0)
    assert result.period_samples == pytest.approx(2 * expected["half_period"], abs=6.0)
    assert result.sample_rate == pytest.approx(expected["rate"], rel=0.005)


def test_fixture_hashes_are_unchanged():
    for name, expected in EXPECTED_SHA256.items():
        assert expected is not None, f"fixture hash not initialized for {name}"
        actual = hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        assert actual == expected
