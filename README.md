# Hantek 1008C Linux

Linux USB protocol research and tooling for the Hantek 1008C 8-channel USB oscilloscope.

Confirmed on the development unit:

- VID:PID `0783:5725`
- Configuration `1`, interface `0`
- Bulk IN `0x81`, bulk OUT `0x02`
- 64-byte max packets
- Observed at USB full-speed (12 Mbit/s)
- No kernel driver bound to interface 0

Confirmed protocol transaction:

```text
OUT 0x02: F3
IN  0x81: F3
```

## Setup

```bash
cd ~/tools/hantek-1008c
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## USB permissions

```bash
sudo cp udev/60-hantek-1008c.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug/reconnect the scope.

## Tools

Enumeration only:

```bash
python tools/enumerate.py
```

F3 keepalive/ping:

```bash
python tools/ping.py
```

Conservative query-like command probing:

```bash
python tools/probe_queries.py
```

Restrict probes if desired:

```bash
python tools/probe_queries.py --command B0
python tools/probe_queries.py --command B5 --command B6
```

Transactions are logged as JSONL under `captures/`.

## Direction

1. Confirm/document USB transport.
2. Characterise query-like commands.
3. Capture vendor-software USB traffic.
4. Run controlled one-variable protocol experiments.
5. Decode acquisition framing/sample representation.
6. Build a reliable Python reference implementation.
7. Evaluate a native libsigrok driver for PulseView.

See `docs/protocol.md`.


### A6 fixed-packet note

The scope returns acquisition data in fixed 64-byte `A6` packets. For a
reported 4000-byte logical buffer the reader fetches 63 packets (4032 raw
bytes) and trims the result to 4000 bytes. This avoids libusb `EOVERFLOW` on
the final partial logical packet.


### Analyse the latest raw capture

After a successful `capture_buffers.py` run:

```bash
python tools/analyze_capture.py
```

The analyser automatically selects the newest `captures/*_capture.json` and
prints candidate byte/word interpretations plus 8-way lane statistics.

With CH1 connected to the built-in 1 kHz / 2 Vpp test output, look for one
candidate layout where lane/channel 1 has a clearly larger AC span/RMS than the
other seven lanes. That is our first strong clue to the actual sample format
and channel interleaving.


### Decode, export, and plot a capture

Install the plotting dependency after syncing this update:

```bash
pip install -r requirements.txt
```

Then:

```bash
python tools/plot_capture.py
```

The tool selects the newest `captures/*_capture.json`, decodes the confirmed
layout, writes a CSV, and saves a PNG plot.

Confirmed raw layout:

```text
buffer02 + buffer03
-> uint16 little-endian transport words
-> low 12 bits are ADC counts
-> CH1, CH2, CH3, CH4, CH5, CH6, CH7, CH8 interleaved
-> repeat
```

For the current 4000-byte + 4000-byte capture, this yields 500 samples per
channel.

The plot intentionally uses:

```text
X axis: sample index
Y axis: raw 12-bit ADC counts
```

No volts-per-count or sample-period calibration is applied yet.


### Known-signal validation range

For the current 1 kHz / 2 Vpp built-in calibration test, the acquisition path
now uses:

```text
A2 03 03 03 03 03 03 03 03
```

for all eight channels.

This is an intentional single-variable change from the previous `A2 01 ...`
setting. Buffer ordering, sample decoding, channel interleaving, and timebase
configuration are unchanged so the next capture/plot is directly comparable.


### Configurable acquisition experiments

Capture defaults now live in `config/default.toml`. Experimental values can be
overridden from the command line without editing source code.

Examples:

```bash
# Show the effective configuration without touching the scope
python tools/capture_buffers.py --dry-run

# Change only A3 and label the capture
python tools/capture_buffers.py --a3 10 --tag a3-10

# Change all channel ranges
python tools/capture_buffers.py --range 03 --tag range-03

# Override one channel only
python tools/capture_buffers.py --ch2-range 01 --tag ch2-range-01

# Override A4 or the AC payload
python tools/capture_buffers.py --a4 01 --tag a4-01
python tools/capture_buffers.py --ac "01 F4 00 09 C5 00 09 C5" --tag ac-test
```

Every capture metadata JSON records the fully resolved settings, making
experiments reproducible and easy to compare.


### Periodicity and sweep comparison

`analyze_capture.py` now reports per-channel:

- AC span and RMS;
- dominant autocorrelation period in samples;
- correlation strength;
- detected excursion/event indices;
- spacing between detected events.

For a group of experimental captures, use:

```bash
python tools/compare_captures.py \
  captures/*_a3-10_capture.json \
  captures/*_a3-11_capture.json \
  captures/*_a3-12_capture.json
```

The comparison automatically identifies the channel with the largest AC
activity and prints the resolved A3 value, dominant period, and event spacing.

`capture_buffers.py` also repeats the resolved A3/A2/A4 settings at the end of
each capture, which makes back-to-back sweep output easier to read.


### Experimental delta reconstruction

The driven calibration channel currently appears as alternating positive and
negative narrow excursions rather than an absolute square-wave level. To test
whether the acquisition payload may represent changes/deltas, use:

```bash
python tools/reconstruct_delta.py captures/<capture>_capture.json
```

The tool:

1. automatically selects the channel with the largest AC activity unless
   `--channel N` is supplied;
2. estimates the raw code corresponding to "no change" from quiet samples;
3. subtracts that delta-zero;
4. cumulatively integrates the residual values;
5. writes a reconstruction CSV;
6. writes separate raw and reconstructed PNG plots.

Example:

```bash
python tools/reconstruct_delta.py \
  captures/20260823T072831Z_ch2-range-01_capture.json \
  --channel 2
```

This is explicitly an **experimental hypothesis test**. The confirmed raw
decoder remains unchanged until the representation is proven.


### Thresholded delta reconstruction

The experimental delta reconstruction now supports an explicit noise threshold:

```bash
python tools/reconstruct_delta.py \
  captures/20260823T072831Z_ch2-range-01_capture.json \
  --channel 2 \
  --threshold 6
```

It writes three separate plots:

- raw acquisition;
- unfiltered cumulative reconstruction;
- thresholded cumulative reconstruction.

The thresholded path integrates only deltas whose absolute distance from the
estimated quiet raw-code level is at least the selected threshold.

Useful comparison sweep:

```bash
for t in 4 6 8; do
  python tools/reconstruct_delta.py \
    captures/20260823T072831Z_ch2-range-01_capture.json \
    --channel 2 \
    --threshold "$t"
done
```

This is still a hypothesis test; it does not alter the confirmed raw decoder.
