# A2 range calibration

Narrow, Medium, and Wide are the user-facing names for the validated A2=01,
A2=02, and A2=03 hardware gain/range states. Calibration is split
into two independent pieces:

1. **Zero calibration**: grounded input establishes a per-device, per-channel,
   per-A2 ADC zero. `tools/calibrate_zero.py` stores this value. The voltage
   scale written at that stage is explicitly tagged as the mfg92 reference
   nominal fallback; zero calibration alone does not prove V/count.
2. **Voltage-scale calibration**: an explicit known/nominal source can replace
   the fallback scale without changing `zero_adc`.

For A2=02 and A2=03, the onboard 1 kHz / nominal 2 Vp-p square wave can be used
with `tools/calibrate_onboard_scale.py`. The tool is report-only by default. Use
`--save-scale` only when intentionally accepting the onboard nominal amplitude
as the working per-device scale.

Example report-only run:

```bash
python tools/calibrate_onboard_scale.py --channel 1 --range Wide
```

Explicit persistence:

```bash
python tools/calibrate_onboard_scale.py --channel 1 --range Wide --save-scale
```

Do not use the onboard 2 Vp-p source to calibrate A2=01: it over-ranges that
sensitive analogue state on the tested unit. A2=01 requires a lower-amplitude
known source or a carefully documented transfer calibration from another range.

Calibration files retain `volts_per_count` plus `scale_source` so consumers can
distinguish reference-nominal fallback values from explicitly measured working
scales. Existing format-1 files lacking `scale_source` load as
`legacy_unspecified` for backward compatibility.

All square-wave plateau/quantile processing is calibration/validation-only. It
must never enter canonical arbitrary-waveform acquisition or reconstruction.

## 2026-09-05 all-channel calibration result

The development unit now has grounded zero calibration for all 24 combinations
of CH1 through CH8 and A2=01 through A2=03. Every zero capture used 12000
samples. Across the complete set, the maximum grounded standard deviation was
0.903 count and the maximum grounded span was 11 counts.

The onboard 1 kHz / nominal 2 Vp-p reference validated all eight channels at
A2=02 and A2=03. Every recovered frequency was 1000.00 Hz. A2=02 validation
amplitudes were approximately 2.00 through 2.079 Vp-p, and A2=03 amplitudes were
1.96 through 1.98 Vp-p. A2=01 remains grounded-zero-only because the onboard
reference over-ranges that state.

`tools/calibrate_all_channels.py` groups work by channel and physical
connection: it captures all requested grounded ranges before asking for one
move to the reference, then validates A2=02 and A2=03 consecutively. Its
validation-only path preserves an existing zero and voltage scale. This was
used to add missing CH1 A2=02 validation metadata without replacing its
previously measured scale.

Temporary USB disappearance is handled only at a fresh session boundary. The
tool polls at 500 ms intervals for up to 15 seconds and logs every recovery.
One observed calibration recovery progressed from `not found`, through an
initial `B0` timeout after re-enumeration, to a successful fresh initialization
after 5.9 seconds and six attempts. The subsequent CH6 A2=03 zero capture and
reference validation passed, providing evidence that the recovered session was
sound. Individual acquisition commands are not blindly retried mid-sequence.
