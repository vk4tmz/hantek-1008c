# Reference-driver Triggered-guard A/B experiment

The public `mfg92/hantek1008py` Triggered acquisition path sends `E4 01` and `E6 01`
immediately before acquisition and again after reading C6/A6 buffers. Its
source comments that these commands are not necessarily required.

This experiment is deliberately narrow. It **does not** copy the entire
reference initialization sequence. It compares:

1. current project acquisition;
2. identical acquisition plus only the E4/E6 Triggered guards.

Fixed setup: CH1 only, A2=03, A3=0F, onboard 1 kHz nominal 2 Vpp square wave.

If the raw representation changes, the guard commands are causally implicated.
If it does not, the next experiment can safely move earlier into the reference
initialization (`F6`, calibration queries, secondary AC/E9 setup) without
confounding multiple changes at once.
