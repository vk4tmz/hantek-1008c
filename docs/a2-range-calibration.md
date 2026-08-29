# A2 range calibration

A2=01, 02 and 03 are validated hardware gain/range states. Calibration is split
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
python tools/calibrate_onboard_scale.py --channel 1 --range 03
```

Explicit persistence:

```bash
python tools/calibrate_onboard_scale.py --channel 1 --range 03 --save-scale
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
