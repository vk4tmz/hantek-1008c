# Using the Hantek 1008C with libsigrok and PulseView

This is the concise user guide for the native Linux Hantek 1008C driver. The
companion documents in this repository preserve the protocol evidence and
experiments behind the implementation.

## Upstream status

The native driver and corresponding PulseView integration have been submitted
upstream for review:

- [libsigrok PR #301: Hantek 1008C oscilloscope support](https://github.com/sigrokproject/libsigrok/pull/301)
- [PulseView PR #132: device mode, input range and trigger-level integration](https://github.com/sigrokproject/pulseview/pull/132)

Until these changes are merged, use the branches from the associated forks and
build both projects against the same development installation prefix as shown
below.

## Supported operation

The driver supports all eight analogue inputs in three distinct acquisition
modes:

- **Trigger** captures finite hardware sweeps and transfers them as separate
  sigrok frames. Time between frames is acquisition dead time and is never
  represented by invented samples.
- **Scan** continuously streams the official Windows application's C9/CA Scan
  transport.
- **Roll** continuously streams the distinct C7/C8 transport. Each hardware row
  contains the enabled channels plus one auxiliary word; the driver discards
  that proven auxiliary word.

Enabled samples are packed in ascending physical-channel order in Scan and
Roll, including sparse selections such as CH1+CH8. Trigger uses physical widths
of 1, 2, 4, 4, 6, 6, 8, and 8 for one through eight enabled channels; unused
final slots at logical counts 3, 5, and 7 are not exposed.

## Build and runtime environment

The development installation keeps sigrok libraries under a private prefix:

```bash
SIGROK_PREFIX="$HOME/tools/sigrok/install"

export PATH="$SIGROK_PREFIX/bin:$PATH"
export LD_LIBRARY_PATH="$SIGROK_PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
```

Build and install libsigrok:

```bash
cd "$HOME/tools/sigrok/libsigrok"

make distclean 2>/dev/null || true
./autogen.sh
./configure --prefix="$SIGROK_PREFIX"
make -j"$(nproc)"
make check
make install
```

Build and install PulseView:

```bash
cd "$HOME/tools/sigrok/pulseview"

rm -rf build
cmake -S . -B build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$SIGROK_PREFIX" \
    -DCMAKE_PREFIX_PATH="$SIGROK_PREFIX"
cmake --build build --parallel "$(nproc)"
cmake --install build
```

Launch the locally installed application:

```bash
pulseview
```

Verify library resolution when diagnosing an installation:

```bash
ldd "$(command -v pulseview)" |
    grep -E 'libsigrok|libsigrokcxx|libsigrokdecode'
```

## USB permissions

Install the supplied udev rule from this repository:

```bash
sudo cp udev/60-hantek-1008c.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Unplug and reconnect the oscilloscope afterward.

## Input range

PulseView exposes the standard device `Range` option:

| Name | Raw setting | Nominal scale |
|---|---:|---:|
| Narrow | `A2=01` | 0.0002 V/count |
| Medium | `A2=02` | 0.00125 V/count |
| Wide | `A2=03` | 0.01 V/count |

These names describe relative input sensitivity. They are not exact V/div or
maximum Vp-p claims. PulseView's per-trace V/div control changes display scale;
it does not replace the device input-range selection.

## Calibration

Calibration is per USB connection path, physical channel, and input range. The
shared format-1 store is normally:

```text
~/.local/share/hantek-1008c/calibration.ini
```

Both the Python reference implementation and libsigrok read and write this same
schema. Close PulseView and other users of the scope, then calibrate through the
installed libsigrok utility:

```bash
sigrok-hantek-1008c-calibrate \
    --sigrok-cli /usr/bin/sigrok-cli \
    --channels 1,2,3,4,5,6,7,8 \
    --ranges Narrow,Medium,Wide
```

To set and remember a maximum permitted change from an existing grounded zero,
add (for example) `--max-zero-shift-counts 50`. The default is 20 ADC counts.
An explicitly supplied limit is saved per device after a successful grounded
capture and is reused by later runs. A rejected capture leaves the known-good
entry and saved limit unchanged.

For each channel the utility first captures all requested grounded ranges, then
asks for one move to the onboard 1 kHz / nominal 2 Vp-p reference and validates
Medium and Wide. Narrow receives grounded-zero calibration only because that
reference over-ranges the sensitive Narrow state. Reference validation never
changes `zero_adc` or `volts_per_count`.

For grounded capture, disconnect or ground every input other than the grounded
target; never leave the onboard reference connected to another channel. For
reference validation, connect the reference only to the target channel and
disconnect or ground every other input. A reference left on another input has
been experimentally shown to contaminate the grounded capture.

The utility retries complete fresh captures for up to 15 seconds after a
transient USB disappearance or timeout and logs every recovery attempt. It
rejects noisy grounded captures and invalid reference amplitude/frequency.

Back up a known-good calibration:

```bash
CALIBRATION_DIR="$HOME/.local/share/hantek-1008c"
cp -a "$CALIBRATION_DIR/calibration.ini" \
    "$CALIBRATION_DIR/calibration-known-good.ini"
sha256sum "$CALIBRATION_DIR/calibration.ini" \
    "$CALIBRATION_DIR/calibration-known-good.ini"
```

Because the current device identity is its physical USB port path, moving the
scope to another port creates a different calibration identity.

## Mode-dependent sample rates

PulseView immediately refreshes the sample-rate selector when Device mode or
the enabled-channel set changes. Rates are samples per second **per enabled
channel**.

### Trigger

| Enabled channels | Advertised rates, slow to fast |
|---:|---|
| 1 | 2k, 4k, 8k, 20k, 40k, 80k, 200k, 400k, 800k, 2.4M |
| 2 | 1k, 2k, 4k, 10k, 20k, 40k, 100k, 200k, 400k, 1.2M |
| 3 or 4 | 500, 1k, 2k, 5k, 10k, 20k, 50k, 100k, 200k, 600k |
| 5 or 6 | 333, 666, 1.333k, 3.333k, 6.666k, 13.333k, 33.333k, 66.666k, 133.333k, 400k |
| 7 or 8 | 250, 500, 1k, 2.5k, 5k, 10k, 25k, 50k, 100k, 300k |

### Scan

| Enabled channels | Advertised rates, slow to fast |
|---:|---|
| 1 | 2, 4, 8, 20, 40, 80, 200, 400, 800 |
| 2 | 1, 2, 4, 10, 20, 40, 100, 200, 400 |
| 3 | 1, 2, 6, 13, 26, 66, 133, 266 |
| 4 | 1, 2, 5, 10, 20, 50, 100, 200 |
| 5 | 1, 4, 8, 16, 40, 80, 160 |
| 6 | 1, 3, 6, 13, 33, 66, 133 |
| 7 | 1, 2, 5, 11, 28, 57, 114 |
| 8 | 1, 2, 5, 10, 25, 50, 100 |

### Roll

| Enabled channels | Advertised rates, slow to fast |
|---:|---|
| 1 | 1, 2, 5, 9, 23, 50, 100, 201, 401, 1003, 2006 |
| 2 | 1, 3, 6, 15, 33, 66, 134, 267, 668, 1337 |
| 3 | 1, 2, 4, 11, 25, 50, 100, 200, 501, 1003 |
| 4 | 2, 3, 9, 20, 40, 80, 160, 401, 802 |
| 5 | 1, 3, 7, 16, 33, 67, 133, 334, 668 |
| 6 | 1, 2, 6, 14, 28, 57, 114, 286, 573 |
| 7 | 1, 2, 5, 12, 25, 50, 100, 250, 501 |
| 8 | 1, 2, 5, 11, 22, 44, 89, 222, 445 |

Integer values are used because libsigrok samplerates cannot represent positive
fractions. Duplicate and sub-1 Sa/s results are omitted.

## Eight-channel Trigger examples

The following captures show the calibrated production driver in PulseView with
all eight channels enabled. CH1 carries a sine wave, CH8 carries the onboard
square-wave reference, and the remaining grounded inputs stay on their own zero
lines.

![Eight channels at 300 kSa/s/channel](images/pulseview-8ch-300ksps-20260905.png)

![Eight channels at 100 kSa/s/channel](images/pulseview-8ch-100ksps-20260905.png)

## Important limitations

- The tested analogue bandwidth is approximately 100 kHz.
- The production Trigger source selector currently exposes automatic/free-run
  (`None`) and CH1. Multichannel acquisition does not yet imply independently
  validated trigger-source selection for CH2 through CH8.
- Trigger frames are real finite sweeps; no samples exist during re-arm and
  transfer dead time.
- Calibration is currently keyed to USB port path because a stable device
  serial identity has not been established.
- A transient USB re-enumeration can change the kernel device address. The
  driver and calibration utility retry complete open/initialization boundaries;
  they do not pretend a partially failed transfer succeeded.
- Calibration and known test waveforms are never used for waveform-specific
  smoothing, thresholding, interpolation, or reconstruction.
