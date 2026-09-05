from dataclasses import replace
from pathlib import Path

import pytest

from hantek1008c.calibration import (
    build_zero_calibration,
    load_max_zero_shift_counts,
    load_zero_calibration,
    save_max_zero_shift_counts,
    save_reference_validation,
    save_zero_calibration,
    section_name,
    validate_zero_candidate,
    validate_onboard_reference,
)


LIBSIGROK_GENERATED_CALIBRATION = """\
[format]
version = 1

[device usb/1-1.1 channel CH1 range 01]
usb_vid = 0783
usb_pid = 5725
connection_id = usb/1-1.1
channel = CH1
range_a2 = 01
zero_adc = 1939.083666667
zero_stddev = 0.822901304
zero_min = 1936
zero_max = 1942
samples = 12000
volts_per_count = 0.0002
calibrated_utc = 2026-09-05T08:32:36+00:00
scale_source = reference_nominal_mfg92

[device usb/1-1.1 channel CH1 range 02]
usb_vid = 0783
usb_pid = 5725
connection_id = usb/1-1.1
channel = CH1
range_a2 = 02
zero_adc = 1950.031750000
zero_stddev = 0.739081821
zero_min = 1947
zero_max = 1953
samples = 12000
volts_per_count = 0.00125
calibrated_utc = 2026-09-05T08:32:44+00:00
scale_source = reference_nominal_mfg92
validation_source = onboard_1khz_2vpp
validation_measured_vpp = 2.067500000
validation_measured_frequency_hz = 1000.000000000
validation_passed = true
validation_samples = 12000
validated_utc = 2026-09-05T08:33:08+00:00

[device usb/1-1.1 channel CH1 range 03]
usb_vid = 0783
usb_pid = 5725
connection_id = usb/1-1.1
channel = CH1
range_a2 = 03
zero_adc = 1969.439500000
zero_stddev = 0.675282472
zero_min = 1965
zero_max = 1973
samples = 12000
volts_per_count = 0.01
calibrated_utc = 2026-09-05T08:32:52+00:00
validation_source = onboard_1khz_2vpp
validation_measured_vpp = 1.970000000
validation_measured_frequency_hz = 1000.000000000
validation_passed = true
validation_samples = 12000
validated_utc = 2026-09-05T08:33:11+00:00
scale_source = reference_nominal_mfg92
"""


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


def test_first_zero_must_be_in_plausible_midscale_region():
    candidate = build_zero_calibration("usb/1-2.3", 1, 3, [2015] * 100)
    assert validate_zero_candidate(candidate, None, 20) is None

    implausible = replace(candidate, zero_adc=1700.0)
    with pytest.raises(ValueError, match="outside the plausible"):
        validate_zero_candidate(implausible, None, 20)


def test_existing_zero_shift_is_limited():
    previous = build_zero_calibration("usb/1-2.3", 1, 3, [2015] * 100)
    nearby = replace(previous, zero_adc=2029.0)
    assert validate_zero_candidate(nearby, previous, 20) == pytest.approx(14.0)

    anomalous = replace(previous, zero_adc=1969.0)
    with pytest.raises(ValueError, match="exceeds the permitted"):
        validate_zero_candidate(anomalous, previous, 20)
    assert validate_zero_candidate(anomalous, previous, 50) == pytest.approx(-46.0)


def test_device_zero_shift_policy_round_trip(tmp_path: Path):
    path = tmp_path / "calibration.ini"
    value, source = load_max_zero_shift_counts("usb/1-2.3", path)
    assert value == pytest.approx(20.0)
    assert source == "default"

    save_max_zero_shift_counts("usb/1-2.3", 50, path)
    value, source = load_max_zero_shift_counts("usb/1-2.3", path)
    assert value == pytest.approx(50.0)
    assert source == "saved device policy"

    other_value, other_source = load_max_zero_shift_counts("usb/9-9", path)
    assert other_value == pytest.approx(20.0)
    assert other_source == "default"


def test_loads_libsigrok_generated_calibration_store(tmp_path: Path):
    """Keep the Python/libsigrok calibration-file contract compatible."""
    path = tmp_path / "calibration.ini"
    path.write_text(LIBSIGROK_GENERATED_CALIBRATION, encoding="utf-8")

    expected = {
        1: (1939.083666667, 0.822901304, 1936, 1942, 0.0002),
        2: (1950.031750000, 0.739081821, 1947, 1953, 0.00125),
        3: (1969.439500000, 0.675282472, 1965, 1973, 0.01),
    }
    for range_id, values in expected.items():
        cal = load_zero_calibration("usb/1-1.1", 1, range_id, path)
        assert cal is not None
        assert cal.zero_adc == pytest.approx(values[0])
        assert cal.zero_stddev == pytest.approx(values[1])
        assert cal.zero_min == values[2]
        assert cal.zero_max == values[3]
        assert cal.samples == 12000
        assert cal.volts_per_count == pytest.approx(values[4])
        assert cal.scale_source == "reference_nominal_mfg92"

    assert load_zero_calibration("usb/1-1.1", 2, 3, path) is None
    assert load_zero_calibration("usb/9-9", 1, 3, path) is None


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


def test_scale_provenance_and_explicit_replacement(tmp_path: Path):
    from hantek1008c.calibration import replace_voltage_scale
    path = tmp_path / "calibration.ini"
    cal = build_zero_calibration("usb/1-2.3", 1, 2, [1996, 1997, 1996, 1998])
    assert cal.scale_source == "reference_nominal_mfg92"
    changed = replace_voltage_scale(cal, 0.001163467, "onboard_nominal_2Vpp_square")
    assert changed.zero_adc == cal.zero_adc
    assert changed.volts_per_count == pytest.approx(0.001163467)
    assert changed.scale_source == "onboard_nominal_2Vpp_square"
    save_zero_calibration(changed, path)
    loaded = load_zero_calibration("usb/1-2.3", 1, 2, path)
    assert loaded is not None
    assert loaded.zero_adc == cal.zero_adc
    assert loaded.volts_per_count == pytest.approx(0.001163467)
    assert loaded.scale_source == "onboard_nominal_2Vpp_square"


def test_onboard_reference_scale_estimator():
    from hantek1008c.calibration import estimate_onboard_reference_scale
    frame = ([2000] * 2000) + ([2200] * 2000)
    scale, span = estimate_onboard_reference_scale([frame], expected_vpp=2.0)
    assert span == pytest.approx(200.0)
    assert scale == pytest.approx(0.01)
