# Official Windows application timebase evidence (2026-08-29)

This note records USB traffic captured from the official Hantek Windows
application controlling the project 1008C.  The capture was made with CH1 only,
x1 probe adjustment, Auto acquisition, the onboard 1 kHz / 2 Vpp reference
signal, and a complete horizontal time/div sweep from 1 ns/div through
20000 s/div and back.

This is protocol evidence, not a request to promote unvalidated sample rates
into the canonical acquisition path.

## A3 is the coarse horizontal/timebase selector

The official application maps its horizontal UI ladder to A3 as follows.  The
extreme 1/2 ns end is collapsed at the minimum observed hardware setting; from
5 ns upward the sequence is monotonic.

| Horizontal time/div | A3 |
|---|---:|
| 1 ns | `01` |
| 2 ns | `01` (same minimum state; no distinct transition observed) |
| 5 ns | `02` |
| 10 ns | `03` |
| 20 ns | `04` |
| 50 ns | `05` |
| 100 ns | `06` |
| 200 ns | `07` |
| 500 ns | `08` |
| 1 us | `09` |
| 2 us | `0A` |
| 5 us | `0B` |
| 10 us | `0C` |
| 20 us | `0D` |
| 50 us | `0E` |
| 100 us | `0F` |
| 200 us | `10` |
| 500 us | `11` |
| 1 ms | `12` |
| 2 ms | `13` |
| 5 ms | `14` |
| 10 ms | `15` |
| 20 ms | `16` |
| 50 ms | `17` |
| 100 ms | `18` |
| 200 ms | `19` |
| 500 ms | `1A` |
| 1 s | `1B` |
| 2 s | `1C` |
| 5 s | `1D` |
| 10 s | `1E` |
| 20 s | `1F` |
| 50 s | `20` |
| 100 s | `21` |
| 200 s | `22` |
| 500 s | `23` |
| 1000 s | `24` |
| 2000 s | `25` |
| 5000 s | `26` |
| 10000 s | `27` |
| 20000 s | `28` |

The already hardware-validated Triggered values therefore have an official UI
interpretation:

- `A3=0E` -> 50 us/div
- `A3=0F` -> 100 us/div
- `A3=10` -> 200 us/div
- `A3=11` -> 500 us/div

Do not infer sample rate solely from the UI time/div.  A3 is best described as
the coarse acquisition/timebase selector; the associated AC command also
changes with the selected horizontal regime.

## AC structure

The observed eight parameter bytes following opcode `AC` have a useful
structural interpretation as three big-endian integers:

```text
AC [u16] [u24] [u24]
```

For example:

```text
AC 0F A0 00 03 42 00 03 42
   |----| |------| |------|
     4000    834      834
```

and the older startup value:

```text
AC 01 F4 00 09 C5 00 09 C5
     500     2501     2501
```

The field semantics are not fully proven.  In particular, the first field being
4000 is consistent with the 4K acquisition depth in that configuration, but it
must not yet be treated as a universally proven "sample count" field.

## Intermediate-timebase AC evidence

For the Windows sweep the final u24 field closely tracks the approximately
10-division total horizontal window over much of the intermediate range:

| A3 | UI time/div | AC parameters interpreted as u16/u24/u24 |
|---:|---:|---|
| `0E` | 50 us | `4000, 834, 834` |
| `10` | 200 us | `0, 1, 1401` |
| `11` | 500 us | `0, 1, 5001` |
| `12` | 1 ms | `0, 1, 10001` |
| `13` | 2 ms | `0, 1, 20001` |
| `14` | 5 ms | `0, 1, 50001` |
| `15` | 10 ms | `0, 1, 99982` |
| `16` | 20 ms | `0, 1, 199777` |
| `17` | 50 ms | `0, 1, 503969` |
| `18+` | 100 ms and slower | `0, 1, 1` |

The near equality for 500 us through 50 ms is strong evidence that the final
field is timing/window related.  The exact unit/rounding/divider semantics are
not proven, and the 200 us value (`1401`) is a real discontinuity that should
not be papered over.

## AC configuration boundary at A3=18 (not Scan Mode)

A particularly strong configuration boundary occurs between:

```text
50 ms/div   -> A3 17, AC ... 07 B0 A1  (503969)
100 ms/div  -> A3 18, AC ... 00 00 01  (1)
```

This overlaps numerically with the independently validated diagnostic ROLL-family
A3 values, but the later dedicated Windows boundary capture proves that the
official GUI remains in triggered operation at A3=18 and A3=19.  Official Scan
Mode begins at A3=1A (500 ms/div) and uses C9/CA with A4 01 observed.  Therefore
A3=18 is an AC/timing configuration boundary, not the official Trigger/Scan
transport boundary.

## Canonical-path consequence

No canonical sample-rate mapping or reconstruction rule is changed by this
capture.  The safe model is now:

```text
requested time/div
    -> A3 coarse acquisition/timebase regime
    -> AC timing/window parameters
    -> transport/acquisition mechanism (must be validated separately)
```

The earlier `tools/probe_timebase_boundary.py` experiment targeted the A3=17/18
AC/timing discontinuity.  It must not be used as the official Trigger/Scan
boundary test.  The proven GUI/transport boundary is A3=19 -> A3=1A.

`tools/probe_official_scan.py` is the current Linux diagnostic for the official
Scan Mode path.  It reproduces the evidence-derived `A3=1A/1B`, `A4 01`,
`C9/CA` sequence while leaving both canonical direct-ADC TRIGGERED and the existing
diagnostic `A4 02 + C7/C8` ROLL path untouched.

## Trigger position controls captured from the official application

Two additional controlled Windows captures separate the horizontal and vertical
trigger controls from time/div and V/div selection.

### Horizontal trigger position: AC

At fixed 10 ms/div, moving only the horizontal trigger-position T marker changes
`AC`.  The `u16 + u24 + u24` structure remains consistent.  The two u24 fields
partition the total acquisition window.  Representative observations include:

```text
u24-left   u24-right   sum
    1000       98982   99982
   20000       79982   99982
   49991       49991   99982
   90000        9982   99982
   99982           1   99983
```

The one-count endpoint convention must not be hidden by normalization.  The
strong conclusion is that the two u24 values encode the two sides of the
horizontal trigger position within the acquisition window.  The exact semantics
of the leading u16 field remain unresolved, although it also changes
monotonically with trigger position.

### Vertical trigger level: AB

Moving only the vertical trigger T marker produces monotonic `AB hi lo`
commands.  `AB` is therefore proven to be a big-endian 16-bit ADC-domain
trigger-threshold quantity.  Examples observed include values around 0x07CB,
0x0800 and up through the 0x09xx range as the marker was moved vertically.

This resolves an earlier ambiguity from the V/div sweep: AB values changed when
A2 changed because the official application re-expressed the user's trigger
threshold in the ADC coordinates of the newly selected analogue range.  AB is
not a fourth gain/range control.

The GUI also changed from `TrigD` to `Auto` when the vertical trigger threshold
was moved outside the waveform.  That is a useful UI observation, but no
separate protocol command for the status change is claimed from this evidence.

## Official Trigger -> Scan Mode boundary

A dedicated forward/reverse boundary capture removes the earlier ambiguity
around A3=0x18.  The official GUI remains in triggered operation at 100 and
200 ms/div and explicitly enters **Scan Mode at 500 ms/div**:

| UI time/div | A3 | Official GUI regime | observed data-transfer family |
|---:|---:|---|---|
| 100 ms | `18` | Trigger | C6/A6 buffer family |
| 200 ms | `19` | Trigger | C6/A6 buffer family |
| 500 ms | `1A` | Scan Mode | C9/CA |
| 1 s | `1B` | Scan Mode | C9/CA |

The reverse transition 500 ms -> 200 ms returns from C9/CA Scan Mode to the
trigger/buffer family.  The official application continues to use `A4 01` in
this Scan Mode capture.

Therefore the earlier AC collapse at A3=0x18 is **not** the official
Trigger/Scan transport boundary.  It is a separate internal timing/configuration
boundary.  Likewise, the project's existing diagnostic slow path using
`A4 02 + C7/C8` is not the same mechanism as official Windows Scan Mode and
must not be documented or implemented as such without further evidence.

The updated safe model is:

```text
horizontal time/div
    -> A3 coarse timebase
    -> AC acquisition window + horizontal trigger placement
    -> at <=200 ms/div: official triggered C6/A6 family
    -> at >=500 ms/div: official Scan Mode C9/CA family (A4 01 observed)

vertical trigger T
    -> AB 16-bit ADC-domain trigger threshold
```

Future Linux work should characterize C9/CA independently before promoting
official Scan Mode into the canonical Python or libsigrok acquisition paths.
## Official Edge-trigger controls

The Windows Trigger dialog exposes Edge mode with Sweep (Auto, Normal, Single), Source (CH1 in the one-channel capture), and Slope (+/-). Dedicated one-variable USBPcap captures were made at 10 ms/div with CH1 on the onboard 1 kHz / 2 Vpp reference signal.

### Trigger slope: C1

Changing only Trigger Slope produces the `C1 00 xx` command family. The captured `+ -> - -> + -> - -> +` sequence generated alternating `C1 00 01` and `C1 00 00` writes with no competing configuration change. This proves `C1` is the Edge-trigger slope/polarity control. The numeric value-to-`+`/`-` orientation remains deliberately unlabeled until transition ordering is correlated unambiguously.

### Trigger Sweep: Auto / Normal / Single

A separate `Auto -> Normal -> Single -> Normal -> Auto` capture does not expose an obvious new dedicated configuration opcode analogous to `C1`. The visible difference is in acquisition/re-arm behaviour using the already-known trigger/buffer control family. This is consistent with Sweep being at least partly a host-side re-arm policy: in particular, Single can stop by not re-arming after one completed acquisition.

Do not invent an Auto/Normal/Single protocol byte from this capture. The exact state-machine timing remains a diagnostic/replay question for Linux.

### Current trigger-control model

```text
vertical trigger level       -> AB big-endian 16-bit ADC-domain threshold
horizontal trigger position  -> AC acquisition-window partition/position
edge trigger slope           -> C1 00 xx
trigger sweep                -> Auto/Normal/Single re-arm behaviour; no dedicated opcode proven
```



## C9 / CA byte-transfer semantics from the boundary capture

Packet-level inspection of the dedicated Trigger/Scan boundary capture refines
the C9/CA mechanism further.  In official Scan Mode the application repeatedly
issues `C9`; the reply is exactly two bytes and behaves as a big-endian count
of currently valid data bytes.  Observed counts in this capture were:

```text
0, 12, 14, 24, 26, 38, 40 bytes
```

When the count is non-zero, the application issues one `CA` request and receives
a 64-byte USB packet.  The first `C9`-reported bytes carry data and the remainder
of the packet is padding.  For example, `C9 -> 00 26` is followed by a 64-byte
`CA` reply whose first 38 bytes are retained; `C9 -> 00 1A` similarly identifies
26 valid bytes.  The evidence set contains no `C9` count above 40, so no
multi-packet continuation rule is claimed.

The official entry sequence around both A3=1A and A3=1B was also consistent:
`A4 01`, `E4 01`, `E6 01`, `C0`, repeated `F3`/`A5` observation for about
1.87 seconds, then `C2`, followed by `F3`/`A5` and `C9`/`CA` polling.  The
~1.87-second interval is evidence-derived host behaviour, not yet promoted to a
hardware requirement.

`tools/probe_official_scan.py` deliberately preserves only the valid C9-sized
prefix from each 64-byte CA packet and stores the raw bytes without waveform
processing.  It refuses a C9 count above 64 rather than inventing an unobserved
continuation protocol.
