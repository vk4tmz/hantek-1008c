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
