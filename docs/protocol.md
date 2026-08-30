# Hantek 1008C USB protocol notes

## Confirmed hardware

```text
VID:PID       0783:5725
USB version   2.00
device ver    2.00
configuration 1
interface     0
class         0xff
subclass      0xff
protocol      0xff
bulk IN       0x81
bulk OUT      0x02
max packet    64 bytes
```

`lsusb -t` reported 12 Mbit/s and no kernel driver bound to interface 0. USB string descriptors are malformed/padded and should not be relied upon for identity.

## Confirmed transaction

### F3

```text
OUT 0x02: F3
IN  0x81: F3
```

Working interpretation: keepalive / ping / transport-health check. Request and response are both one byte, and the response is an exact echo.


## Confirmed startup-data behaviour

The following commands were run repeatedly on the development unit and produced
stable, byte-for-byte identical replies across repeated probes.

CH1 was initially connected to the scope's built-in 1 kHz / 2 Vpp test output.
The same commands were then repeated with CH1 disconnected / grounded and the
replies remained unchanged.

Therefore these replies are **not live waveform samples** and are currently
classified as static startup / calibration / configuration data.

| Command | Reply length | Observed behaviour |
|---|---:|---|
| `B0` | 1 | exact echo `B0` |
| `B5` | 64 | structured static data |
| `B6` | 64 | structured static data |
| `E5` | 2 | structured static data |
| `F7` | 64 | structured static data |
| `F8` | 64 | structured static data |
| `FA` | 56 | structured static data |
| `F5` | 1 | exact echo `F5` |

The structured responses are naturally divisible into little-endian 16-bit
values:

```text
B5: 64 bytes = 32 x 16-bit values
B6: 64 bytes = 32 x 16-bit values
E5:  2 bytes =  1 x 16-bit value
F7: 64 bytes = 32 x 16-bit values
F8: 64 bytes = 32 x 16-bit values
FA: 56 bytes = 28 x 16-bit values
```

Notable patterns:

- `B5` starts with eight `0x0800` values, i.e. eight decimal `2048` values.
- `B6` contains obvious 8-value groupings.
- `F7`, `F8`, and `FA` become structured signed values when interpreted as
  little-endian `int16`.
- These patterns are consistent with calibration / correction tables, but the
  exact semantics are not yet proven.

Use `tools/decode_reply.py` to inspect captures in raw, `uint16`, and `int16`
forms.



## Confirmed parameterised startup acknowledgements

The following parameterised writes have now been confirmed directly on the
development unit:

```text
B9 01 BF 04 00 00 -> B9
B7 00             -> B7
BB 08 00          -> BB
```

These commands are acknowledged by returning only the opcode byte, rather than
echoing the full request payload.

The next documented configuration writes to test are:

```text
A0 08
AA 01 01 01 01 01 01 01 01
```

Existing protocol notes identify these respectively as the enabled-channel
count and the per-channel enable state. They are now available through
`tools/probe_startup.py`, but remain unverified on this project's hardware
until explicitly run.



## Confirmed channel-configuration acknowledgements

The following channel-configuration writes have now been confirmed directly on
the development unit:

```text
A0 08                         -> A0
AA 01 01 01 01 01 01 01 01 -> AA
```

Both are acknowledged by returning only the opcode byte.

Existing reverse-engineering notes identify:

- `A0` as the enabled-channel count.
- `AA` as the per-channel enable state.

The next documented startup/configuration writes are available through
`tools/probe_startup.py` for one-at-a-time testing:

```text
A3 11
C1 00 00
A7 00 00
AC 01 F4 00 09 C5 00 09 C5
```

Their exact semantics on this hardware remain unverified until explicitly run.



## Confirmed startup/configuration command map

The following startup/configuration transactions have now been confirmed on the
development unit:

```text
B9 01 BF 04 00 00             -> B9
B7 00                         -> B7
BB 08 00                      -> BB
A0 08                         -> A0
AA 01 01 01 01 01 01 01 01 -> AA
A3 11                         -> A3
C1 00 00                      -> C1
A7 00 00                      -> A7 00
AC 01 F4 00 09 C5 00 09 C5  -> AC
```

Most parameterised startup/configuration writes return an opcode-only ACK.

`A7` is currently the only confirmed exception in this sequence:

```text
A7 00 00 -> A7 00
```

The second response byte is therefore significant enough to preserve as
protocol evidence. Its semantics remain unknown.

This marks the current boundary between startup/configuration archaeology and
acquisition-path archaeology.

## Acquisition-path probes

Existing reverse-engineering notes describe two acquisition-buffer selectors:

```text
C6 02
A6 02

C6 03
A6 03
```

Working interpretation from prior notes:

- `C6` queries acquisition-buffer state/size.
- `A6` reads acquisition-buffer data.
- selector `02` and selector `03` refer to the two acquisition buffers.

These meanings are **not yet independently verified by this project**.

`tools/probe_acquisition.py` exposes only the exact documented commands:

```text
C6_02 -> C6 02
A6_02 -> A6 02
C6_03 -> C6 03
A6_03 -> A6 03
```

The intended test order is deliberately conservative:

1. `C6_02`
2. inspect/log response
3. only then consider `A6_02`
4. repeat later for selector `03`

Do not bulk-run all four commands while the acquisition semantics are still
being established.



## Documented acquisition waiting cycle

The published Hantek 1008C protocol notes give the following sequence before
buffer-size / buffer-data reads:

```text
F3
A2 01 01 01 01 01 01 01 01
A4 01
C0
C2
A5 5A
A5 5A
```

This project has not yet independently established the semantics of all of
these commands.

`tools/probe_wait_cycle.py` exposes them individually:

```text
F3 -> F3
A2 -> A2 01 01 01 01 01 01 01 01
A4 -> A4 01
C0 -> C0
C2 -> C2
A5 -> A5 5A
```

The recommended reverse-engineering sequence is:

1. Send `F3`.
2. Send `A2`.
3. Query `C6 02` and record whether it remains zero.
4. Send `A4`.
5. Query `C6 02` again.
6. Continue with `C0`, `C2`, and the two `A5 5A` writes, checking `C6 02`
   between stages as useful.

This staged approach is intentional: it can reveal which command actually arms
or starts acquisition instead of treating the published sequence as a black
box.



## Stateful acquisition-sequence requirement

An isolated probe of:

```text
A4 01
```

produced a USB PIPE/STALL on the attempted IN reply. A subsequent isolated
`C6 02` also failed with a PIPE error.

This is evidence that the acquisition path is stateful and that `A4` should
not be treated as an ordinary independent write/ACK transaction.

The project therefore now includes:

```text
tools/run_acquisition_sequence.py
```

which keeps the USB interface claimed for the complete startup/configuration
and waiting-cycle sequence.

The runner deliberately treats an `A4` PIPE/STALL as protocol evidence,
attempts to clear endpoint halts, and continues rather than immediately
aborting. This is intended for characterisation only; it is not yet a
production acquisition implementation.



## Confirmed stateful acquisition sequence

A continuous single-process run of the complete known startup/configuration
sequence followed by the documented waiting cycle produced:

```text
A4 01  -> A4
C0     -> C0
C2     -> C2
A5 5A  -> A5 02
A5 5A  -> A5 02
C6 02  -> 0F A0
```

Before the waiting cycle, `C6 02` returned:

```text
00 00
```

After the waiting cycle it returned:

```text
0F A0
```

Interpreted as big-endian `0x0FA0`, this is 4000 bytes.

This is strong evidence that:

- the acquisition path is stateful;
- the documented waiting sequence successfully makes capture data available;
- `A5 5A -> A5 02` is likely a ready/buffer-state response;
- `C6` returns a two-byte buffer size/state value in big-endian order.

The project now includes `tools/capture_buffers.py`, which performs the full
stateful sequence and then drains selectors `02` and `03` using repeated
`A6 <selector>` requests, reading up to 64 bytes from bulk IN per request.

Raw output is saved under `captures/` together with JSON metadata and a
transaction log.


## Existing reverse-engineering leads

Reported elsewhere, not yet independently verified by this project:

```text
A0   number of enabled channels
AA   enabled-channel state/mask
A2   voltage range per channel
A3   sampling rate
AC   additional sample-rate configuration
AB   trigger level
C1   trigger source/slope
C6   acquisition buffer size query
A6   acquisition buffer read
F3   keepalive / ping
```

Reported initialization sequence:

```text
B0
F3
B901BF040000
B700
BB0800
B5
B6
E5
F7
F8
FA
F5
A008
AA0101010101010101
A311
C10000
A70000
AC01F40009C50009C5
```

Treat this as reference only; do not replay the full sequence blindly.

## Conservative probe candidates

```text
B0
B5
B6
E5
F7
F8
FA
F5
```

`tools/probe_queries.py` sends them one at a time and records replies.

## Experimental method

Change one vendor-software UI variable at a time and diff USB traffic: channel, channel count, vertical range, timebase, trigger source, trigger slope, trigger level. Preserve raw `.pcapng` captures and record exact UI state.

## Next milestones

1. Characterise query-like commands.
2. Build timestamped JSONL evidence.
3. Capture a clean vendor initialization sequence.
4. Decode `C6` / `A6` acquisition framing.
5. Determine sample ordering across 8 channels.
6. Determine ADC-code-to-voltage scaling.


## Fixed-size A6 packet behaviour

The first full buffer-read attempt reached 3968 of 4000 logical bytes and then
failed with libusb `EOVERFLOW` when the host requested only the remaining
32 bytes.

`A6` transfers should therefore be treated as fixed-size 64-byte packets. The
buffer reader now:

1. reads `ceil(reported_size / 64)` packets;
2. requests 64 bytes for every `A6` transfer;
3. concatenates all raw packets;
4. trims the result to the logical size reported by `C6`.

For a 4000-byte logical buffer this means 63 packets (4032 raw bytes), with the
final 32 bytes discarded beyond the reported logical size.

This matches the independent `hantek1008py` implementation.


## First complete raw acquisition

A full stateful acquisition has now successfully returned:

```text
C6 02 -> 0F A0 -> 4000 logical bytes
C6 03 -> 0F A0 -> 4000 logical bytes
```

Each selector required 63 fixed 64-byte `A6` packets (4032 transport bytes),
trimmed to the reported 4000-byte logical length.

This gives 8000 logical bytes across selectors 02 and 03.

Before assigning sample format or voltage scaling, use
`tools/analyze_capture.py` to compare candidate interpretations:

- raw unsigned bytes;
- little- and big-endian 16-bit words;
- signed little-endian 16-bit words;
- low 12 bits of little-endian words;
- 8-way byte and word interleaving.

A known CH1 1 kHz / 2 Vpp stimulus is especially useful because the correct
layout should make one channel/lane show substantially more AC activity than
the other seven.


## Confirmed acquisition sample layout

Structural analysis of a capture taken with CH1 connected to the scope's
built-in 1 kHz / 2 Vpp test output strongly confirms the acquisition layout:

```text
16-bit little-endian transport words
12-bit ADC value = word & 0x0FFF
8-channel interleave:
CH1 CH2 CH3 CH4 CH5 CH6 CH7 CH8
repeat
```

Evidence from the combined 8000-byte capture:

```text
lane 1 span 126 counts, AC RMS ~8.9 counts
lanes 2-8 spans only 4-6 counts, AC RMS ~0.6-0.8 counts
```

Only CH1 was driven, making the channel-lane correspondence unambiguous.

Each 4000-byte buffer contains:

```text
4000 / 2 = 2000 ADC words
2000 / 8 = 250 samples per channel
```

Selectors 02 and 03 together therefore provide 500 samples per channel.

`hantek1008c.decode` now provides reusable decoding, and
`tools/plot_capture.py` exports CSV plus a PNG plot in raw ADC counts.


## Vertical-range validation change

The first plotted CH1 waveform did not resemble the expected 1 kHz calibration
square wave even though the channel interleave was strongly confirmed.

For the next validation capture, only the `A2` range setting is changed:

```text
previous: A2 01 01 01 01 01 01 01 01
current : A2 03 03 03 03 03 03 03 03
```

The decoder, buffer concatenation order, and timebase remain unchanged. This
keeps the experiment controlled and allows direct comparison of waveform shape
under a different vertical range.


## Parameterized reverse-engineering captures

To reduce edit/test iterations, experimentally interesting acquisition fields
are now configurable. `config/default.toml` is the canonical known-working
baseline, while CLI options provide temporary overrides for A3, A2 channel
ranges, A4, AC, command delay, and USB timeout.

The resolved values are embedded in every capture metadata JSON. This allows
controlled one-variable-at-a-time experiments without losing provenance.


## Periodicity analysis

The capture analyser now measures periodic structure directly instead of
relying on visual inspection of PNG plots. For each decoded channel it reports
dominant autocorrelation lag and robustly detected excursion/event spacing.

This is intended to quantify the calibration signal while time calibration is
still unknown. If a known 1 kHz source repeats every N samples, the implied
per-channel sample rate is approximately `N * 1000 samples/s`, subject to
confirmation that the detected events represent one event per calibrator
cycle.


## Experimental delta-coded acquisition hypothesis

With the 1 kHz / 2 Vpp calibration output connected to CH2 at range `01`, the
raw channel contains alternating positive and negative narrow excursions at
50-sample spacing. This resembles transition/delta information more than an
absolute square-wave level.

A separate experimental tool, `tools/reconstruct_delta.py`, now tests this by
estimating the quiet raw-code baseline and cumulatively integrating deviations
from that baseline.

This hypothesis is **not yet promoted to protocol fact**. The established facts
remain:

- 16-bit little-endian transport words;
- low 12 bits contain the channel value;
- CH1..CH8 are interleaved;
- selectors 02 then 03 form a continuous 500-sample/channel acquisition;
- A2 independently controls per-channel vertical gain/range;
- A3 changes periodic sample spacing/timebase behaviour.


## Thresholded delta-reconstruction test

The first unfiltered cumulative reconstruction produced a recognizable square
wave but showed plateau drift. This is consistent with integrating small
baseline/noise residuals between the large alternating transition events.

The experimental reconstruction tool now supports a configurable threshold so
only significant deviations from the estimated quiet raw-code level are
integrated. Comparing thresholds 4, 6, and 8 counts should establish whether
the drift disappears while the alternating transition structure is preserved.

This remains experimental evidence and is not yet treated as the canonical
waveform decode.


## Balanced delta-zero reconstruction

Thresholds 4, 6, and 8 produced the same reconstructed waveform, proving the
plateau drift was not caused by low-level residual noise surviving the
threshold. The remaining staircase drift is consistent with a small bias in
the selected delta-zero.

The experimental decoder now supports `balanced` zero estimation. Consecutive
opposite-sign transition groups are paired, and for each pair the zero that
makes the selected transition deltas sum to zero is calculated. The median
pair-zero is then used for reconstruction.

This should cause a complete up/down cycle to return to the same integrated
baseline without altering individual transition magnitudes.

## Provisional source-derived calibration

Once reconstruction is stable, the known built-in source can provide empirical
calibration:

- 1 kHz frequency establishes samples/cycle and sample rate;
- 2 Vpp amplitude establishes provisional volts per reconstructed count.

These values remain provisional until the device's factory calibration blocks
are decoded and applied.


## Tone-specific autocorrelation validation

A clean 4 kHz CH2 capture at `A3=11` produced strong periodic structure
(span 11 counts, RMS AC ~3.06, generic autocorrelation ~0.943), but the generic
analyser selected lag 50 rather than the 25-sample period predicted by a
100 ksample/s/channel model.

This does not by itself invalidate the 100 ksample/s model: autocorrelation can
prefer an integer multiple of the true period, especially for short,
quantized, or non-sinusoidal encoded data.

`tools/analyze_tone.py` therefore evaluates the expected physical period and
its harmonics explicitly. Future timebase conclusions should use those
frequency-aware results rather than the single generic maximum alone.


## Focused raw-channel waveform plotting

The plotter now supports single-channel selection, mean centering, and a
user-supplied per-channel sample rate. This permits direct visual validation
of the raw CH2 sine capture without the DC offsets of the other seven channels
compressing the display.

For the clean 4 kHz CH2 capture and a 100 ksample/s/channel candidate rate, the
500-sample record should span approximately 5 ms and therefore contain about
20 cycles.

## Active-channel rate experiment (2026-08-25)

The mfg92 `hantek1008py` implementation configures active channels with `A0`
set to the number of active channels and `AA` set to eight per-channel 0/1
bytes. It also reports that reducing the active-channel count raises the actual
sampling rate, with empirical factors `[4.56, 3.03, 2.27, 1.82, 1.51, 1.30,
1.14, 1.00]` for 1 through 8 active channels respectively.

Our capture tool now derives `A0` from the `AA` mask and stores
`active_channels` in metadata. Decoding uses the active-channel count as the
interleave width rather than assuming eight lanes. Initial validation should use
the onboard 1 kHz / 2 Vpp square-wave source on CH1 and compare otherwise
identical 8-, 4-, 2-, and 1-channel captures.

## 2026-08-25 active-channel / A3 timing experiment

With the onboard 1 kHz square-wave reference and A3=0x11, measured periods were
100, 200, 400 and 800 samples with 8, 4, 2 and 1 active channels respectively.
This establishes approximately 800 ksample/s aggregate at A3=0x11, divided among
active channels, while the 8000-byte Triggered payload remains constant.

The reference implementation maps A3 to a 1-2-5 Triggered time/div ladder. Around
0x11 the adjacent faster settings are:

- 0x11 = 500 us/div
- 0x10 = 200 us/div
- 0x0F = 100 us/div
- 0x0E = 50 us/div

Use `tools/sweep_a3.py` with only the driven channel active to measure the actual
sample rate at each setting from square-wave edge spacing. Do not infer the rate
from time/div alone because the ADC may cap or otherwise change behavior at the
fastest settings.

## Fixed regression corpus: CH1-only A3 sweep (2026-08-25)

The original CH1-only onboard 1 kHz / 2 Vpp captures for A3 values `0x11`,
`0x10`, `0x0F`, and `0x0E` are preserved in `tests/fixtures/a3_1khz/` together
with capture metadata and transaction logs.

Direct analysis of transition-impulse clusters in the raw little-endian words
produces the following empirical anchors:

| A3 | median half-period | inferred sample rate |
|----|--------------------|----------------------|
| 11 | ~400 samples       | ~800 ksample/s       |
| 10 | ~400 samples       | ~800 ksample/s       |
| 0F | ~1200 samples      | ~2.4 Msample/s       |
| 0E | ~1200 samples      | ~2.4 Msample/s       |

The `0x10` result is intentionally preserved even though a simple time/div
model would predict a different rate: the raw captures show the same ~400
sample half-period as `0x11`.  Future protocol work must explain this rather
than silently normalizing it to the nominal timebase ladder.

For timing regression, `detect_delta_impulse_edges()` detects clusters of raw
excursions around the quiet code (~2001) and measures spacing between cluster
centres.  This avoids coupling established timing results to the still
experimental cumulative-delta waveform reconstruction, whose baseline can
wander when the quiet-code estimate is biased by a fraction of a count.

## Official Windows trigger-control evidence (2026-08-29)

Targeted captures from the official Hantek application refine several previously unknown startup/configuration commands:

- `AB hi lo` is the vertical trigger threshold, a big-endian 16-bit ADC-domain value.
- `AC [u16] [u24] [u24]` carries horizontal acquisition-window/trigger-position information; the two u24 fields partition the total horizontal window.
- `C1 00 xx` is the Edge-trigger slope/polarity control. Correlation against the recorded Windows UI chronology (`+ -> - -> + -> - ... -> +`) proves `C1 00 00` = `+` / rising and `C1 00 01` = `-` / falling.
- Trigger Sweep `Auto / Normal / Single` did not reveal a distinct new configuration opcode. Observed differences are consistent with host acquisition/re-arm policy; do not assign an unsupported sweep byte.
- Official Trigger mode remains active through 200 ms/div (`A3 19`); official Scan Mode starts at 500 ms/div (`A3 1A`) and uses the `C9/CA` transfer family while `A4 01` remains in use. This is distinct from the project's diagnostic `A4 02 + C7/C8` ROLL path.

The compressed USBPcap captures supporting these assignments are retained under `evidence/windows-usbpcap/20260829/`.



## Official Scan Mode Linux diagnostic (2026-08-29)

The Windows Trigger/Scan boundary capture proves that official Scan Mode starts
at 500 ms/div (`A3=1A`) and uses `A4 01` with the `C9/CA` transfer family.
Linux reproduction now refines the C9/CA model.

At A3=1A, an initial C9 value of 2992 was followed by one 64-byte CA transaction
and then C9=0.  Therefore C9 is **not** treated as a decrementing FIFO depth and
values above 64 have no proven sample-length semantics.  They are quarantined.
After startup, steady-state C9 values were 8, 10, 12, and 14 bytes.  In every
such case the next CA reply was 64 bytes: exactly the C9-sized prefix was data
and the rest was zero padding.  Immediate post-CA C9 was usually zero and once
4; that observation is retained but is not used as a continuation rule.

`tools/probe_official_scan.py` therefore keeps only C9<=64 prefixes in its
steady-state raw sample artifact, writes C9>64 CA replies to a separate
oversize-evidence artifact, verifies zero padding, records monotonic timing, and
provides an observational little-endian 12-bit word view.  It performs no
smoothing, thresholding, interpolation, integration, detrending, or waveform-
specific processing.  `DirectADCSession.acquire_words()` and the diagnostic
`A4 02 + C7/C8` ROLL path remain unchanged.

### Official Scan C9/CA candidate row evidence (2026-08-29)

Linux reproduction of the official Windows Scan path now shows a strong 4-byte
logical cadence for CH1-only C9/CA payloads: A3=1A ~398 candidate rows/s,
A3=1B ~199 rows/s, and A3=1C 99.717 rows/s.  The two little-endian 16-bit words
inside each 4-byte candidate row remain semantically unnamed (`word0`, `word1`)
until further evidence identifies their roles.  No canonical acquisition path
uses either word yet.

## AC A/B check at A3=11 (2026-08-29)

A controlled Python TRIGGERED experiment compared the project's historical final
`AC 00 00 00 00 01 00 05 79` (`0,1,1401`) with the official Windows A3=11
value `AC 00 00 00 00 01 00 13 89` (`0,1,5001`).  All other acquisition
settings were held constant: CH1 only, A3=11, A2=03, A4=01 and the same
reference guards.

Both settings reached A5 ready state normally and produced identical physical
buffer geometry: buffer 02 empty, buffer 03 exactly 8000 bytes, 125 x 64-byte
A6 reads, zero discarded tail.  This proves that the official AC value is
accepted, but it does **not** demonstrate a production benefit or establish
that samplerate-driven TRIGGERED must mirror the official application's horizontal
window mapping.  Do not change canonical AC programming from this experiment
alone.

## Scan candidate-row adjacency evidence (2026-08-29)

The neutral 4-byte Scan row model can be tested without assuming any waveform
shape by comparing the two alternating boundaries in the raw word stream:
`word0[n] -> word1[n]` and `word1[n] -> word0[n+1]`.

For the preserved A3=1C capture (`20260829T054750Z`), the within-row mean
absolute delta is 1.096 ADC counts and the across-row-boundary mean absolute
delta is 1.000 count.  Their medians are 1 and 0 respectively; 368/396
within-row deltas and 362/395 across-row deltas are <=1 count.  Correlation is
~0.99847 for `word0[n],word1[n]` and ~0.99912 for
`word1[n],word0[n+1]`.

The lack of a discontinuity at the 4-byte row boundary is evidence consistent
with `word0,word1` being an interleaved sequence of consecutive ADC-like
observations rather than a same-time value plus unrelated metadata.  It is not
yet sufficient to promote two samples per row into canonical acquisition: the
result must be repeated across multiple A3 values and a sufficiently varying
input, and the resulting effective sample-rate interpretation must be checked
against independent timing evidence.

`tools/analyze_scan_word_order.py` reports these alternating-boundary metrics
without waveform-dependent thresholds or automatic semantic classification.

## Scan temporal-order cross-rate evidence (2026-08-29)

A follow-up controlled-input experiment strengthened the interpretation of the
official `A4 01 + C9/CA` Scan 4-byte candidate row.  With CH1 grounded, A3=1A,
1B and 1C all showed the same sub-count-scale continuity across every adjacency
class (`word0->word1`, `word1->next-word0`, and same-position row steps), with
no persistent offset, inversion or separate value population between the two
word positions.  This is strong evidence that both words are measurements of
the same analogue input path rather than one sample plus unrelated metadata.

With CH1 driven by a 20 Hz sine through the ATR2x-USB audio output, the three
Scan rates gave the following mean absolute deltas:

- A3=1A, 398.170 rows/s: within 2.3285, across 2.3306, word0 row-step 4.4887,
  word1 row-step 4.5107 counts.
- A3=1B, 198.993 rows/s: within 4.4623, across 4.5069, word0 row-step 8.8793,
  word1 row-step 8.7044 counts.
- A3=1C, 99.124 rows/s: within 8.8992, across 8.8384, word0 row-step 16.3737,
  word1 row-step 16.4242 counts.

The alternating-boundary ratios (`across/within`) were 1.0009, 1.0100 and
0.9932 respectively.  Same-position row steps were approximately twice the
adjacent-word movement at all three rates.  This is strong waveform-agnostic
protocol evidence consistent with the temporal sequence
`word0[n], word1[n], word0[n+1], word1[n+1], ...` in official Scan mode.
The corresponding observation cadences are therefore approximately twice the
4-byte-row cadences (~796.3, ~398.0 and ~198.2 observations/s), but this
interpretation is still confined to the official C9/CA Scan transport until the
separate diagnostic C7/C8 ROLL transport is cross-checked directly.

`tools/analyze_roll_word_order.py` is provided for that C7/C8 cross-check.  It
reads the raw transport saved by `tools/capture_roll_adc.py`, treats both
16-bit row positions neutrally as 12-bit observations, and reports exactly the
same alternating-boundary metrics.  No canonical acquisition or reconstruction
path is changed by this diagnostic.

## C7/C8 ROLL word-role cross-check (2026-08-29)

The separate diagnostic `A4 02 + C7/C8` ROLL transport was tested directly so
that the official C9/CA Scan interpretation would not be transferred to it by
analogy.  Both 16-bit positions of each raw 4-byte ROLL row were preserved and
analysed with the same waveform-agnostic adjacency metrics used for Scan.

With CH1 driven from the ATR2x-USB output by a 20 Hz sine, the two row positions
behaved very differently:

- A3=1A (historical row rate 401/s): word0 row-step mean 30.0287 counts,
  word1 row-step mean 0.93375 counts.
- A3=1B (201/s): word0 row-step mean 59.6008 counts, word1 row-step mean
  1.19399 counts.
- A3=1C (100/s): word0 row-step mean 113.07 counts, word1 row-step mean
  1.6775 counts.

The changing word0 step grows as the row interval grows, as expected for the
same analogue waveform observed progressively more slowly.  In contrast,
word1 remains almost static.  The alternating word0/word1 separation is also
large and nearly rate-independent: mean absolute deltas are approximately
259 counts for both `word0[n] -> word1[n]` and
`word1[n] -> word0[n+1]` at all three A3 values.  This is not the structure
seen in official C9/CA Scan mode and is inconsistent with interpreting the
ROLL row as two consecutive CH1 observations.

A grounded-CH1 control at A3=1A provides an independent check.  The production
word0 lane collapsed to a 7-count span with a row-step mean of 0.6927 count.
Word1 was likewise individually stable (row-step mean 0.6458 count), but the
two positions remained separated by approximately 249 counts and had no useful
cross-correlation.  Thus both row positions can be quiet numeric quantities,
but they do not represent the same grounded ADC population.

These measurements support the existing canonical C7/C8 ROLL interpretation:
`word0` is the changing CH1 analogue observation used by the diagnostic ROLL
path, while `word1` is a distinct, still-unidentified device quantity.  Do not
call word1 metadata, status, or another channel without further evidence.  Do
not emit it as a second CH1 sample and do not double the historical ROLL
samplerates.  Canonical ROLL acquisition therefore remains unchanged.

This result also establishes that identical 4-byte transport geometry does not
imply identical row semantics: official C9/CA Scan and diagnostic C7/C8 ROLL
must continue to be described and decoded independently.

## Official Scan reference-path promotion (2026-08-29)

The Python protocol/reference path now exposes the official `A4 01 + C9/CA`
Scan row as two temporally ordered CH1 ADC-like observations.  The structural
decode is exactly:

`word0[n], word1[n], word0[n+1], word1[n+1], ...`

No sample values are averaged, selected, smoothed, thresholded, interpolated,
integrated, detrended, or otherwise waveform-processed.  The interpretation is
specific to official C9/CA Scan and must not be reused for the distinct C7/C8
ROLL row, whose word1 has independently been shown to have different semantics.

`scan_ch1_observations()` implements the evidence-backed flattening and
`scan_observation_rate()` reports two CH1 observations per measured 4-byte row.
`probe_official_scan.py` now records the decoded CH1 observation count and
observation throughput while retaining the row/word diagnostics for protocol
inspection.

A validation-only tool, `tools/analyze_scan_reference_tone.py`, checks a known
periodic stimulus against the flattened observation stream.  It uses the known
test signal only to validate timing and does not participate in acquisition or
waveform reconstruction.  The previously captured 20 Hz ATR2x-USB datasets at
A3=1A/1B/1C remain the intended hardware validation set before considering any
production libsigrok C9/CA implementation.

## Production handoff: official C9/CA Scan (2026-08-29)

After grounded-input, cross-rate adjacency, C7/C8 control, and reference-tone timing validation, the libsigrok production driver now has an official Scan implementation limited to the nine independently validated settings:

- A3=1A (official 500 ms/div): nominal 800 CH1 observations/s.
- A3=1B (official 1 s/div): nominal 400 CH1 observations/s.
- A3=1C (official 2 s/div): nominal 200 CH1 observations/s.
- A3=1D (official 5 s/div): nominal 80 CH1 observations/s.
- A3=1E (official 10 s/div): nominal 40 CH1 observations/s.
- A3=1F (official 20 s/div): nominal 20 CH1 observations/s.
- A3=20 (official 50 s/div): nominal 8 CH1 observations/s.
- A3=21 (official 100 s/div): nominal 4 CH1 observations/s.
- A3=22 (official 200 s/div): nominal 2 CH1 observations/s.

The production Scan path follows the same evidence-backed structural decode as this Python reference: stateful 4-byte framing across C9/CA transaction boundaries and temporal emission order `word0[n], word1[n], word0[n+1], word1[n+1], ...`. It performs no smoothing, averaging, interpolation, thresholding, detrending, integration, or waveform-specific reconstruction.

The C7/C8 ROLL path remains deliberately separate and word0-only. At the shared
public 2 Sa/s rate, the validated official Scan mapping now takes precedence;
the ROLL implementation remains intact but is no longer selected at 2 Sa/s.
The historical diagnostic ROLL rates `1, 5, 9, 23, 50, 100, 201, 401 Sa/s` are
also omitted from libsigrok's advertised PulseView list to avoid presenting two
rate families for the same official Scan timebase region. The retained public
non-Scan rates are 1003 and 2006 Sa/s in the official Trigger region and the two
validated TRIGGERED rates.

### Production hardware validation: A3=1A through A3=22

Official C9/CA Scan has now passed real-hardware validation at all nine exposed
production settings:

- A3=1A: 800 Sa/s (official 500 ms/div).
- A3=1B: 400 Sa/s (official 1 s/div).
- A3=1C: 200 Sa/s (official 2 s/div).
- A3=1D: 80 Sa/s (official 5 s/div).
- A3=1E: 40 Sa/s (official 10 s/div).
- A3=1F: 20 Sa/s (official 20 s/div).
- A3=20: 8 Sa/s (official 50 s/div).
- A3=21: 4 Sa/s (official 100 s/div).
- A3=22: 2 Sa/s (official 200 s/div).

Both `sigrok-cli` and PulseView reproduced the ATR2x-USB audio reference at each
setting: 20 Hz for A3=1A through 1D and 1 Hz for A3=1E through 21. At A3=1D,
`sigrok-cli` delivered exactly 800 samples at the advertised 80 Sa/s and the
emitted stream recovered exactly 20.000 Hz; PulseView showed the expected sparse
approximately four-sample-per-cycle trace. This validates the existing
production handoff without changing its waveform-agnostic structural decode or
authorizing any waveform-specific reconstruction.

For A3=1E/1F/20/21, the Python-first 1 Hz ATR2x-USB batch measured steady
observation cadences (excluding the queued startup packet) of 40.1103, 20.1001,
8.10128, and 4.10395 observations/s. The interleaved stream recovered the
reference at approximately 1 Hz, and grounded controls at every setting had
only 2--4 count spans with valid zero padding and no unhandled C9 event. The
larger initial A3=1F packet contained 12 queued startup rows and was retained as
observed rather than hidden or rewritten.

Production `sigrok-cli` then delivered exactly 800, 400, 160, and 80 samples at
40, 20, 8, and 4 Sa/s respectively. The unmodified emitted samples recovered
1.000000, 0.999702, 1.000000, and 1.000000 Hz. PulseView showed clean sine waves
at 40 and 20 Sa/s, a visibly coarse trace at 8 Sa/s, and the expected repeating
roughly triangular four-samples-per-cycle trace at 4 Sa/s. The latter validates
cadence and periodicity, not high-fidelity waveform shape.

For A3=22, a 60-second Python-first capture measured 1.899987 observations/s
and recovered a 0.2 Hz ATR2x-USB reference at 0.189999 Hz with an exact median
period of 10 observations. Valid CA padding, no oversize C9 event, and the
observed two-byte capture-end carry were preserved. The grounded control had a
four-count span, population standard deviation 0.7115 count, and similar
within-row/across-row mean absolute changes of 0.7407/0.7692 count.

The production selection was then changed from diagnostic `A3=21` ROLL to
official `A3=22` Scan at the public 2 Sa/s setting. A production `sigrok-cli`
capture delivered exactly 120 samples and recovered 0.200244 Hz. PulseView
showed the expected approximately ten-sample-per-cycle sine after its display
scale was manually changed from the initial 20 V/div to 2 V/div; that visual
scale change did not alter acquisition data or cadence.

### Ultra-slow Scan protocol/cadence validation: A3=23 through A3=28 (2026-08-29)

The remaining official Windows Scan profiles were exercised in the Python
protocol/reference path through the end of the known horizontal table. A3=23
used a 600-second capture; A3=24..28 were then run sequentially for 600, 900,
1500, 2500, and 5000 seconds respectively. CH1 was connected to the ATR2x-USB
audio output for these captures.

The C9/CA transport remained structurally unchanged across every profile:

| A3 | Official time/div | Nominal observation rate | Measured observation rate | Complete 4-byte rows | Final carry | Oversize CA |
|---:|---:|---:|---:|---:|---:|---:|
| `23` | 500 s/div | 0.8 Sa/s | 0.790 Sa/s | 237 | 2 B | 0 |
| `24` | 1000 s/div | 0.4 Sa/s | 0.390 Sa/s | 117 | 2 B | 0 |
| `25` | 2000 s/div | 0.2 Sa/s | 0.193 Sa/s | 87 | 2 B | 0 |
| `26` | 5000 s/div | 0.08 Sa/s | 0.076 Sa/s | 57 | 2 B | 0 |
| `27` | 10000 s/div | 0.04 Sa/s | 0.038 Sa/s | 47 | 2 B | 0 |
| `28` | 20000 s/div | 0.02 Sa/s | 0.019 Sa/s | 47 | 2 B | 0 |

In all six captures the first non-empty CA transaction carried a two-byte valid
prefix and steady transactions thereafter carried four-byte valid prefixes.
Padding was zero, no oversize CA transaction occurred, and byte accounting was
exact. For example, A3=28 produced one 2-byte prefix followed by 47 four-byte
prefixes: 190 bytes total, or 95 16-bit observations, represented at capture
end as 47 complete rows plus the expected two-byte stateful carry.

The regular four-byte CA arrival spacing progressed at approximately 2.5, 5,
10, 25, 50, and 100 seconds for A3=23..28. Since each complete Scan row contains
two temporally ordered observations, this corresponds to approximately 1.25,
2.5, 5, 12.5, 25, and 50 seconds per observation. This is strong hardware
evidence that A3=1A..28 form one continuous official C9/CA Scan family whose
acquisition cadence extends below 1 Hz.

The attempted 0.001 Hz reference waveform is deliberately **not** counted as
waveform-frequency validation. The ATR2x-USB audio output did not deliver a
meaningful near-DC sine at that frequency: the A3=28 ADC observations, for
example, occupied only 2027..2037 (10-count span, population standard deviation
approximately 2.34 counts) over the 5000-second run. The data therefore validate
protocol framing and cadence, not reproduction of the intended 0.001 Hz tone.
The quiet sequential differences remain consistent with the already-proven
Scan temporal ordering and show no C7/C8-like split between the two words, but
they are not used as new standalone proof of that interpretation.

A second hardware campaign then exercised A3=23..28 with **CH1 grounded** for
60, 90, 150, 300, 600, and 1200 seconds respectively. The grounded ADC remained
quiet across all six profiles: observed spans were only 2--4 counts, population
standard deviation was approximately 0.60--1.21 counts, and within-row versus
across-row adjacent differences remained in the same sub-count-to-about-one-count
noise regime. This provides a direct quiet-input control supporting the existing
interpretation that Scan rows contain two consecutive CH1 observations rather
than two different quantities.

The grounded captures also measured the steady four-byte CA periods directly at
approximately 2.5, 5, 10, 25, 50, and 100 seconds for A3=23..28. Because each
steady CA carries two observations, these correspond exactly to 1.25, 2.5, 5,
12.5, 25, and 50 seconds per observation, i.e. 0.8, 0.4, 0.2, 0.08, 0.04, and
0.02 Sa/s. The shorter grounded captures initially appeared to be three rows
short relative to duration, but raw timing shows this is a repeatable startup
pipeline effect: the first partial observation becomes available only after
roughly three steady CA periods. The steady-state cadence itself matches the
nominal fractional rates.

Framing remained exact in every grounded run: the first non-empty CA supplied a
2-byte valid prefix, later CA transactions supplied 4-byte valid prefixes, CA
padding was zero, no oversize CA occurred, and every capture ended with the
expected 2-byte carry. Together with the long-duration campaign, this closes the
hardware characterization of the official C9/CA Scan family through A3=28.

Production libsigrok support remains intentionally limited to A3=1A..22 until
the fractional-rate profiles can be represented honestly (for example through
timebase/sample-interval metadata where appropriate) rather than rounded or
faked as integer `SR_CONF_SAMPLERATE` values.

### Future viewer model for ultra-slow Scan: data logging / charting

The A3=23..28 profiles are better described operationally as slow continuous
data-logging or chart-recorder modes than as conventional oscilloscope sweep
rates. Their native observation periods are approximately 1.25, 2.5, 5, 12.5,
25, and 50 seconds respectively. That makes them suitable for long-duration
measurements such as battery charge/discharge, temperature or pressure trends,
slow sensor drift, and intermittent faults where preserving the time history is
more important than displaying a fast repetitive waveform.

The current PulseView timing path is samplerate-oriented and uses integer
`SR_CONF_SAMPLERATE` values as the normal stream timing basis. Therefore the
sub-1-Hz Hantek profiles should not be exposed by rounding 0.8, 0.4, 0.2, 0.08,
0.04, or 0.02 Sa/s into invented integer rates. A future generic PulseView
enhancement could instead accept a precise sample period/interval as the timing
basis for continuous analog data and render the result as a long-duration
chart. The desired model is conceptually a rational sample period, so intervals
such as 5/4 s, 5/2 s, and 25/2 s remain exact rather than being forced into
integer-second or integer-Hz representations.

This should be treated as a generic slow-instrument/viewer capability, not as a
Hantek-specific UI mode. The existing PulseView samplerate presentation for the
currently supported A3=1A..22 profiles remains appropriate and should not be
changed merely to mimic the Windows application's time/div selector.

### A3=1D Python-first Scan validation

The next official Scan setting, A3=1D (5 s/div), has now completed its
waveform-agnostic Python protocol/reference investigation. Two 10-second 20 Hz
ATR2x-USB captures measured 39.6869 and 39.6916 complete 4-byte rows/s, yielding
79.3738 and 79.3831 temporally ordered CH1 observations/s. The reference-tone
analyser recovered 19.8435 and 19.8458 Hz. The stronger repeat spanned 38 ADC
counts.

A separate grounded-CH1 control measured 39.5756 rows/s and 79.1512
observations/s. Its complete interleaved observation stream occupied only
2002..2006 (4 ADC counts) with a population standard deviation of 0.5892 count.
Within-row and across-row mean absolute changes were similarly small at 0.5429
and 0.4886 count respectively.

Across all three A3=1D captures, steady-state CA padding was zero and no
oversize C9 event occurred. Capture-end carry was preserved as observed (0 or
2 bytes), never padded or discarded. These results support a nominal 80 Sa/s
production Scan mapping for A3=1D while preserving the separate existing
50 Sa/s C7/C8 ROLL mapping at the same A3 selector.

Existing C7/C8 ROLL and C6/A6 TRIGGERED behaviour remain separate and unchanged.

## Linux hardware-trigger validation and frontend policy

Windows USBPcap evidence plus controlled Linux tests now establish the Trigger
state machine sufficiently for canonical use.  `AB hi lo` is the big-endian
16-bit ADC-domain trigger threshold, and the known Windows `+/-` toggle
chronology resolves `C1 00 00` as `+` / rising and `C1 00 01` as `-` / falling.

The decisive Linux arm sequence is:

```text
A4 01
C0
F3 / A5 5A polling
```

`C2` must **not** be sent immediately after `C0`.  With CH1 connected to a
1 kHz square wave and `AB=0860`, six of six captures reached A5 ready state 2
without C2, after approximately 112--126 ms.  With CH1 grounded and the same
USB configuration, zero of four captures became ready during a 1.2 s wait.  A
further grounded control remained in A5 state 0 for 10004.4 ms and completed
only after the diagnostic sent C2.  This proves that C0 arms a genuine hardware
trigger wait, A5 state 0 is the waiting state, A5 state 2 is a completed/ready
state, and C2 is a forced-completion action rather than part of initial arming.

The canonical Python direct-Triggered path therefore implements two frontend
policies:

- **Auto/free-running** (`trigger_enabled=False`): arm with C0, poll A5 for the
  host-side Auto timeout (default 1870 ms, matching the observed official-app
  cadence), then send C2 only if no genuine trigger completed the acquisition.
- **Normal** (`trigger_enabled=True`): arm with C0 and poll A5 indefinitely.
  There is no timeout C2.  Re-arming after a completed frame is a caller/frontend
  policy.

The official application also exposes **Single**, but no dedicated USB sweep
selector has been proven.  Single is therefore retained as a host-side one-shot
re-arm policy, not exposed as a distinct device command in the canonical Python
API.

For libsigrok/PulseView integration, do not invent a Hantek-specific
Auto/Normal/Single control.  Existing frontend semantics map naturally: no
frontend trigger configured -> Auto/free-running; a rising/falling trigger
configured -> Normal-style indefinite hardware wait and re-arm while Run
remains active.  Ordinary Run is not interpreted as Single.  Single remains a
documented capability for possible future generic one-shot support.

The 1 kHz square wave and grounded input are validation controls only.  No
waveform-specific thresholding, alignment, smoothing, or reconstruction is
introduced into the canonical sample path.

