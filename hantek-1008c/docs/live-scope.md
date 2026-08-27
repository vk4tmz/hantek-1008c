# Experimental live scope

`tools/live_scope.py` opens/configures the Hantek once and repeatedly re-arms
and reads buffers 02/03. It currently displays one command-line-selected
channel.

Example:

    python tools/live_scope.py --channel 1

Defaults: A3=0F (~2.4 MS/s for one active channel), A2=03. The reconstructed
vertical axis is intentionally labelled decoder counts, not volts. A simple
software rising-edge alignment stabilizes repetitive waveforms; `--no-trigger`
disables it and `--raw` displays raw 12-bit words.

This is experimental: sustained acquisition semantics have not yet been
validated on hardware. Ctrl-C or closing the plot stops the viewer.
