# 2026-08-27 differential-bias lab fixtures

Canonical CH1 / A2=03 / A3=0F captures retained from the waveform-agnostic
reconstruction investigation.

- `20260827T075115Z_grounded-a3-0f_*`: probe tip shorted to probe ground.
  Healthy acquisition (`A5 02` twice), used to characterize differential-zero
  noise and the alternating even/odd raw-word offset at 2.4 MS/s.
- `20260827T074648Z_square-1khz-a3-0f-fresh_*`: Hantek onboard 1 kHz / 2 Vpp
  reference. Healthy acquisition (`A5 02` twice), used to confirm 1200-sample
  half-period / 2.4 MS/s directly from the raw differential stream.

These fixtures are evidence, not permission for waveform-specific cleanup.
Known waveform shape may be used to validate timing and quantify defects, but
production reconstruction must remain waveform-agnostic.
