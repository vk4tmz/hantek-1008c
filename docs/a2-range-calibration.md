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

The production `sigrok-hantek-1008c-calibrate` utility writes the same format-1
section and field schema as the Python calibration module. A regression test in
`tests/test_calibration_store.py` loads representative Narrow, Medium, and Wide
records emitted by that utility, including its reference-validation metadata.
This keeps the cross-project calibration contract explicit.

## Zero-calibration safeguard

Both Python calibration tools and the installed libsigrok utility apply the
same checks before replacing a grounded-zero value:

- A first calibration must lie within the central 45–55% of the 12-bit ADC
  range (approximately 1843–2252 counts).
- A replacement must be within 20 counts of the existing value by default.
- `--max-zero-shift-counts N` selects another positive limit. After a
  successful grounded calibration, that explicit limit is stored as a
  device-wide policy in `[calibration policy <USB connection>]`.
- If no explicit value is supplied, a saved device policy is used; otherwise
  the 20-count default applies.

The comparison is always against the same device, channel, and range. A
rejected candidate does not modify either the calibration entry or policy.
This guard detects a session-wide shifted ADC baseline while still allowing an
operator to deliberately choose a larger tolerance when measurements justify
it.

Calibration also requires strict input isolation. During grounded-zero capture,
the target input must be grounded and every other input must be disconnected or
grounded. In particular, do not leave the onboard reference connected to a
different channel. During reference validation, connect it only to the target
channel and disconnect or ground all others. Testing reproduced excessive
grounded-channel noise when the reference remained connected to either CH2 or
CH8 while CH1 was being calibrated; the noise-quality check correctly rejected
both captures before they could be saved.

After the final input-range/startup integration changed the observed grounded
baseline, all 24 channel/range zero entries were regenerated with the production
utility. Medium and Wide reference validation passed on all eight channels. This
also demonstrated why calibration should be repeated after a driver change that
affects analogue frontend initialization rather than carrying forward stale
zero values merely because the file format is still compatible.

## Unresolved common-mode zero drift (2026-09-06)

The development unit has shown a repeatable midday displacement of its raw ADC
zero on consecutive days. The scope had remained powered continuously for days,
so this must not be described as ordinary post-power-on warm-up. Warmer ambient
conditions and changed room airflow are plausible correlations, but causation
has not yet been established.

With CH1 and CH2 grounded, all other inputs disconnected, no onboard reference
connected, and saved calibration bypassed, three consecutive Triggered frames
were internally stable while their means disagreed with the saved Wide zeros:

| Channel | Saved Wide zero | Raw mean at 12:05 | Raw mean at 12:36 |
|---|---:|---:|---:|
| CH1 | 2004.929 | 1982.952 | 1977.676 |
| CH2 | 2016.054 | 1988.368 | 1982.947 |

Both channels moved downward by approximately 5.3--5.4 counts during the
31-minute observation. A later single-probe CH1 sweep measured raw-minus-saved
zero differences of -29.642, -29.350, and -29.122 counts for Narrow, Medium,
and Wide respectively. Agreement within 0.52 count across all three ranges
shows a common raw ADC displacement rather than incorrect range selection or
voltage scaling. The resulting displayed error differs by range because each
range has a different volts-per-count scale: approximately -5.93 mV Narrow,
-36.69 mV Medium, and -291.22 mV Wide.

One CH1 checkpoint contained a separate transient population (minimum 1721,
standard deviation 14.196 counts) while neighbouring captures remained below
one count standard deviation. The existing noise-quality check would correctly
reject such a calibration capture.

This observation remains an investigation item. Determine whether raw zero
tracks ambient temperature or airflow, and whether the official application
performs continuing zero compensation or sends an unidentified hardware
auto-zero/frontend command. Do not weaken the zero-shift safeguard, introduce
an arbitrary warm-up delay, or compensate waveform data until controlled
evidence establishes a waveform-agnostic correction.
