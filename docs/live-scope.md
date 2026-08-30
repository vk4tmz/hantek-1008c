# Live scope

`tools/live_scope.py` is the basic live viewer for the canonical Hantek 1008C
direct-ADC acquisition path.

Example:

    python tools/live_scope.py --channel 1

Defaults are A3=0F (validated 2.4 MS/s with one active channel) and A2=03.
The hardware is fully initialized once, including the public-reference
calibration/setup sequence, and each frame then uses guarded Triggered acquisition
with A5 readiness polling. The returned 12-bit words are displayed directly;
there is no delta integration, detrending, thresholding, or waveform-specific
cleanup.

The vertical axis is intentionally labelled **Direct ADC counts (12-bit; not
volts)** until per-channel/per-range voltage calibration is promoted into the
canonical path. A simple software rising-edge alignment stabilizes repetitive
waveforms; `--no-trigger` disables that display alignment.

If A5 never reaches ready state 2/3, acquisition fails closed instead of reading
nominal buffer lengths containing invalid/empty data. During reverse-engineering
this state has sometimes required a USB unplug/replug to clear.
