# 2026-08-27 mfg92 reference initialization fixture

Canonical CH1 1 kHz / 2 Vpp onboard square-wave capture made with the experimental
full mfg92-style initialization path at A3=0x11.  In this state the device returns
buffer03=8000 bytes and buffer02=0; the 4000 little-endian words are direct ADC
samples, not the derivative-looking stream seen with the abbreviated initialization.

This fixture exists to guard the acquisition *mode/state* semantics.  It must not be
used to justify waveform-specific reconstruction or filtering.
