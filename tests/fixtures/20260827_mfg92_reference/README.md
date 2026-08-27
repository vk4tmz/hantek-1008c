# 2026-08-27 direct-ADC reference fixtures

These fixtures preserve the hardware breakthrough that distinguished the
minimal/wrong acquisition state from the fully initialized direct-ADC state.

- `083001Z` — CH1, 1 kHz onboard square-wave reference, A3=11. Full reference
  initialization returns direct ADC samples with exact 400-sample half-cycles
  (~800 kS/s).
- `083720Z` — same signal/setup, A3=0F. Full reference initialization returns
  direct ADC samples with transition clusters centred at 1199, 2399, 3599 and
  exact 1200-sample half-cycles (2.4 MS/s).

Both are positive regression fixtures. Earlier 500+7500-byte minimal-path
captures remain useful negative evidence for the incorrectly initialized state.
