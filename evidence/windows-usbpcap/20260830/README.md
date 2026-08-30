# Official Hantek Windows USBPcap evidence — 2026-08-30

These captures extend the 2026-08-29 official-Windows evidence with the extreme
fast timebase, multi-channel acquisition geometry, channel enable commands, and
multi-channel hardware-trigger source behaviour.  They are retained as protocol
evidence.  No waveform-specific reconstruction rule is derived from the known
test signals.

## Physical signals used

Unless a filename states otherwise:

- CH1: 1 kHz square-wave source.
- CH2: ATR2x USB audio output playing a 4 kHz sine, approximately 0.9 Vpp.
- Other enabled channels: unconnected/quiet for the acquisition-geometry tests.
- Timebase for the multi-channel matrix: 10 ms/div, official application Auto acquisition.

The independent CH1/CH2 frequencies were used only to identify lanes and verify
interleaving.  They are not used for filtering, thresholding, flattening, or
waveform-specific cleanup.

## Extreme fast timebase

`20260830_Hantek1008_1CH_1khz_Square_ZoomHorizontally_LowTimeDiv_Filtered_Dev10.pcapng.gz`

A focused 5 ns -> 2 ns -> 1 ns -> 2 ns -> 5 ns sweep produced:

```text
A3 01
A3 00
A3 01
A3 02
```

Therefore the official Windows mapping is directly established as 1 ns/div =
A3 00, 2 ns/div = A3 01, and 5 ns/div = A3 02.  The earlier duplicate 1 ns / 2
ns A3=01 interpretation was a capture/interpretation miss.

## One- and two-channel baselines

- `20260830_Hantek1008_1CH_1khz_Square_10ms_CH1_Filtered_Dev10.pcapng.gz`
- `20260830_Hantek1008_1CH_4khz_Sine_10ms_CH2_Filtered_Dev10.pcapng.gz`
- `20260830_Hantek1008_2CH_CH1-CH2_10ms_Auto_Filtered_Dev10.pcapng.gz`

Triggered C6/A6 acquisition remains an 8000-byte / 4000-u16-word physical
frame.  With CH1+CH2 enabled the words alternate CH1, CH2, CH1, CH2, ... and
each channel receives 2000 observations.  The independent 1 kHz square and 4
kHz sine signatures identify the two lanes without relying on DC offset or UI
vertical position.

## Channel enable/configuration evidence

- `20260830_Hantek1008_CH2_Enable-Disable-Enable_10ms_Auto_Filtered_Dev10.pcapng.gz`
- `20260830_Hantek1008_CH8_Enable-Disable-Enable_10ms_Auto_Filtered_Dev10.pcapng.gz`

Observed examples include:

```text
CH1 only: A0 01 ; AA 01 00 00 00 00 00 00 00
CH1+CH2:  A0 02 ; AA 01 01 00 00 00 00 00 00
CH1+CH8:  A0 02 ; AA 01 00 00 00 00 00 00 01
```

This strongly ties AA's eight bytes to acquisition/channel enable state, while
A0 also tracks acquisition width/count in the tested cases.  Later 7/8-channel
evidence shows A0 and AA are not always redundant, so their exact semantics
must not be collapsed into one field prematurely.

## Multi-channel acquisition geometry

- `20260830_Hantek1008_3CH_CH1-CH2-CH3_10ms_Auto_Filtered_Dev10.pcapng.gz`
- `20260830_Hantek1008_4CH_CH1-CH2-CH3-CH4_10ms_Auto_Filtered_Dev10.pcapng.gz`
- `20260830_Hantek1008_5CH_CH1-thru-CH5_10ms_Auto_Filtered_Dev10.pcapng.gz`
- `20260830_Hantek1008_8CH_allChannelsEnabled_10ms_Auto_Filtered_Dev10.pcapng.gz`
- `20260830_Hantek1008_ChannelEnable_CH1-CH5_to-CH8_10ms_Auto_ExcludingDev14.pcapng.gz`

At the same 10 ms/div setting, the physical Triggered frame remains 4000 u16
words while the observed acquisition width changes with the number of channels
explicitly enabled in the UI:

| Explicit UI channels | Observed acquisition width |
|---:|---:|
| 1 | 1 |
| 2 | 2 |
| 3 | 4 |
| 4 | 4 |
| 5 | 6 |
| 6 | 6 |
| 7 | 8 |
| 8 | 8 |

The resulting observations per acquisition lane are therefore 4000, 2000,
1000, 1000, approximately 667, approximately 667, 500, and 500 respectively.
Do **not** yet label this a bug, fixed channel-pair architecture, or accidental
partner-channel enable.  The table records observed behaviour only.  A planned
Linux/Python protocol-lab test will inject a distinctive signal into the
nominally disabled extra channel for the 3/5/7 cases to determine whether the
extra lane is a real adjacent ADC channel or padding/internal acquisition state.

The final 5->6->7->8 enable capture also demonstrates that A0 and AA need not
change together.  In particular, the CH7 transition can expand AA to eight
active acquisition entries before the later explicit CH8 enable changes A0 to
08.  Preserve the raw command chronology rather than assuming A0 and AA are
simple duplicate channel counts.

## Multi-channel hardware trigger source and threshold

- `20260830_Hantek1008_5CH_TriggerSource_CH2-to-CH1_10ms_Auto_Filtered_Dev32.pcapng.gz`
- `20260830_Hantek1008_5CH_TriggerSource_CH3-CH4-CH5-CH4-CH3_10ms_Auto_ExcludingDev14_HantekDevAddressChanges.pcapng.gz`

Directly observed source encoding through CH5 is zero-based in the first C1
parameter, with the second parameter retaining slope:

```text
C1 00 00 = CH1 rising
C1 01 00 = CH2 rising
C1 02 00 = CH3 rising
C1 03 00 = CH4 rising
C1 04 00 = CH5 rising
```

On a source change the official application programs the newly selected
channel's raw ADC trigger threshold before the source/slope and arm sequence:

```text
AB <source-specific raw threshold>
C1 <zero-based source> <slope>
F3
A4 01
C0
```

For example, the CH2->CH1 capture programs `AB 07 C9` before `C1 00 00`; the
Windows UI had CH1 at -105 mV while CH2 was at 0 V.  This rules out carrying the
previous channel's threshold across that transition.  Separate 0 V channels
also produced different AB codes, showing that physical/UI trigger voltage is
converted to a source-channel-specific ADC threshold rather than one universal
0 V code.

## USB device-address / re-enumeration trap

During trigger-source experiments the official application could pause for
several seconds, and USB captures showed the Hantek disappearing and returning
with a new USB device address (for example Dev32 -> Dev33 -> Dev34).  Filtering
a USBPcap to the original device address can therefore make all later Hantek
traffic appear to vanish and can falsely suggest that CH4/CH5 use a different
trigger-source opcode.

A no-Wireshark/no-USBPcap control still reproduced source-change UI/acquisition
pauses (for example CH2->CH3, CH3->CH4, CH4->CH5, CH5->CH6), so the pause itself
is not caused by Wireshark.  The exact cause/relationship of USB re-enumeration
remains unresolved.  Treat address changes as an evidence-capture hazard, not
as a required part of the trigger protocol.

For future Windows capture work, follow the Hantek across re-enumeration (for
example by VID:PID or by retaining the broader USBPcap and excluding unrelated
high-volume devices) instead of assuming one Dev address for the whole run.

## Integrity

`SHA256SUMS.txt` contains SHA-256 hashes for every retained compressed capture.
