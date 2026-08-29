# Official Windows Scan Mode: Linux protocol probe

This note describes the diagnostic Linux reproduction of the official Hantek
1008C Scan Mode observed in the 2026-08-29 Windows USBPcap evidence.

The proven boundary is 200 ms/div (`A3=19`, triggered C6/A6 family) to
500 ms/div (`A3=1A`, official Scan Mode C9/CA family).  1 s/div uses `A3=1B`
and remains in C9/CA Scan Mode.  `A4 01` remains in use on the Scan side.

`tools/probe_official_scan.py` remains deliberately separate from the canonical
`DirectADCSession` acquisition method and from `capture_roll_adc.py`.  No result
in this note changes the canonical arbitrary-waveform acquisition path.

## Linux A3=1A result: C9/CA semantics

The 2026-08-29 Linux run at 500 ms/div (`A3=1A`) completed 305 C9 polls and 304
CA transactions.  The first non-zero C9 was `0x0BB0` (2992).  One 64-byte CA
transaction immediately consumed that condition: the following C9 was zero.
This disproves a simple decrementing FIFO-depth interpretation; if 2992 were a
byte count remaining to drain, one CA read would not be expected to make it
zero.  The probe therefore treats C9 values above 64 as an oversize/startup
condition with unknown semantics and quarantines the returned CA packet.

After that initial condition, steady-state C9 values were small and even:

- 8 bytes: 9 occurrences
- 10 bytes: 211 occurrences
- 12 bytes: 81 occurrences
- 14 bytes: 2 occurrences

For every steady-state C9 value in this run, the next CA USB reply was exactly
64 bytes, the first C9 bytes were retained as payload, and every byte after that
prefix was zero padding.  The immediate C9 read after CA was normally zero; one
observation returned 4.  That post-CA value is recorded as evidence but is not
used as a continuation/drain rule.

The updated probe therefore uses only the evidence-backed rule:

```
C9 == 0       -> no CA read
1 <= C9 <= 64 -> one CA read; retain exactly the C9-byte prefix; verify padding
C9 > 64       -> one CA read for protocol continuity, quarantine all 64 bytes
                 separately; do not treat it as samples or FIFO depth
```

## Observational sample view

The steady-state retained payloads are all even-length in the current A3=1A
capture, so the diagnostic reports complete little-endian 16-bit words masked
to 12 bits as an observational view.  This is not waveform reconstruction and
is not used to decide which bytes to retain.

The uploaded run's complete raw stream (including the then-unquarantined first
64-byte startup CA packet) contained 1623 words with raw values 1998..2202.  The
known onboard 1 kHz / 2 Vp-p source is useful only as validation that these
numbers are physically plausible; it is not used as a decoding or cleanup rule.
The v3 probe now excludes any C9>64 startup packet from the steady-state `.bin`
and writes such packets to a separate `_oversize-ca.bin` artifact.

The probe also records actual monotonic scan elapsed time and reports observed
word throughput.  Treat that value as transport/sample-throughput evidence, not
a canonical samplerate, until repeated A3=1A/A3=1B measurements establish the
rate model.

## Run

For 500 ms/div:

```bash
python tools/probe_official_scan.py --profile 1a --capture-s 2
```

If that remains stable, repeat at 1 s/div:

```bash
python tools/probe_official_scan.py --profile 1b --capture-s 2
```

The default 1870 ms C0-to-C2 interval mirrors the official Windows boundary
capture and remains an evidence-derived diagnostic timing, not a canonical
constant.

## A3=1A / A3=1B rate comparison and extended Scan profiles

Two clean v3 Linux measurements now give an almost exact 2:1 relationship in
steady-state C9/CA payload production:

- A3=1A (500 ms/div), 2 s requested: 3184 steady bytes = 1592 complete u16 words.
- A3=1B (1 s/div), 2 s requested: 1590 steady bytes = 795 complete u16 words.

A neutral 4-byte grouping is now also reported because the earlier C7/C8 lab
path used a 4-byte CH1 logical row and, under that candidate grouping, the two
new observations are approximately 398 and 199 rows/s using the requested
2-second window.  Those values closely match the earlier independently
measured A3=1A (~401 Sa/s) and A3=1B (~201 Sa/s) cadence.  This is evidence in
favour of a common 4-byte logical acquisition unit, but it does **not** yet
prove the meaning of either 16-bit word.  The diagnostic therefore reports:

```
observational_le_u12_words
observational_word_throughput_per_s
candidate_4byte_rows
candidate_4byte_tail_bytes
candidate_4byte_row_throughput_per_s
```

No word is selected, averaged, thresholded, or otherwise treated as the CH1
waveform by this diagnostic.

The official Windows horizontal sweep established the complete Scan-side A3
map, and the probe now exposes it from the proven boundary onward:

```
1A  500 ms/div
1B  1 s/div
1C  2 s/div
1D  5 s/div
1E  10 s/div
1F  20 s/div
20  50 s/div
21  100 s/div
22  200 s/div
23  500 s/div
24  1000 s/div
25  2000 s/div
26  5000 s/div
27  10000 s/div
28  20000 s/div
```

The captured Windows sweep showed `AC 00 00 00 00 01 00 00 01` throughout this
Scan region.  The profile table therefore uses that captured AC value for each
entry.  This extends only the diagnostic profile selection; it does not assert
a canonical samplerate for any entry.

For the next rate point:

```bash
python tools/probe_official_scan.py --profile 1c --capture-s 4
```

If the candidate 4-byte-row model is correct, A3=1C should be near the earlier
~100 Sa/s class.  That expectation is a test prediction, not an acquisition
rule.

## A3=1C confirmation and neutral word0/word1 view

A repeatable Linux run at A3=1C (2 s/div) on 2026-08-29 produced:

```
C9 polls=630
CA packets=363
steady_bytes=1596
u12_words=798
candidate_4byte_rows=399
candidate_rows/s=99.717
candidate_4byte_tail_bytes=0
oversize_ca=1
```

This is the third consecutive Scan profile to follow the same cadence model:

| A3 | Official time/div | Observed candidate 4-byte rows/s |
|---|---:|---:|
| 1A | 500 ms/div | ~398 |
| 1B | 1 s/div | ~199 |
| 1C | 2 s/div | 99.717 |

The nearly exact halving from 1A -> 1B -> 1C, together with the zero-byte tail
at 1C, is strong evidence that CH1-only official C9/CA Scan transport has a
4-byte logical acquisition cadence.  It still does **not** establish which of
the two 16-bit values is the CH1 waveform sample, whether they are paired ADC
conversions, or whether the second word has another hardware meaning.

The diagnostic therefore now splits complete candidate rows only for neutral
statistics:

```
word0 = first little-endian 16-bit value, masked to 12 bits
word1 = second little-endian 16-bit value, masked to 12 bits
```

It reports count/min/max/span for each word plus the mean and maximum absolute
word0/word1 difference.  It does not select, average, merge, smooth, threshold,
or otherwise reconstruct a waveform from either word.  This keeps the next
experiment structural and waveform-agnostic.

The earlier one-off A5 timeout before the successful 1C run occurred during the
shared DirectADC initialization/calibration phase, before the 1C Scan transport
was exercised.  The immediate identical rerun completed normally, so that
failure is retained as an initialization robustness observation rather than
classified as a Scan-mode failure.

## Stateful row framing across C9/CA boundaries

A second A3=1C run on 2026-08-29 produced 1586 steady-state bytes, 396
complete candidate 4-byte rows, and a 2-byte capture-end tail at an observed
98.989 candidate rows/s.  Its neutral word statistics were:

```
word0: count=396 min=1998 max=2202 span=204
word1: count=396 min=1999 max=2201 span=202
mean |word0-word1| = 1.09596 counts
max  |word0-word1| = 66 counts
```

The two words therefore track each other very closely in this validation
capture, while occasional larger differences remain possible.  This supports
paired ADC observations as a working structural interpretation, but the
protocol code deliberately continues to expose only `word0` and `word1`.
Neither word is selected or averaged into a canonical waveform sample.

The 2-byte tail also demonstrates why C9/CA USB transaction boundaries must
not be treated as logical-row boundaries.  `ScanCandidateRowFramer` is now a
pure, stateful protocol-lab helper: arbitrary retained CA prefixes are fed into
it, complete 4-byte candidate rows are emitted, and 0..3 trailing bytes are
carried into the next feed.  At capture end any remaining carry is reported
verbatim rather than discarded or padded.  The probe cross-checks the stateful
result against whole-buffer framing as an invariant.

This is framing only.  It does not establish whether one logical oscilloscope
sample is a whole 4-byte pair or either individual 16-bit observation, and it
does not modify `DirectADCSession` or the existing C7/C8 ROLL lab path.
