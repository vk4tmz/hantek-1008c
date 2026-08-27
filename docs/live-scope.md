# Experimental live scope

`tools/live_scope.py` opens the Hantek 1008C, performs the full initialization
sequence validated against the public `mfg92/hantek1008py` implementation, and
then repeatedly performs guarded burst acquisitions.

The viewer now displays **direct 12-bit ADC samples**. It does not integrate a
delta stream, detrend, threshold, smooth, or otherwise reconstruct the waveform.
Vertical units are therefore ADC counts, not volts, until per-channel/range
voltage calibration is promoted into the canonical path.

Example:

    python tools/live_scope.py --channel 1

Defaults: A3=0F (validated 2.4 MS/s for one active channel), A2=03. A simple
software rising-edge alignment stabilizes repetitive waveforms; `--no-trigger`
disables it.

Each frame polls `A5 5A` until the hardware reports ready state 2 or 3 before
reading the capture buffers. If the device remains in state 0/1, the viewer
fails closed rather than displaying stale/empty data; a USB unplug/replug may be
required to recover the device.

Ctrl-C or closing the plot stops the viewer.
