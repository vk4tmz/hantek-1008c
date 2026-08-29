# A2 vertical-range analysis

The public `mfg92/hantek1008py` implementation recognizes exactly three A2
analogue range IDs. Its factors remain useful reference semantics, but the
source itself marks the Volt/Div interpretation TODO/check, so they are **not**
treated as independently verified per-device calibration constants.

| A2 | mfg92 factor | reference nominal V/count |
|---|---:|---:|
| 01 | 0.02 | 0.000200 |
| 02 | 0.125 | 0.001250 |
| 03 | 1.0 | 0.010000 |

## 2026-08-29 direct-ADC evidence

Canonical direct-ADC acquisition, with no reconstruction or waveform cleanup,
shows that A2=01, 02 and 03 are three distinct, deterministic analogue gain
states. A forward/reverse `01 -> 02 -> 03 -> 03 -> 02 -> 01` sequence showed
sub-percent repeatability for A2=01/02 at useful signal levels and no meaningful
order/hysteresis effect.

A 1 kHz sine amplitude sweep from the same USB-audio source gave a stable
A2=01/A2=02 gain ratio once the lower-resolution measurements were excluded:

- 5%: 5.0147x
- 10%: 4.9922x
- 15%: 5.0187x
- 20%: 5.0061x
- mean of those four: approximately **5.008x**

This is strong evidence that A2=01 remains linear over the tested interval; the
previous isolated ~6.23x low-level result was dominated by too little ADC span.
A separate 5% square-wave test also remained near this approximately 5x region
after plateau analysis, so sine-vs-square is not the primary explanation.

Using the scope's onboard nominal 1 kHz / 2 Vp-p square reference, repeated
captures produced:

- A2=02: 1719, 1719, 1719 counts p-p
- A2=03: 204, 205, 204 counts p-p
- measured A2=02/A2=03 gain ratio: **8.4127x**

If the onboard output is treated as nominally exactly 2.0 Vp-p, this particular
unit implies working scales near:

- A2=02: **0.001163467 V/count**
- A2=03: **0.009787928 V/count**
- A2=01: approximately **0.0002323 V/count**, transferred from A2=02 using the
  measured ~5.008x low-level gain ratio.

Those empirical values are **not universal constants**. The onboard output is a
nominal reference rather than a laboratory voltage standard, and A2=01's scale
is transferred through a separate common-source ratio measurement. Do not
hard-code them into the protocol model or production driver.

Grounded calibration also demonstrated that zero offset is genuinely range
specific on the tested unit (approximately 1986.3, 1996.7 and 2015.5 counts for
A2 01, 02 and 03 respectively). Per-device/per-channel/per-range zero and scale
provenance therefore belong in persistent calibration state.

A2=00 and A2=04 have shown alias-like behaviour on this one unit (00~03 and
04~02), but remain unsupported and must not be promoted.

## V/div semantics remain separate

A2 is a physical analogue gain/range selector. It must not yet be equated
one-for-one with a PulseView/libsigrok V/div value. The scope exposes a larger
1-2-5 family of user-facing vertical settings than the three observed A2 gain
states, implying additional display/probe scaling semantics. Resolve that
mapping before adding `SR_CONF_VDIV` to the production driver.
