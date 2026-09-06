# Hantek 1008C Trigger, Scan, and Roll acquisition

## Terminology

The official Hantek Windows application calls the finite C6/A6 acquisition family **Triggered**. Earlier driver revisions called this family **BURST** while its protocol role was still being established. The driver now uses **Triggered** for that family; this is a terminology cleanup only and does not change the C6/A6 acquisition protocol. **Scan** remains the official C9/CA streaming family, while the separate diagnostic C7/C8 **ROLL** path remains distinct.

## Observed acquisition mechanisms

The Hantek 1008C has three independently observed acquisition/transfer mechanisms
relevant to this driver. The finite C6/A6 Triggered family, official C9/CA Scan
family, and separate C7/C8 Roll family are implemented in the production driver
for one through eight enabled channels.

**TRIGGERED mode** is a finite, triggered/swept acquisition. The scope is armed, a block of
samples is captured into hardware memory, the completed frame is transferred to the
host, and the scope is then re-armed for another acquisition.

This is the digital equivalent of a traditional triggered CRT oscilloscope. A classic
CRT scope waits for a trigger, sweeps the beam from left to right, then retraces/resets
before the next sweep. The retrace interval is not part of the displayed waveform.
Likewise, the Hantek's time between TRIGGERED frames is dead time: it was not sampled and
must never be filled with invented samples.

With one active channel the Hantek has a 4K-sample TRIGGERED memory. Repeated 4K frames can
therefore look "live" in a frontend, just as repeated CRT sweeps look continuous to the
eye, but the frames are still separate acquisitions.

**ROLL mode** is the continuous low-rate `A4 02 + C7/C8` path.
The device reports the number of available bytes with `C7` and the host drains them
with `C8`. There is no 4K sweep boundary defining the trace. This behaves more like a
strip-chart recorder: new samples continuously arrive and are appended to the timeline.
It is a useful validated low-rate transport, but it is not the official Hantek Windows
application's Scan Mode.

**Official Scan Mode** is used by the Windows application from 500 ms/div (`A3=1A`)
and slower. It keeps `A4 01` and transfers a continuous byte stream using `C9/CA`.
The production driver exposes the independently validated `A3=1A` through `22`
settings as 800, 400, 200, 80, 40, 20, 8, 4, and 2 Sa/s respectively. The two words in each 4-byte row
are emitted as successive CH1 observations in their evidence-backed temporal order.

## Sample-rate and waveform guidance

The "comfortable maximum frequency" values below are deliberately more conservative
than Nyquist. They are intended for a useful oscilloscope display, not merely for
detecting that a signal exists.

- Sine: approximately 10 samples/cycle or better.
- Square: approximately 20 samples/cycle or better.
- The Hantek's 100 kHz analog bandwidth also limits usable waveform content.
- For square waves, the table caps the fundamental near 20 kHz so useful low-order
  harmonics can still fit inside the 100 kHz analog front end.

These are engineering guidance values, not manufacturer guarantees.

## Relevant TRIGGERED A3 / timebase / rate mapping

A3 is the horizontal acquisition selector. Its nominal time/div value and the actual
ADC sample rate are related but are not identical concepts; adjacent A3 values can
share the same measured sample rate.

| A3 | Nominal time/div | Validated one-channel rate | Notes |
|---:|---:|---:|---|
| `0x0E` | 50 us/div | 2.4 MSa/s | validated Python mapping |
| `0x0F` | 100 us/div | 2.4 MSa/s | canonical 2.4 MSa/s selector |
| `0x10` | 200 us/div | 800 kSa/s | validated Python mapping |
| `0x11` | 500 us/div | 800 kSa/s | canonical 800 kSa/s selector |

A full 4K frame at 800 kSa/s contains 5.000 ms of sampled time. A ~1 kHz square wave
therefore produces about five complete cycles in one frame, which has been confirmed
on hardware.

A full 4K frame at 2.4 MSa/s contains about 1.667 ms of sampled time.

## ROLL rate mapping

For one active channel:

| A3 | Rate | Approx. sample interval |
|---:|---:|---:|
| `0x22` | 1 Sa/s | 1.000 s |
| `0x21` | 2 Sa/s | 0.500 s |
| `0x20` | 5 Sa/s | 0.200 s |
| `0x1F` | 9 Sa/s | 0.111 s |
| `0x1E` | 23 Sa/s | 43.5 ms |
| `0x1D` | 50 Sa/s | 20.0 ms |
| `0x1C` | 100 Sa/s | 10.0 ms |
| `0x1B` | 201 Sa/s | 4.98 ms |
| `0x1A` | 401 Sa/s | 2.49 ms |
| `0x19` | 1.003 kSa/s | 0.997 ms |
| `0x18` | 2.006 kSa/s | 0.499 ms |

The 2.006 kSa/s, 1.003 kSa/s, 401 Sa/s and 201 Sa/s points have been checked on
hardware with a 50 Hz sine. The observed progression was approximately 40, 20, 8 and
4 samples/cycle respectively.

## Comfortable waveform-frequency table

### TRIGGERED

| Rate | 4K sampled span | Comfortable sine | Comfortable square |
|---:|---:|---:|---:|
| 800 kSa/s | 5.000 ms | ~80 kHz | ~20 kHz |
| 2.4 MSa/s | 1.667 ms | ~100 kHz* | ~20 kHz* |

`*` limited primarily by the 100 kHz analog front end rather than sample rate.

### ROLL

| Rate | Comfortable sine | Comfortable square |
|---:|---:|---:|
| 1 Sa/s | ~0.1 Hz | ~0.05 Hz |
| 2 Sa/s | ~0.2 Hz | ~0.1 Hz |
| 5 Sa/s | ~0.5 Hz | ~0.25 Hz |
| 9 Sa/s | ~0.9 Hz | ~0.45 Hz |
| 23 Sa/s | ~2.3 Hz | ~1.15 Hz |
| 50 Sa/s | ~5 Hz | ~2.5 Hz |
| 100 Sa/s | ~10 Hz | ~5 Hz |
| 201 Sa/s | ~20 Hz | ~10 Hz |
| 401 Sa/s | ~40 Hz | ~20 Hz |
| 1.003 kSa/s | ~100 Hz | ~50 Hz |
| 2.006 kSa/s | ~200 Hz | ~100 Hz |

## Interpretation rules

1. Never join TRIGGERED frames by inventing samples for acquisition dead time.
2. Never alter samples based on knowing the expected waveform shape.
3. Test sine and square waves are validation signals, not reconstruction hints.
4. Nyquist is not the same as a comfortable oscilloscope display limit.
5. Any proven acquisition/protocol change must be checked in both the Python reference
   implementation and the libsigrok production driver.

## libsigrok implementation status

This document belongs to the libsigrok Hantek 1008C production driver.

The driver exposes acquisition family through the standard
`SR_CONF_DEVICE_MODE` string option. PulseView presents `Trigger`, `Scan`, and
`Roll`; its samplerate selector contains only values valid for the selected
family and current enabled-channel set. For one enabled channel:

| Device mode | CH1 samplerates |
|---|---|
| Trigger | 2, 4, 8, 20, 40, 80, 200, 400, 800 kSa/s; 2.4 MSa/s |
| Scan | 2, 4, 8, 20, 40, 80, 200, 400, 800 Sa/s |
| Roll | 1, 5, 9, 23, 50, 100, 201, 401, 1003, 2006 Sa/s |

Changing mode selects the fastest valid rate in that family, after which the
user may choose another family-specific rate. Enabling or disabling channels
retains the selected mode and selects a valid effective rate for the new
geometry. The complete count-dependent Trigger, Scan, and Roll lists and their
hardware evidence are documented in the multichannel sections below.

### TRIGGERED representation in sigrok

Each physical TRIGGERED acquisition is represented as a real sigrok frame:

`FRAME_BEGIN -> ANALOG samples -> FRAME_END`

Successive 4K frames are separate sweeps. They are intentionally not made contiguous
with synthetic gap samples. PulseView can refresh successive frames quickly enough to
look like a moving/live oscilloscope, but 800 kSa/s and 2.4 MSa/s remain TRIGGERED mode.

Canonical TRIGGERED selectors are:

| Rate | A3 |
|---:|---:|
| 800 kSa/s | `0x11` |
| 2.4 MSa/s | `0x0F` |

The 800 kSa/s path requires the selected A3 value to be established during the full
direct-ADC initialization. Re-sending A3 immediately before each `A4 01` arm was found
to disturb acquisition state and corrupt the latter part of the frame. With A3 moved
into the initialization path, the full 4K / 5 ms frame is clean.

### ROLL representation in sigrok

ROLL uses the continuous `C7`/`C8` transport. C7 reports the number of bytes currently
ready and repeated C8 transactions drain those bytes. ROLL samples are sent as a
continuous analog stream and are not wrapped in TRIGGERED frame markers.

The 2.006 kSa/s, 1.003 kSa/s, 401 Sa/s and 201 Sa/s rates were validated using a 50 Hz
sine signal and produced the expected samples-per-cycle progression.

## Sample limits in TRIGGERED mode

`SR_CONF_LIMIT_SAMPLES` is an aggregate session limit, but a Hantek TRIGGERED is a
physical 4K acquisition frame. The driver therefore never truncates the final
physical TRIGGERED frame to hit a non-multiple-of-4000 sample limit exactly.

Examples:

| Requested sample limit | TRIGGERED frames delivered | Samples delivered |
|---:|---:|---:|
| 1,000 | 1 | 4,000 |
| 4,000 | 1 | 4,000 |
| 5,000 | 2 | 8,000 |
| 10,000 | 3 | 12,000 |
| 20,000 | 5 | 20,000 |

This preserves physical sweep integrity and prevents a frontend from displaying a
shortened final sweep. ROLL mode is continuous and may stop exactly at the requested
sample count. For TRIGGERED acquisition, `limit_frames` is the natural control when an
exact number of sweeps is required.

### PulseView sample-count normalization

PulseView uses `SR_CONF_LIMIT_SAMPLES` not only as a stop condition but also as the
capture size it expects to retain/display. In TRIGGERED mode the driver therefore rounds
a non-zero requested sample limit **up to the next complete 4000-sample frame at
configuration time**, and reports that effective value back through
`SR_CONF_LIMIT_SAMPLES`.

Examples: 5K -> 8K, 10K -> 12K, 20K -> 20K.

This is in addition to never truncating packets at the session bus. ROLL mode keeps
the exact requested sample limit because it is a true continuous stream.

## Official Windows timebase / trigger evidence

| UI time/div | A3 | Official regime | transfer family |
|---:|---:|---|---|
| 100 ms | `0x18` | Trigger | C6/A6 |
| 200 ms | `0x19` | Trigger | C6/A6 |
| 500 ms | `0x1A` | Scan Mode | C9/CA |
| 1 s | `0x1B` | Scan Mode | C9/CA |

The official application still uses `A4 01` in the observed C9/CA Scan Mode. Therefore
the driver's existing low-rate `A4 02 + C7/C8` ROLL implementation is a different
mechanism and must not be renamed or treated as official Scan Mode.

### Startup A3 synchronization

The Python C7/C8 ROLL reference path performs the complete startup/final
configuration using the selected low-rate A3 value and then sends that same A3
again immediately before the `A4 02` ROLL arm sequence.  libsigrok now mirrors
that validated flow.  It no longer substitutes `A3=0F` during full startup when
a low-rate ROLL samplerate was selected.

This is an existing-flow synchronization fix; it does not enable official
`C9/CA` Scan Mode and it does not change TRIGGERED sequencing.

### Linux C9/CA Scan validation

The Python protocol-laboratory path now independently reproduces the official
`A4 01 + C9/CA` Scan transport on Linux. The following framing rules are supported by
repeated hardware captures:

- In steady state, `C9` values from 1 through 64 specify the valid prefix length of the
  following fixed 64-byte `CA` response. Bytes after that prefix are zero padding.
- Occasional startup `C9` values greater than 64 have different/unknown semantics.
  They are quarantined and are not interpreted as a FIFO byte count or sample data.
- USB `CA` transaction boundaries are transport boundaries only. A stateful framer
  carries 0 through 3 bytes between responses and emits only complete neutral 4-byte
  candidate rows. Capture-end carry is preserved verbatim; it is never padded or
  discarded.
- A candidate row consists of two little-endian 16-bit values, currently named
  `word0` and `word1`. Their exact temporal/device semantics are deliberately not yet
  assigned.

Three-point cadence validation with the same CH1 configuration gives:

| A3 | Official time/div | Candidate 4-byte rows/s | Capture-end carry |
|---:|---:|---:|---:|
| `0x1A` | 500 ms/div | 397.194 | 0 B |
| `0x1B` | 1 s/div | 198.649 | 0 B |
| `0x1C` | 2 s/div | 99.173 | 2 B |

The approximately 400/200/100 row/s progression closely matches the independently
measured `C7/C8` low-rate cadence at the same A3 values (about 401/201/100 per second).
This strongly supports 4-byte logical row framing for the tested CH1-only Scan stream,
while not proving what one row should mean as a libsigrok analogue sample.

For an `A3=1C` capture of the onboard test signal, `word0` spanned 1998..2202 and
`word1` 1999..2201 ADC-like counts. The mean absolute within-row difference was about
1.096 counts and the maximum was 66 counts. This strongly indicates related analogue
observations rather than unrelated metadata, but is not sufficient to choose one word,
average them, or emit two samples per row in the production driver.

Accordingly, the proven C9/CA transport/framing findings are documented here, but the
production acquisition code intentionally remains unchanged until `word0`/`word1`
semantics and the correct libsigrok sample representation are established in the
waveform-agnostic Python reference path.

The same official captures establish these trigger controls:

- `AB hi lo`: vertical trigger threshold, big-endian 16-bit ADC-domain value.
- `AC [u16] [u24] [u24]`: horizontal acquisition-window / trigger-position data; the u24 pair partitions the total horizontal window.
- `C1 <source> <slope>`: Edge-trigger source/slope. The 2026-08-29 CH1-only chronology proves second byte `00` = `+` / rising and `01` = `-` / falling; the 2026-08-30 multi-channel corpus proves zero-based first-byte source numbering through CH5 (`00`..`04`).
- Trigger Sweep `Auto / Normal / Single`: no dedicated new configuration opcode was proven; observed behaviour is consistent with host acquisition/re-arm policy. Do not invent a sweep selector byte.

Controlled Linux tests then establish the arm/wait state machine. The correct
initial sequence is `A4 01 -> C0`, followed by repeated `F3 / A5 5A` polling;
`C2` must not be sent immediately after `C0`. With CH1 connected to a 1 kHz
square wave and `AB=0860`, six of six captures reached A5 state 2 naturally in
about 112--126 ms. With CH1 grounded and the same USB configuration, zero of
four captures reached ready during 1.2 s, and a further grounded control stayed
in A5 state 0 for 10004.4 ms until C2 was deliberately sent. This proves:

- `C0` arms a genuine hardware-trigger wait;
- A5 state 0 is waiting and A5 state 2 is completed/ready;
- `C2` is a forced-completion action, not part of initial arming.

For production libsigrok/PulseView integration, the agreed frontend mapping is:

- no frontend trigger configured -> **Auto/free-running**: wait for a genuine
  trigger up to the host Auto timeout, then use C2 only to force completion and
  re-arm;
- rising/falling trigger configured -> **Normal**: wait indefinitely with no
  timeout C2, deliver the genuine triggered frame, then re-arm while Run remains
  active;
- ordinary Run is **not** interpreted as Single. The official Single capability
  remains documented for possible future generic one-shot support rather than a
  Hantek-specific frontend control.

These findings do not authorize waveform-specific cleanup, smoothing,
interpolation, or changes to canonical direct-ADC reconstruction. Production
code should be changed only by deliberately promoting the proven Python
reference semantics.

### AC A/B result at A3=11

A controlled Python TRIGGERED A/B test compared the driver's historical final AC
value `0,1,1401` with the official Windows A3=11 value `0,1,5001`, while
holding CH1/A2/A3/A4 and the acquisition sequence constant.  Both settings
reached ready state and returned the same physical acquisition geometry:
buffer 02 empty, buffer 03 8000 bytes, 125 complete A6 packets and no trailing
bytes.  This confirms that the official value is accepted but does not prove
that samplerate-driven TRIGGERED should reproduce the official UI's AC mapping.
The production AC value therefore remains unchanged pending evidence of a
functional requirement.

### Scan word0/word1 adjacency evidence

Waveform-agnostic adjacency analysis of the preserved A3=1C official C9/CA
Scan capture compares `word0[n] -> word1[n]` with the row-boundary transition
`word1[n] -> word0[n+1]`.  Mean absolute deltas are about 1.096 and 1.000 ADC
counts respectively, with very similar <=1-count populations and correlations
of about 0.9985 and 0.9991.  There is therefore no observed numerical
continuity break at the 4-byte row boundary.

This is evidence consistent with the two words forming consecutive ADC-like
observations in an interleaved stream, rather than one analogue value plus
unrelated metadata.  It is not yet a production decoding rule.  In particular,
the driver must not emit two samples per row, average the words, or otherwise
reinterpret C7/C8 or C9/CA until the result is repeated across rates and its
effective timing is reconciled with independent sample-rate measurements.

### Official Scan temporal-order cross-rate evidence (2026-08-29)

Controlled Python protocol-lab tests now provide stronger evidence for the
4-byte official `A4 01 + C9/CA` Scan row.  With CH1 grounded, A3=1A, 1B and 1C
showed no persistent separation between word0 and word1: all alternating and
same-position adjacency classes collapsed to the same small ADC-noise regime.
With CH1 driven by a 20 Hz sine, `word0[n] -> word1[n]` and
`word1[n] -> word0[n+1]` had essentially identical mean absolute deltas at all
three rates, while `word0[n] -> word0[n+1]` and `word1[n] -> word1[n+1]` were
approximately twice as large.

Measured Scan row rates and alternating-boundary results were:

- A3=1A: 398.170 rows/s; within 2.3285 counts, across 2.3306 counts.
- A3=1B: 198.993 rows/s; within 4.4623 counts, across 4.5069 counts.
- A3=1C: 99.124 rows/s; within 8.8992 counts, across 8.8384 counts.

This is strong evidence consistent with a temporal Scan sequence
`word0[n], word1[n], word0[n+1], word1[n+1], ...`, implying approximately two
ADC-like observations per 4-byte Scan row.  Do not transfer that interpretation
to the production C7/C8 ROLL decoder yet: the C7/C8 transport must be tested
independently with both raw row words preserved.  Production sample-rate
mapping and emission remain unchanged pending that cross-check.

### C7/C8 ROLL word-role cross-check (2026-08-29)

The C9/CA Scan temporal interpretation was cross-checked directly against the
separate diagnostic `A4 02 + C7/C8` ROLL transport rather than being transferred
by analogy.  Raw 4-byte ROLL rows were preserved with both 16-bit positions and
analysed with the same neutral adjacency metrics.

With CH1 driven by a 20 Hz sine, word0 followed the changing analogue input
while word1 remained nearly static.  Mean same-position row deltas were:

- A3=1A (401 rows/s): word0 30.0287 counts, word1 0.93375 counts.
- A3=1B (201 rows/s): word0 59.6008 counts, word1 1.19399 counts.
- A3=1C (100 rows/s): word0 113.07 counts, word1 1.6775 counts.

At all three rates the alternating word0/word1 boundaries were separated by
about 259 counts, rather than showing the equal adjacent temporal spacing seen
in C9/CA Scan.  A grounded-CH1 A3=1A control then reduced the word0 row-step to
0.6927 count and word1 row-step to 0.6458 count, while the two row positions
remained separated by about 249 counts.

This is strong evidence that C7/C8 word0 and word1 have different semantics.
The existing production ROLL path therefore remains correct to emit word0 only;
word1 must not be treated as a second consecutive CH1 sample and the historical
ROLL samplerates must not be doubled.  Word1 remains deliberately unnamed
beyond "word1" because the current evidence does not establish whether it is
metadata, status, another analogue quantity, or something else.

The result also confirms that C9/CA Scan and C7/C8 ROLL can share 4-byte row
geometry while carrying different row semantics.  Production acquisition is
unchanged by this documentation update.

### Python Scan reference-path promotion (2026-08-29)

The evidence-backed Python protocol/reference path now decodes official
`A4 01 + C9/CA` Scan rows as the temporal CH1 sequence
`word0[n], word1[n], word0[n+1], word1[n+1], ...` and reports an observation
cadence of two CH1 observations per measured 4-byte row.  This promotion is
confined to the Python Scan reference path; it does not change the libsigrok
production driver.

The decode is structural only and performs no waveform-specific cleanup,
smoothing, thresholding, interpolation, averaging, integration or detrending.
A validation-only Python reference-tone analyzer is used to check the existing
20 Hz ATR2x-USB Scan captures against the resulting observation cadence before
any C9/CA production implementation is considered here.

Do not transfer this two-observation rule to C7/C8 ROLL.  Direct C7/C8 testing
has already established different word semantics, and production ROLL remains
word0-only at the existing historical samplerates.

### Initial production C9/CA Scan implementation (2026-08-29)

The production driver now has a deliberately narrow official Scan path for the
nine independently validated settings only:

| libsigrok samplerate | A3 | Official time/div | Transport |
|---:|---:|---:|---|
| 800 Sa/s | `0x1A` | 500 ms/div | `A4 01 + C9/CA` Scan |
| 400 Sa/s | `0x1B` | 1 s/div | `A4 01 + C9/CA` Scan |
| 200 Sa/s | `0x1C` | 2 s/div | `A4 01 + C9/CA` Scan |
| 80 Sa/s | `0x1D` | 5 s/div | `A4 01 + C9/CA` Scan |
| 40 Sa/s | `0x1E` | 10 s/div | `A4 01 + C9/CA` Scan |
| 20 Sa/s | `0x1F` | 20 s/div | `A4 01 + C9/CA` Scan |
| 8 Sa/s | `0x20` | 50 s/div | `A4 01 + C9/CA` Scan |
| 4 Sa/s | `0x21` | 100 s/div | `A4 01 + C9/CA` Scan |
| 2 Sa/s | `0x22` | 200 s/div | `A4 01 + C9/CA` Scan |

The advertised Scan rates are nominal observation rates.  Repeated host-side
measurements saw about 398/199/99/40 four-byte rows per second, and the validated
row interpretation provides two temporally ordered CH1 observations per row.
A 20 Hz reference-tone check recovered 19.92/19.90/19.82 Hz across A3=1A/1B/1C
and 19.843/19.846 Hz in two A3=1D Python captures when the interleaved stream was
interpreted at twice the measured row cadence.

Scan startup mirrors the evidence-backed Python reference sequence: selected
A3, official Scan AC `0,1,1`, `F3`, `A4 01`, `E4 01`, `E6 01`, `C0`, about
1.87 seconds of repeated `F3/A5` observation, then `C2`.  Steady-state reads use
`F3`, `A5 5A`, `C9`, and exactly one fixed 64-byte `CA` transaction when C9 is
non-zero.  C9 values 1..64 select the valid CA prefix.  Values above 64 remain
quarantined as unresolved startup/oversize conditions and are not emitted.

The Scan decoder keeps a 0..3 byte carry across CA transaction boundaries and
emits complete rows only.  A complete row is decoded structurally as
`word0, word1`, producing the temporal sequence
`word0[n], word1[n], word0[n+1], word1[n+1], ...`.  No averaging, smoothing,
interpolation, thresholding, detrending or waveform-specific processing is
performed.

The existing diagnostic `A4 02 + C7/C8` ROLL implementation remains preserved
internally at its historical word0-only samplerates. Those legacy rates are not
advertised to PulseView because official Scan is now the public path throughout
the validated 500 ms/div-and-slower region. Direct 20 Hz and grounded-input
testing established that C7/C8 has different word semantics, so its historical
rates are not reinterpreted or doubled.
Official Scan takes precedence at the public 2 Sa/s setting, so the historical
`A3=21` ROLL mapping is no longer selected there; the ROLL implementation itself
is unchanged.

### Production hardware validation

Official C9/CA Scan has passed real-hardware validation at all nine currently
exposed production settings:

| Rate | A3 | Official time/div | Validation |
|---:|---:|---:|---|
| 800 Sa/s | `0x1A` | 500 ms/div | `sigrok-cli` and PulseView |
| 400 Sa/s | `0x1B` | 1 s/div | `sigrok-cli` and PulseView |
| 200 Sa/s | `0x1C` | 2 s/div | `sigrok-cli` and PulseView |
| 80 Sa/s | `0x1D` | 5 s/div | `sigrok-cli` and PulseView |
| 40 Sa/s | `0x1E` | 10 s/div | `sigrok-cli` and PulseView |
| 20 Sa/s | `0x1F` | 20 s/div | `sigrok-cli` and PulseView |
| 8 Sa/s | `0x20` | 50 s/div | `sigrok-cli` and PulseView |
| 4 Sa/s | `0x21` | 100 s/div | `sigrok-cli` and PulseView |
| 2 Sa/s | `0x22` | 200 s/div | `sigrok-cli` and PulseView |

Each check used the ATR2x-USB audio output: a 20 Hz reference for A3=1A through
1D and a 1 Hz reference for A3=1E through 21. Both were reproduced at the
expected cadence. The checks validate the existing waveform-agnostic production
decode; they do not introduce smoothing, averaging, interpolation, thresholding,
or other waveform-specific reconstruction.

At A3=1D, two Python reference captures measured 79.374 and 79.383 observations/s
and recovered 19.843 and 19.846 Hz. A grounded control measured 79.151
observations/s with a four-count span. The production `sigrok-cli` capture then
delivered exactly 800 samples at the advertised 80 Sa/s and recovered exactly
20.000 Hz; PulseView showed the expected sparse approximately four-sample-per-cycle
trace.

The Python-first A3=1E/1F/20/21 batch used a 1 Hz ATR2x-USB reference and
measured steady observation cadences of 40.1103, 20.1001, 8.10128, and 4.10395
observations/s after excluding each profile's queued startup packet. Grounded
controls had only 2--4 count spans, valid zero padding, and no unhandled C9
event. Production `sigrok-cli` delivered exactly 800, 400, 160, and 80 samples
at 40, 20, 8, and 4 Sa/s and recovered 1.000000, 0.999702, 1.000000, and
1.000000 Hz without altering sample values. PulseView showed clean sine waves
at 40 and 20 Sa/s, a coarse trace at 8 Sa/s, and an expected repeating roughly
triangular four-samples-per-cycle trace at 4 Sa/s. This validates cadence and
periodicity at the lowest rate, not high-fidelity waveform shape.

At A3=22, the Python-first capture measured 1.899987 observations/s and
recovered a 0.2 Hz ATR2x-USB reference at 0.189999 Hz with an exact median
period of 10 observations. Its grounded control had a four-count span and
0.7115-count population standard deviation; padding was valid and no oversize
C9 event occurred. Production `sigrok-cli` then delivered exactly 120 samples
at 2 Sa/s and recovered 0.200244 Hz. PulseView showed the expected roughly
ten-sample-per-cycle sine after its display scale was manually changed from the
initial 20 V/div to 2 V/div. Display scaling did not alter acquisition data.

### Ultra-slow Python protocol/cadence validation: A3=23 through A3=28 (2026-08-29)

The Python protocol/reference path has now exercised every remaining official
Windows Scan profile through A3=28. A3=23 used a 600-second capture; A3=24..28
used 600, 900, 1500, 2500, and 5000 seconds respectively. CH1 was connected to
the ATR2x-USB audio output. These are protocol/cadence validations, not yet
production libsigrok or PulseView validations.

| A3 | Official time/div | Nominal observation rate | Measured observation rate | Complete rows | Final carry | Oversize CA |
|---:|---:|---:|---:|---:|---:|---:|
| `0x23` | 500 s/div | 0.8 Sa/s | 0.790 Sa/s | 237 | 2 B | 0 |
| `0x24` | 1000 s/div | 0.4 Sa/s | 0.390 Sa/s | 117 | 2 B | 0 |
| `0x25` | 2000 s/div | 0.2 Sa/s | 0.193 Sa/s | 87 | 2 B | 0 |
| `0x26` | 5000 s/div | 0.08 Sa/s | 0.076 Sa/s | 57 | 2 B | 0 |
| `0x27` | 10000 s/div | 0.04 Sa/s | 0.038 Sa/s | 47 | 2 B | 0 |
| `0x28` | 20000 s/div | 0.02 Sa/s | 0.019 Sa/s | 47 | 2 B | 0 |

Every capture retained the same C9/CA framing semantics: the first non-empty CA
transaction supplied a two-byte valid prefix, steady transactions supplied
four-byte valid prefixes, padding was zero, and no oversize CA transaction was
observed. At A3=28, for example, one 2-byte prefix plus 47 four-byte prefixes
produced exactly 190 bytes = 95 16-bit observations = 47 complete rows plus a
two-byte capture-end carry.

Regular four-byte CA arrivals were approximately 2.5, 5, 10, 25, 50, and 100
seconds apart for A3=23..28, corresponding to approximately 1.25, 2.5, 5, 12.5,
25, and 50 seconds per observation. This supports one continuous official C9/CA
Scan family from A3=1A through A3=28 and confirms that the final profiles are
genuinely fractional-Hz acquisitions.

The attempted 0.001 Hz ATR2x-USB reference is **not** treated as waveform
validation. The audio output did not produce a meaningful near-DC reference;
for example, A3=28 occupied only ADC codes 2027..2037 (10-count span, population
standard deviation approximately 2.34 counts) during the 5000-second run. The
run therefore establishes framing and cadence only. Its quiet sequential
differences are consistent with the already-established Scan temporal ordering
and do not show the distinct word split previously observed in diagnostic
C7/C8 ROLL.

A second Python hardware campaign then exercised A3=23..28 with **CH1 grounded**
for 60, 90, 150, 300, 600, and 1200 seconds respectively. The grounded ADC
remained quiet across all profiles: spans were only 2--4 counts, population
standard deviation was approximately 0.60--1.21 counts, and within-row and
across-row adjacent differences stayed in the same small-noise regime. This is a
useful quiet-input control for the existing interpretation that each Scan row
contains two consecutive observations of the same analog input.

Raw host timing from the grounded captures measured the steady four-byte CA
periods at approximately 2.5, 5, 10, 25, 50, and 100 seconds for A3=23..28.
Since each steady CA contains two observations, the hardware therefore confirms
sample periods of 1.25, 2.5, 5, 12.5, 25, and 50 seconds, exactly matching the
nominal 0.8, 0.4, 0.2, 0.08, 0.04, and 0.02 Sa/s rates. Short captures are
consistently about three rows short relative to simple duration/rate arithmetic;
inspection of the raw timing shows a repeatable startup pipeline latency of
approximately three steady CA periods before the first partial observation is
available. The steady-state cadence itself is not slow by that amount.

Grounded framing remained exact throughout: the first non-empty CA carried a
2-byte valid prefix, later CA transactions carried 4-byte valid prefixes, CA
padding was zero, no oversize CA occurred, and captures ended with the expected
2-byte carry. Together with the longer campaign, this closes Python hardware
characterization of the official C9/CA Scan family through A3=28.

Production Scan remains limited to A3=1A..22 while the correct libsigrok
representation of rates below 1 Hz is resolved. Do not round or otherwise fake
these profiles as integer `SR_CONF_SAMPLERATE` values; investigate timebase
and/or sample-interval semantics instead. Existing C7/C8 ROLL and C6/A6 TRIGGERED
behaviour remain unchanged.

### Future PulseView enhancement: ultra-slow data logging / charting

The official Hantek Scan profiles below 1 Hz are a natural fit for a generic
data-logging or chart-recorder presentation in PulseView. A3=23..28 correspond
to nominal observation rates of 0.8, 0.4, 0.2, 0.08, 0.04, and 0.02 Sa/s, or
approximately one observation every 1.25, 2.5, 5, 12.5, 25, and 50 seconds. At
the slowest setting (`A3=0x28`, 20000 s/div), a ten-division horizontal record
represents roughly 200000 seconds (about 55.6 hours), which is much closer to a
chart recorder or data logger than to a conventional oscilloscope sweep.

These modes can therefore be useful for long-duration analog trends such as
battery charge/discharge, temperature and pressure changes, slow sensor drift,
and intermittent automotive or instrumentation faults. The Hantek C9/CA Scan
transport is well suited to that use because the device produces observations
continuously at the selected hardware cadence while the host retrieves the
available data. Host USB packet arrival times must not be substituted for the
device's acquisition interval, because observations can be delivered in small
batches and host polling adds scheduling jitter.

Current PulseView timing is samplerate-oriented and the normal continuous-stream
time axis is driven by integer `SR_CONF_SAMPLERATE` values. `SR_CONF_TIMEBASE`
can describe the device's native horizontal setting, but by itself does not
provide a fractional-Hz stream timing basis. `SR_CONF_SAMPLE_INTERVAL` is
relevant prior art for slow instruments, but an integer-second interval cannot
exactly represent all Hantek profiles (notably 1.25, 2.5, and 12.5 seconds).

A useful future PulseView/libsigrok enhancement would therefore be a generic
precise sample-period timing path for continuous analog data, ideally using a
rational period/interval representation. PulseView could then place samples on
the timeline as `sample_index * sample_period` and naturally display very slow
streams as long-duration charts. For the Hantek this would permit exact timing
for A3=23..28 without inventing integer sample rates, while also benefiting DMMs,
temperature loggers, environmental sensors, and other sub-1-Hz instruments.

This is a proposed future PulseView capability, **not functionality assumed to
exist today**, and it should remain generic rather than becoming a Hantek-only
mode. The current samplerate-based PulseView presentation for the validated
A3=1A..22 production profiles is satisfactory and should remain unchanged unless
a broader timing design requires otherwise.

## Production trigger policy

The triggered transport now uses the hardware trigger state machine instead of
sending `C2` immediately after every `C0` arm.  The implementation keeps the
A5 polling non-blocking so a frontend Stop remains responsive while a Normal
trigger is waiting.

- The canonical trigger path is libsigrok's **session trigger** (`struct sr_trigger`).  A valid session trigger always takes precedence.
- The driver advertises `SR_CONF_TRIGGER_MATCH` with `SR_TRIGGER_RISING` and `SR_TRIGGER_FALLING` so frontends that support analog session-trigger construction can create a CH1--CH8 edge trigger.
- PulseView 0.5.x exposes the device-level `SR_CONF_TRIGGER_SOURCE` and `SR_CONF_TRIGGER_SLOPE` controls for this analog device but does not currently provide the generic trigger-match toolbar on an analog signal. The fallback source list is `None`, `CH1` through `CH8`: `None` means Auto/free-running when no session trigger exists, while an enabled explicit channel means Normal hardware triggering using the selected `r`/`f` slope. Selecting a disabled source or selecting a source outside Trigger mode is rejected. Disabling the selected source, or switching to Scan or Roll, safely restores `None`. This does not invent a trigger-match value and does not alter the canonical session-trigger path.
- No session trigger and source `None`: Auto/free-running policy.  Arm with `C0`, poll A5, accept
  a genuine hardware completion when it arrives, otherwise send `C2` after the
  official approximately 1.87 s Auto timeout and then read the forced frame.
- A CH1--CH8 rising/falling session trigger, or the corresponding PulseView fallback source: Normal policy. Arm with `C0` and
  poll A5 indefinitely; no timeout `C2` is sent.  After a genuine triggered
  frame is read, the next acquisition callback re-arms automatically while
  the session remains running.
- `C1 <source> 00` is rising (`+`); `C1 <source> 01` is falling (`-`), with zero-based source values `00` through `07` for CH1 through CH8.
- `SR_CONF_TRIGGER_LEVEL` is exposed to frontends in volts and defaults to
  `0 V`. Immediately before acquisition, the driver resolves that voltage for
  the selected trigger channel and active input range into the ADC-domain `AB`
  value:

  ```text
  AB = round(zero_adc[channel, range] + trigger_volts /
             volts_per_count[channel, range])
  ```

  The per-channel, per-range saved calibration is used when available. If it
  is missing, the driver warns and uses ADC midscale (`2048`) plus the nominal
  Narrow, Medium or Wide scale. Values outside the 12-bit ADC interval
  `0..4095` are rejected rather than clamped. Source `None` retains the
  established `0x0800` Auto/free-running threshold because no explicit trigger
  channel is selected.
- Single/one-shot is a documented official-application policy but is not
  mapped onto ordinary PulseView Run and is not exposed as a device-specific
  sweep control.

### PulseView hardware validation (2026-08-30)

The `None` / `CH1` device-level fallback was validated end-to-end with the
locally built PulseView 0.5.x frontend and real Hantek 1008C hardware:

- With CH1 grounded and source `None`, PulseView continued to acquire the
  expected approximately 1.66 ms triggered frames at 2.4 MS/s, confirming the
  Auto/free-running path remained active.
- With CH1 grounded and source `CH1`, acquisition remained armed until the
  operator stopped it, confirming Normal mode does not fall through to the
  Auto timeout.
- With a 1 kHz square wave connected to CH1, source `CH1` and slope `r`
  triggered correctly on the rising edge.
- With the same input and slope `f`, triggering correctly moved to the falling
  edge.

This validates the PulseView device-setting fallback without any PulseView
source changes.  The standard libsigrok session-trigger path remains the
canonical interface and continues to take precedence when present.

Hardware edge triggering is currently enabled only for the validated C6/A6
triggered family.  Official C9/CA Scan and diagnostic C7/C8 ROLL transport remain
unchanged.

## Official Windows multi-channel evidence (2026-08-30)

acquisition evidence.  At 10 ms/div the physical C6/A6 frame remains 8000 bytes
/ 4000 little-endian 16-bit words while the observed acquisition width changes
with the number of channels explicitly enabled in the Windows UI:

| Explicit UI channels | Observed acquisition width | Approx. words/lane |
|---:|---:|---:|
| 1 | 1 | 4000 |
| 2 | 2 | 2000 |
| 3 | 4 | 1000 |
| 4 | 4 | 1000 |
| 5 | 6 | 667/666 |
| 6 | 6 | 667/666 |
| 7 | 8 | 500 |
| 8 | 8 | 500 |

CH1 carried an independent 1 kHz square wave and CH2 an independent 4 kHz sine,
allowing the first two interleaved lanes to be identified without any
waveform-specific processing.  A CH1+CH8 capture also confirms that non-adjacent
enabled physical channels can participate in the interleaved acquisition.

Do **not** yet describe the 3->4, 5->6, 7->8 width rounding as a bug, fixed pair
architecture, or accidental partner-channel enable.  The Windows evidence only
establishes the table above.  Before production multi-channel demultiplexing is
implemented, the Python protocol laboratory should deliberately drive the
nominally disabled extra channel in 3/5/7-channel configurations and determine
whether the extra lane is an adjacent ADC channel or padding/internal state.

Channel-configuration examples include:

```text
CH1 only: A0 01 ; AA 01 00 00 00 00 00 00 00
CH1+CH2:  A0 02 ; AA 01 01 00 00 00 00 00 00
CH1+CH8:  A0 02 ; AA 01 00 00 00 00 00 00 01
```

The final 5->6->7->8 transition capture demonstrates that A0 and AA are not
always redundant.  AA can expand to eight active acquisition entries when CH7
is enabled before the later explicit CH8 enable changes A0 to 08.  Production
code must preserve the evidence and avoid collapsing A0/AA into one guessed
semantic until the Python lab resolves their roles.

### Multi-channel trigger source / threshold

The official application directly establishes zero-based C1 source numbering
through CH5:

```text
C1 00 00 = CH1 rising
C1 01 00 = CH2 rising
C1 02 00 = CH3 rising
C1 03 00 = CH4 rising
C1 04 00 = CH5 rising
```

The second byte remains slope (`00` rising, `01` falling).  On source change the
application sends the newly selected source's channel-specific raw ADC trigger
threshold before source/slope and arming:

```text
AB <source-specific raw threshold>
C1 <zero-based source> <slope>
F3
A4 01
C0
```

A CH2->CH1 capture with CH1 stored at -105 mV and CH2 at 0 V sent `AB 07 C9`
before `C1 00 00`, ruling out stale carry-over of CH2's threshold. Channels at
the same 0 V UI trigger level can have different AB codes, so trigger voltage
must be resolved for the selected channel rather than treated as one universal
ADC threshold. The production driver implements this using the active input
range and the selected source channel's saved `zero_adc` and
`volts_per_count` calibration values.

### USB capture device-address warning

During some official-Windows trigger-source runs the Hantek disappeared and
returned under a new USB device address (observed Dev32 -> Dev33 -> Dev34).
Captures filtered to only the original Dev address therefore lost all later
Hantek traffic and initially made CH4/CH5 C1 writes appear absent.  A broader
capture recovered ordinary `C1 03 00` and `C1 04 00` writes.

acquisition pauses on some trigger-source changes, so the pause itself is not a
Wireshark artefact.  The exact relationship between the pause and USB
re-enumeration remains unresolved.  Re-enumeration is an evidence-capture hazard,
not a protocol requirement; do not reproduce it in the driver.

Compressed supporting captures and SHA-256 hashes are retained under

### Corrected extreme fast-end A3 mapping

A focused official-Windows 5 ns -> 2 ns -> 1 ns -> 2 ns -> 5 ns capture on
2026-08-30 produced `A3 01`, `A3 00`, `A3 01`, `A3 02`.  Therefore the official
mapping is directly established as 1 ns/div = A3 00, 2 ns/div = A3 01, and
5 ns/div = A3 02.  The earlier duplicate 1 ns/2 ns A3=01 interpretation was a
capture/interpretation miss.  This mapping alone does not authorize a production
samplerate; effective timing must still be measured under Linux.

## Multi-channel direct ADC (validated 2026-08-30 and 2026-09-01)

A3=0x11 and A3=0x0f Triggered modes have hardware-validated multi-channel routing.
`AA` selects arbitrary physical inputs; selected channels are compacted in
ascending physical-channel order.  The physical widths for 1..8 enabled
channels are 1,2,4,4,6,6,8,8.  For logical counts 3,5,7 the final physical slot
is a dummy lane and must not be exposed as a channel sample.

At A3=0x11 the aggregate stream is ~800 kword/s, so effective per-channel rates
are approximately 800k,400k,200k,200k,133333,133333,100k,100k samples/s.
Sparse CH1+CH8 routing and every odd dummy boundary (CH4/CH6/CH8) were verified
with independent 1 kHz and 4 kHz references.

At A3=0x0f the aggregate stream is ~2.4 Mword/s with the same physical width
table. Effective rates for 1..8 enabled channels are therefore approximately
2.4M,1.2M,600k,600k,400k,400k,300k,300k samples/s. The 2026-09-01 canonical-mask
matrix independently recovered the 4 kHz CH1 reference at each width; odd
logical counts selected widths 4/6/8 with correlation approximately 0.9996.

The exact role of A0 remains unresolved; changing it between logical count and
rounded width did not alter the measured geometry.  The driver writes the
logical enabled count to A0 and the true physical mask to AA.

Production multi-channel acquisition supports Triggered A3=0x0f and A3=0x11
through A3=0x19. Their aggregate-rate model is 2.4M, 800k, 400k, 200k, 80k,
40k, 20k, 8k, 4k and 2k word/s respectively. PulseView receives the aggregate
rate divided by the physical acquisition width.

The expected PulseView lists for the one-build validation sweep are:

| Enabled channels | Width | Validated samples/s/channel, slow to fast |
|---:|---:|---|
| 2 | 2 | 1k, 2k, 4k, 10k, 20k, 40k, 100k, 200k, 400k, 1.2M |
| 3 or 4 | 4 | 500, 1k, 2k, 5k, 10k, 20k, 50k, 100k, 200k, 600k |
| 5 or 6 | 6 | 333, 666, 1.333k, 3.333k, 6.666k, 13.333k, 33.333k, 66.666k, 133.333k, 400k |
| 7 or 8 | 8 | 250, 500, 1k, 2.5k, 5k, 10k, 25k, 50k, 100k, 300k |

### Full multichannel samplerate validation (2026-09-05)

The complete ten-rate list above was exercised through PulseView at physical
widths 8, 6, 4 and 2 in one build. CH1 carried a 20 Hz sine reference and a
second enabled channel carried the onboard 1 kHz square reference. Every rate
at every width produced the expected frame span and waveform cycle count, with
correct channel identity and no rate-specific data corruption. The A3=0x12
through A3=0x19 entries are therefore hardware-validated rather than inferred
from the timebase progression alone.

Several acquisitions encountered the device's already-observed transient USB
disappearance or initialization failure. The driver now retries the complete
reopen plus initialization sequence for up to 15 seconds at 500 ms intervals,
with explicit recovery-entry, retry, success and terminal-failure logging.
Configuration and unsupported-mode errors remain immediate failures.

Multi-channel frames are emitted as one analogue packet per enabled channel.
This is required because a sigrok analogue packet has one shared meaning and
encoding, while Hantek voltage calibration is per device, channel, and range.
Each channel is emitted in volts when its own persisted calibration for the
selected A2 range is
available; channels without independently established calibration remain
explicitly labelled as raw ADC counts.  One channel's calibration is never
applied to another channel merely to make its trace look plausible.

The standard string `range` configuration exposes the three independently
observed frontend states as `Narrow`, `Medium`, and `Wide`. They correspond to
the raw hardware settings A2=01, A2=02, and A2=03 and nominal scales of
0.0002, 0.00125, and 0.01 V/count respectively. These relative names describe
the proven sensitivity ordering without claiming an unproven volts/div value.
The selected value is applied to all eight physical inputs during initialization
and selects the matching persisted per-channel calibration. Diagnostic logs
retain both the meaningful name and raw A2 value.

### Standalone sigrok-cli calibration utility

`sigrok-hantek-1008c-calibrate` calibrates the production driver without
checking out or importing the companion Python protocol-laboratory project.
It invokes the installed `sigrok-cli`, captures raw ADC counts under a temporary
empty `XDG_DATA_HOME`, and atomically updates
`~/.local/share/hantek-1008c/calibration.ini` (or `$XDG_DATA_HOME` when set).

Close PulseView and any other process using the scope, then run:

```
sigrok-hantek-1008c-calibrate
```

The default run covers CH1 through CH8 and Narrow, Medium, and Wide. For each channel
it captures all requested grounded ranges before asking for one cable move to
the onboard 1 kHz / nominal 2 Vp-p reference. A2=02 and A2=03 are then validated
consecutively. A2=01 is grounded-zero only because the onboard reference
overranges that frontend state. Subsets can be selected, for example:

```
sigrok-hantek-1008c-calibrate --channels 3,4 --ranges Medium,Wide
```

Input isolation is mandatory during calibration. For grounded capture, ground
the target and disconnect or ground all other inputs; never leave the onboard
reference connected to another channel. For reference validation, connect the
reference only to the target and disconnect or ground every other input. Tests
with the reference left on CH2 and CH8 both produced excessive noise on grounded
CH1 and were rejected by the noise-quality check.

Grounded-zero replacement has a safety check. A first value must fall within
the central 45–55% of the 12-bit ADC range (approximately 1843–2252 counts),
and an existing per-device/channel/range value may move by at most 20 counts by
default. A different positive limit can be selected with, for example:

```sh
sigrok-hantek-1008c-calibrate --max-zero-shift-counts 50
```

After a successful grounded capture, an explicitly supplied limit is stored
under `[calibration policy <USB connection>]` in the calibration file. Later
runs without the option reuse that device policy. A rejected capture changes
neither the existing calibration nor the saved policy. The utility logs the
existing value, candidate value, signed change, permitted limit, policy source,
and acceptance result.

Each capture retries complete `sigrok-cli` acquisitions for up to 15 seconds
at 500 ms intervals after transient USB disappearance, timeout, or malformed
capture output. Recovery entry, each failed attempt, success, elapsed time, and
the terminal error are printed explicitly. Ground captures are rejected above
5 counts standard deviation or 32 counts span. Reference validation requires
1.6--2.4 Vp-p and 900--1100 Hz; it records validation results but never changes
the saved zero offset or nominal volts-per-count scale.

The calibration format is shared with the companion Python reference project.
Its identity key is the physical USB connection path, channel, and raw range ID;
moving the scope to another USB port therefore selects a different identity.
Back up a known-good store before experiments or driver changes that affect
analogue frontend initialization:

```
cp -a ~/.local/share/hantek-1008c/calibration.ini \
    ~/.local/share/hantek-1008c/calibration-known-good.ini
```

Calibration must be repeated after an initialization change that shifts the
grounded ADC baseline. A syntactically compatible but stale zero value produces
a real DC display offset and must not be hidden by display-side correction.

The utility's parser and measurement checks can be exercised without hardware:

```
sigrok-hantek-1008c-calibrate --self-test
```

### Hardware-independent driver regression tests

When the Check test framework and the Hantek driver are enabled, `make check`
also builds `tests/hantek-1008c`. It locks down the validated Triggered physical
widths, the distinct Scan and Roll divisors, all aggregate rate/A3 tables,
effective per-channel rate selection for one through eight channels, invalid
rate rejection, and the Narrow/Medium/Wide range mapping. These model tests do
not open or require a USB device.

The same test executable feeds synthetic byte streams through the production
Scan/Roll row decoder. It verifies rows split at arbitrary byte boundaries,
multiple logical rows per read, preserved sparse-lane ordering, 12-bit masking,
and removal of Roll's trailing AUX word. This structural test path performs no
waveform-dependent processing.

### Multi-channel Scan geometry (2026-09-05)

An A3=0x1a C9/CA matrix captured contiguous CH1..CHN selections for every
enabled count from eight back to one. Each two-second run produced approximately
780--795 aggregate little-endian ADC words/s regardless of channel count. The
stream deinterleaves across the exact logical enabled count, not Triggered's
padded `1,2,4,4,6,6,8,8` physical width:

- at eight channels, CH8 alone contained the onboard square-wave span while
  grounded CH2 and CH5 remained quiet;
- the seven-, five-, and three-channel streams divided exactly by 7, 5, and 3;
- applying Triggered's padded widths to those odd counts mixed distinct channel
  baselines and left incomplete rows.

A following sparse-mask matrix confirmed that enabled samples are packed in
ascending physical-channel order. `CH1+CH8`, `CH2+CH5`, `CH1+CH5`, `CH5+CH8`,
`CH1+CH5+CH8`, and `CH1+CH2+CH5+CH8` all divided exactly by their logical
counts. The 20 Hz sine, grounded-channel baselines, and onboard square wave
remained attached to the expected physical channels in every combination.

Scan therefore uses `aggregate A3 rate / enabled channel count`. Settings whose
aggregate rate is below the enabled count are omitted because libsigrok cannot
represent a positive fractional sample rate. Other non-integral divisions are
reported using the same integer truncation policy as Triggered mode.

| Enabled channels | Advertised Scan samples/s/channel, slow to fast |
|---:|---|
| 1 | 2, 4, 8, 20, 40, 80, 200, 400, 800 |
| 2 | 1, 2, 4, 10, 20, 40, 100, 200, 400 |
| 3 | 1, 2, 6, 13, 26, 66, 133, 266 |
| 4 | 1, 2, 5, 10, 20, 50, 100, 200 |
| 5 | 1, 4, 8, 16, 40, 80, 160 |
| 6 | 1, 3, 6, 13, 33, 66, 133 |
| 7 | 1, 2, 5, 11, 28, 57, 114 |
| 8 | 1, 2, 5, 10, 25, 50, 100 |

PulseView may now retain Scan while channels are enabled or disabled and
immediately refreshes this count-dependent list. Roll selection with multiple
enabled channels was subsequently investigated separately as described below.

### Multi-channel Roll geometry (2026-09-05)

An A3=0x18 C7/C8 matrix covering contiguous eight-to-one and six sparse masks
established a third transport geometry. Each Roll row contains the enabled ADC
channels in ascending physical order followed by exactly one auxiliary word:

```text
CH1 only:       CH1, AUX
CH1 + CH8:      CH1, CH8, AUX
CH1 + CH5 + CH8: CH1, CH5, CH8, AUX
```

The auxiliary lane was the stable approximately 1720-count position. The known
20 Hz CH1 sine, grounded CH2/CH5 baselines, and CH8 square wave retained their
physical identities in every contiguous and sparse mask. Aggregate transport
was approximately 3974 words/s independent of enabled count.

The established CH1-only Roll rates already represent half of the underlying
word rate because a one-channel row contains `CH1,AUX`. Multichannel effective
rates are therefore `2 * CH1-only rate / (enabled channels + 1)`, with integer
truncation and duplicate or sub-1 settings omitted:

| Enabled channels | Advertised Roll samples/s/channel, slow to fast |
|---:|---|
| 1 | 1, 2, 5, 9, 23, 50, 100, 201, 401, 1003, 2006 |
| 2 | 1, 3, 6, 15, 33, 66, 134, 267, 668, 1337 |
| 3 | 1, 2, 4, 11, 25, 50, 100, 200, 501, 1003 |
| 4 | 2, 3, 9, 20, 40, 80, 160, 401, 802 |
| 5 | 1, 3, 7, 16, 33, 67, 133, 334, 668 |
| 6 | 1, 2, 6, 14, 28, 57, 114, 286, 573 |
| 7 | 1, 2, 5, 12, 25, 50, 100, 250, 501 |
| 8 | 1, 2, 5, 11, 22, 44, 89, 222, 445 |

The production decoder carries incomplete rows across C7/C8 polls, emits only
the enabled ADC words, and deliberately discards the proven auxiliary slot. It
does not filter, smooth, interpolate, or otherwise modify channel samples.

### PulseView end-to-end validation (2026-09-05)

Contiguous CH1..CHN configurations were exercised through the installed native
libsigrok driver and PulseView for every N from 1 through 8. Both advertised
Triggered rates passed at each physical width:

| Enabled channels | Physical width | Fast rate | Slow rate | Samples/channel | Result |
|---:|---:|---:|---:|---:|:---:|
| 1 | 1 | 2.4 MSa/s | 800 kSa/s | 4000 | PASS |
| 2 | 2 | 1.2 MSa/s | 400 kSa/s | 2000 | PASS |
| 3 | 4 | 600 kSa/s | 200 kSa/s | 1000 | PASS |
| 4 | 4 | 600 kSa/s | 200 kSa/s | 1000 | PASS |
| 5 | 6 | 400 kSa/s | 133.333 kSa/s | 666 | PASS |
| 6 | 6 | 400 kSa/s | 133.333 kSa/s | 666 | PASS |
| 7 | 8 | 300 kSa/s | 100 kSa/s | 500 | PASS |
| 8 | 8 | 300 kSa/s | 100 kSa/s | 500 | PASS |

CH1 carried a clean 4 kHz sine while the independent 1 kHz / nominal 2 Vp-p
square reference was moved successively through CH2..CH8. Channel identity and
waveform shape remained correct at both rates. Grounded inputs remained near
zero after their own persisted A2=03 calibration was loaded. The odd-width
dummy lanes at logical counts 3, 5, and 7 were not exposed and did not leak into
visible samples.

With all eight channels enabled, PulseView showed 500 samples per channel and
the expected frame spans: approximately 1.667 ms at 300 kSa/s/channel and
5.000 ms at 100 kSa/s/channel. The visible cycle counts of both known signals
agreed with those rates. Full-resolution screenshots are retained with the
hardware-validation evidence in the companion Hantek protocol-laboratory
repository rather than duplicated in the production driver tree.
