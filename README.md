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

### Persistent zero calibration

**Scale provenance:** zero offset and voltage scale are independent. A grounded
zero calibration stores the mfg92-derived nominal V/count only as an explicitly
labelled fallback (`scale_source=reference_nominal_mfg92`). Per-device scale
measurements can replace that value without changing `zero_adc`; see
`docs/a2-range-calibration.md`. A2 hardware range is not yet treated as a
one-to-one user-facing V/div setting.


The user-assisted calibration tool stores hardware calibration independently of
PulseView or libsigrok under the XDG data directory (normally
`~/.local/share/hantek-1008c/calibration.ini`). The current identity key is the
physical USB port path plus channel and A2 range; this avoids silently sharing
calibration between two identical scopes until a stable device serial identity
is proven.

For the current CH1 / A2=03 MVP:

```bash
python tools/calibrate_zero.py --channel 1 --range 03
```

The tool performs two deliberately separate phases:

1. Ground CH1. Several direct-ADC Triggered acquisitions establish and store the zero offset
   only if the grounded data are stable.
2. Connect the onboard 1 kHz / 2 Vp-p reference. The tool checks frequency and
   amplitude and records the result, but this validation never changes the zero
   offset or the nominal volts-per-count mapping.

Normal acquisition must never infer zero from whatever signal happens to be
connected at startup. The Python tools and native libsigrok driver consume the
same persisted calibration data.

To work through several channels and ranges with explicit probe-movement
prompts, while skipping already-complete entries by default, run:

```bash
python tools/calibrate_all_channels.py
```

Limit a session when desired, for example:

```bash
python tools/calibrate_all_channels.py --channels 2 3 --ranges 01 02 03
```

The orchestrator groups work by channel and physical connection. With a channel
grounded it captures all selected zero calibrations consecutively, then asks for
one move to the onboard reference and validates A2=02 and A2=03 consecutively.
A2=01 records grounded zero only because the onboard 2 Vp-p reference
over-ranges that sensitive state. The single-range tool retains its combined
ground-to-reference workflow and sends the validated F3 echo every 500 ms while
waiting, so its existing acquisition session remains present.

Fresh device open/initialization tolerates temporary USB re-enumeration for up
to 15 seconds, polling every 500 ms and continuing immediately on success. Any
recovery sequence is logged with attempts and elapsed time. The multi-channel
orchestrator offers to retry the current task or stop safely after a failure;
individual acquisition commands are never blindly retried mid-sequence.

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


### Balanced delta-zero and provisional calibration

The experimental reconstruction now supports three zero modes:

```text
quiet     estimate zero from quiet/raw baseline samples
balanced  estimate zero so alternating transition pairs sum to zero
manual    use an explicitly supplied raw-code zero
```

`balanced` is the default experimental mode.

Example with the known built-in 1 kHz / 2 Vpp source:

```bash
python tools/reconstruct_delta.py \
  captures/20260823T072831Z_ch2-range-01_capture.json \
  --channel 2 \
  --threshold 6 \
  --zero-mode balanced
```

The tool now also reports provisional calibration values from the known source:

- edge spacing -> samples/cycle -> sample rate / sample period;
- reconstructed plateau separation -> provisional volts per reconstructed count.

These calibration values are **not final**. They are intended as empirical
reference measurements until the startup factory calibration blocks (`B5`,
`B6`, `F7`, `F8`, `FA`, etc.) are decoded and reconciled.


### Known-tone timebase validation

For controlled sine-wave tests, use `tools/analyze_tone.py` rather than relying
only on the generic single "best period" autocorrelation value.

Example for a 4 kHz source with a 100 ksample/s/channel candidate rate:

```bash
python tools/analyze_tone.py \
  captures/20260823T085519Z_sine-4khz-clean_capture.json \
  --frequency-hz 4000 \
  --candidate-rate 100000 \
  --channel 2
```

The tool reports:

- correlation near the expected fundamental period;
- correlations at integer multiples of that period;
- half-period / edge-related lags;
- the strongest autocorrelation lags overall.

This is important because a harmonic (for example 2x the true period) can have
a stronger correlation than the physical fundamental in short, quantized
captures.


### Focused single-channel plotting

`plot_capture.py` now supports selecting one channel and plotting it on a
calibrated time axis:

```bash
python tools/plot_capture.py \
  captures/20260823T085519Z_sine-4khz-clean_capture.json \
  --channel 2 \
  --center \
  --sample-rate 100000
```

Options:

```text
--channel N      plot only CH1..CH8
--center         subtract the selected channel mean
--sample-rate R  use milliseconds on the X axis from a per-channel sample rate
```

The default all-channel plotting behavior is unchanged.

For the current 4 kHz validation capture at a candidate 100 ksample/s/channel,
500 samples span about 5 ms, so approximately 20 waveform cycles should be
visible if the raw CH2 lane directly represents the sine waveform.

## Active-channel sample-rate experiment

`capture_buffers.py` supports an explicit active-channel list. It derives both
`A0` (active-channel count) and the eight-byte `AA` enable mask from this list,
and records the result in capture metadata. The decoder and plotting/tone tools
then de-interleave using only those active lanes.

For the onboard 1 kHz / 2 Vpp square-wave test on CH1, keep A3/range/acquisition
settings unchanged and capture this controlled progression:

```bash
python tools/capture_buffers.py --active-channels 1,2,3,4,5,6,7,8 --tag square-1khz-8ch
python tools/capture_buffers.py --active-channels 1,2,3,4       --tag square-1khz-4ch
python tools/capture_buffers.py --active-channels 1,2           --tag square-1khz-2ch
python tools/capture_buffers.py --active-channels 1             --tag square-1khz-1ch
```

The reference implementation reports empirical effective-rate factors versus
8-channel operation of 1.00x (8ch), 1.82x (4ch), 3.03x (2ch), and 4.56x (1ch).
These captures are intended to verify those factors directly on this unit before
we rely on them.

### Regression corpus

The repository now preserves the 2026-08-25 CH1-only onboard 1 kHz / 2 Vpp
A3 sweep under `tests/fixtures/a3_1khz/`.  These are the original raw buffer
payloads and capture metadata, not synthesized waveforms.

Install and run the regression suite with:

```bash
pip install -e '.[test]'
pytest -q
```

The tests currently protect:

- CH1-only `A0`/`AA` configuration and the 500+7500 byte buffer split;
- 4000 decoded words per CH1-only acquisition;
- raw transition-impulse timing at A3 `11`, `10`, `0F`, and `0E`;
- ~800 ksample/s at A3 `11` and `10` for the known 1 kHz source;
- ~2.4 Msample/s at A3 `0F` and `0E`;
- SHA-256 integrity of every raw regression payload.

Timing tests deliberately operate on raw transition-impulse clusters rather
than the experimental cumulative waveform reconstruction.  This keeps known-good
sample timing independent of future fixes to baseline/voltage reconstruction.

## Canonical direct-ADC acquisition (2026-08-27)

Hardware testing against the public `mfg92/hantek1008py` initialization sequence
showed that the full initialization places the 1008C into direct-ADC Triggered mode.
In that state a one-channel Triggered acquisition is 4000 direct 12-bit samples (normally 8000
bytes in buffer 03, buffer 02 empty) and requires **no delta integration or
linear detrending**.

Use the live viewer:

    python tools/live_scope.py --channel 1

or save one canonical direct-ADC Triggered acquisition:

    python tools/capture_direct_adc.py --channel 1 --a3 0f --range 03

`tools/capture_buffers.py` remains available as the legacy/minimal protocol-lab
capture path because its wrong-state fixtures are valuable negative regression
evidence. It is not the canonical oscilloscope acquisition path.
