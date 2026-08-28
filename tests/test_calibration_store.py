from pathlib import Path

import pytest

from hantek1008c.calibration import (
    build_zero_calibration,
    load_zero_calibration,
    save_reference_validation,
    save_zero_calibration,
    section_name,
    validate_onboard_reference,
)


def test_section_is_device_channel_range_specific():
    assert section_name("usb/1-2.3", 1, 3) == "device usb/1-2.3 channel CH1 range 03"


def test_zero_calibration_round_trip(tmp_path: Path):
    path = tmp_path / "calibration.ini"
    cal = build_zero_calibration("usb/1-2.3", 1, 3, [2000, 2001, 2002, 2001])
    save_zero_calibration(cal, path)
    loaded = load_zero_calibration("usb/1-2.3", 1, 3, path)
    assert loaded is not None
    assert loaded.zero_adc == pytest.approx(2001.0)
    assert loaded.volts_per_count == pytest.approx(0.01)
    assert loaded.volts(2201) == pytest.approx(2.0)
    assert load_zero_calibration("usb/1-2.3", 2, 3, path) is None


def test_reference_validation_does_not_modify_zero(tmp_path: Path):
    path = tmp_path / "calibration.ini"
    cal = build_zero_calibration("usb/1-2.3", 1, 3, [2001] * 100)
    save_zero_calibration(cal, path)
    # 1 kHz square at 2.4 MS/s: 1200 samples per half-period, 200 counts span.
    frame = ([2001] * 1200) + ([2201] * 1200) + ([2001] * 1200) + ([2201] * 400)
    result = validate_onboard_reference([frame, frame], cal, 2_400_000.0)
    assert result.measured_vpp == pytest.approx(2.0)
    assert result.measured_frequency_hz == pytest.approx(1000.0)
    assert result.passed
    save_reference_validation(cal, result, path)
    loaded = load_zero_calibration("usb/1-2.3", 1, 3, path)
    assert loaded is not None
    assert loaded.zero_adc == cal.zero_adc
    assert loaded.volts_per_count == cal.volts_per_count


def test_reference_frequency_rejects_transition_ringing():
    cal = build_zero_calibration("usb/1-2.3", 1, 3, [2001] * 100)
    # A 1 kHz square at 2.4 MS/s with midpoint-crossing ringing around each
    # transition.  The validation estimator must count physical cycles, not
    # each noisy threshold toggle.
    low = [2001] * 1195
    rise = [2050, 2110, 2080, 2160, 2140]
    high = [2201] * 1190
    fall = [2150, 2090, 2120, 2040, 2060]
    frame = low + rise + high + fall + low + rise + high + fall
    result = validate_onboard_reference([frame], cal, 2_400_000.0)
    assert result.measured_frequency_hz == pytest.approx(1000.0, rel=0.01)
    assert result.passed
