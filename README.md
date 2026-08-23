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
