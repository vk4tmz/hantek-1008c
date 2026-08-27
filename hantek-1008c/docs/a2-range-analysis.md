# A2 vertical-range analysis

The public `mfg92/hantek1008py` implementation recognizes exactly three A2
vertical-scale IDs:

| A2 | reference factor | nominal raw-to-volt scale |
|---|---:|---:|
| 01 | 0.02 | 0.0002 V/count |
| 02 | 0.125 | 0.00125 V/count |
| 03 | 1.0 | 0.01 V/count |

The reference source itself marks the Volt/Div interpretation as TODO/check, so
the factors are preserved as reference-driver semantics rather than treated as
independently verified hardware specifications.

Our 1 kHz nominal-2-Vpp corpus gives a useful cross-check after acquisition-local
delta-center estimation and local transition integration:

- A2=03: about 2.39 Vpp equivalent.
- A2=02: about 2.13 Vpp equivalent.
- A2=01: about 0.55 Vpp equivalent and is clearly unsuitable for calibration
  with this large source; treat it as over-range/clipped.
- A2=00 behaves very similarly to 03 on this unit, but is unsupported.
- A2=04 behaves very similarly to 02 on this unit, but is unsupported.

Do not promote 00/04 aliases or volts calibration into the production API from
this single-device corpus. A lower-amplitude external reference is needed to
validate A2=01/02/03 without over-range.
