# Reference-driver F6 A/B experiment

This follows the negative E4/E6 Triggered-guard result.

The experiment keeps CH1-only, A2=03, A3=0F and the onboard 1 kHz nominal
2 Vpp square wave fixed. Capture B differs from capture A only by adding `F6`
at the startup/calibration position used by the public reference driver.

Do not enable the E4/E6 Triggered guards for this comparison.

Compare:
- buffer sizes and raw-word distribution;
- modal delta centre;
- square-wave transition spacing/sample rate;
- transition impulse areas;
- whether the sample representation changes materially.
