# Official Hantek Windows USBPcap evidence — 2026-08-29

These captures were produced with the official Hantek Windows application and
USBPcap/Wireshark.  They are retained as protocol evidence, not as generated
test waveforms.

## Captures

### Vertical V/div ladder

`20260829_Hantek1008_1CH_10ms_1khz_Square_VerticalVoltRanges_Filtered_Dev16.pcapng.gz`

- Hantek USB address in that Windows session: **16**.
- CH1 only, x1 probe/display adjustment, 10 ms/div, Auto acquisition.
- CH1 connected to the onboard nominal 1 kHz, 2 Vp-p square-wave source.
- UI ladder captured from 10 mV/div up to 5 V/div and back down.
- This capture established the official application's coarse A2 groupings:
  - A2=01: 10, 20 mV/div
  - A2=02: 50, 100, 200 mV/div
  - A2=03: 500 mV, 1 V, 2 V, 5 V/div
- Intermediate V/div values within one A2 group do not change the raw ADC
  amplitude; they are display scaling rather than additional analogue gain.

### Horizontal time/div ladder

`20260829_Hantek1008_1CH_10ms_1khz_Square_HorizontalTimeDivRanges_Filtered_Dev16.pcapng.gz`

- Hantek USB address in that Windows session: **16**.
- CH1 only, 1 V/div, x1 adjustment, Auto acquisition.
- Full horizontal ladder captured from 1 ns/div through 20000 s/div and back.
- The capture maps the official UI time/div choices to A3 and associated AC
  configuration values.
- Important anchors include 50 us/div=A3 0x0E, 100 us/div=0x0F,
  200 us/div=0x10, 500 us/div=0x11, 10 ms/div=0x15, 50 ms/div=0x17 and
  100 ms/div=0x18.
- AC is structurally consistent with `u16 + u24 + u24` (big-endian fields).
- The A3 0x17 -> 0x18 / 50 ms -> 100 ms region is a strong acquisition-mode
  boundary candidate, but the exact TRIGGERED/ROLL transport switch remains a
  hardware-validation question and must not be inferred solely from GUI motion.

### Startup baseline

`20260829_Hantek1008_Startup_Filtered_Dev15.pcapng.gz`

- Filtered from the original 178 MiB startup capture.
- The original session assigned the Hantek USB address **15**.
- The matching standard USB device descriptor contains VID:PID **0783:5725**.
- Only USBPcap Enhanced Packet Blocks for device address 15 are retained;
  non-packet pcapng metadata blocks are preserved.
- This is the clean official-software startup/control baseline and includes the
  three-range A2 initialization/calibration sequence observed from the official
  application.

## USB device addresses are not persistent identifiers

`usb.device_address` is assigned by Windows/USB enumeration and can change
between captures, reconnects, reboots, or topology changes.  Addresses 15, 16,
and a later observed 17 are therefore not contradictory and must **never** be
hard-coded as the identity of the Hantek 1008C.

The persistent identity is VID:PID **0783:5725**.  During a capture that includes
USB enumeration, the project helper can discover the current address from the
standard USB device descriptor and filter the pcapng automatically:

```bash
python tools/filter_usbpcap_device.py input.pcapng output.pcapng
```

It defaults to VID:PID 0783:5725.  An explicit address can also be supplied when
working with a capture that begins after enumeration:

```bash
python tools/filter_usbpcap_device.py input.pcapng output.pcapng \
  --device-address 17
```

The helper is deliberately dependency-free; `python-pcapng` is not required.
It is scoped to the little-endian pcapng/USBPcap files used in this project.

## Provenance rule

These captures are empirical protocol evidence.  They must not be used to add
waveform-specific cleanup, thresholding, smoothing, flattening or reconstruction
to either the Python reference path or the libsigrok production path.

### Horizontal trigger-position sweep

`20260829_Hantek1008_1CH_10ms_1khz_Square_HorizontalTrigger_Filtered_Dev17.pcapng.gz`

- Hantek USB address in this Windows session: **17**.
- CH1, 10 ms/div, 1 V/div, x1, onboard nominal 1 kHz 2 Vp-p source.
- Only the horizontal trigger-position `T` marker was moved.
- The official application changes `AC` while the marker moves.
- `AC` is consistent with three big-endian fields: `u16 + u24 + u24`.
- At 10 ms/div the two u24 fields partition an approximately 99,982 us total
  acquisition window.  Near centre they are approximately equal; moving the
  marker transfers time from one side to the other while preserving the sum.
- At the horizontal extremes the GUI changes the T-marker glyph to point left
  or right; in the interior it points down.
- The exact semantics/units of the first u16 AC field remain unresolved.

### Vertical trigger-level sweep

`20260829_Hantek1008_1CH_10ms_1khz_Square_VerticalTrigger_Filtered_Dev17.pcapng.gz`

- Hantek USB address in this Windows session: **17**.
- Only the vertical trigger-level `T` marker was moved.
- The official application emits monotonic `AB hi lo` values as the trigger
  marker moves.
- This proves `AB` is the vertical trigger-threshold command and its payload is
  a big-endian 16-bit ADC-domain quantity.
- This resolves the earlier correlation between A2 and AB during V/div changes:
  Windows recalculates the ADC-domain trigger threshold when the analogue A2
  range changes; AB is not itself an analogue-gain selector.
- When the trigger threshold was moved outside the CH1 waveform, the GUI status
  changed from `TrigD` to `Auto`.  This UI observation is retained separately
  from the proven AB command semantics; a distinct USB command for the status
  transition has not been established.

### Official Trigger / Scan Mode boundary

`20260829_Hantek1008_1CH_10ms_1khz_Square_Horizontal_TriggerScan_Boundary_Filtered_Dev17.pcapng.gz`

- Hantek USB address in this Windows session: **17**.
- Controlled sequence: 100 ms/div -> 200 ms/div -> 500 ms/div -> 1 s/div ->
  500 ms/div -> 200 ms/div -> 100 ms/div.
- The official GUI explicitly shows triggered operation through **200 ms/div**
  and **Scan Mode** beginning at **500 ms/div**.
- Corresponding A3 values are 0x18=100 ms/div, 0x19=200 ms/div,
  0x1A=500 ms/div, and 0x1B=1 s/div.
- The USB transport changes at the official boundary: the triggered/buffer
  family uses C6/A6, while Scan Mode uses repeated C9/CA transfers.
- Windows continues to use `A4 01` in this Scan Mode capture.  Therefore the
  project's existing diagnostic `A4 02 + C7/C8` ROLL path must **not** be
  equated with official Windows Scan Mode.

- `20260829_Hantek1008_1CH_10ms_1khz_Square_TriggerSlope_Filtered_Dev17.pcapng.gz` — one-variable Edge Trigger Slope `+ -> - -> + -> - -> +`; isolates `C1 00 xx`.
- `20260829_Hantek1008_1CH_10ms_1khz_Square_TriggerSweep_Filtered_Dev17.pcapng.gz` — Trigger Sweep `Auto -> Normal -> Single -> Normal -> Auto`; preserves re-arm/state evidence and does not justify inventing a dedicated sweep opcode.

