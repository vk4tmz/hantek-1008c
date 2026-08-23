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
