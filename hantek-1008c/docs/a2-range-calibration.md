# A2 range calibration

Use the onboard 1 kHz, 2 Vpp square-wave reference on CH1.

`tools/sweep_a2.py` fixes CH1-only acquisition and A3=0F (the empirically measured
~2.4 MS/s mode), then captures A2 values 03, 00, 01, 02, and 04.  A2=03 is first
as a known-good control.

Do not interpret normalized decoder counts as volts yet.  Preserve the JSON and
both raw buffer files from each capture; range-dependent span and clipping will
be used to derive the vertical calibration model.
