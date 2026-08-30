# Multi-channel samplerate protocol lab

This lab is intentionally broader than the first implementation change.  It is
designed to answer the channel-width, A0-versus-AA, sparse-mask, per-channel
samplerate, repeatability, and odd-partner-lane questions with as few code/test
iterations as practical.

The test program is `tools/probe_multichannel_samplerate.py`.  It retains raw
buffer 02/03 data, USB transaction logging, timing/ready-state metrics, and a
JSON report.  Known test frequencies are measurement references only; no
waveform-specific filtering, thresholding, flattening, smoothing, repair, or
reconstruction is applied.

## Suite `rate`

Runs contiguous CH1..CHN for N=1..8 using the acquisition widths observed in
the official Windows application: 1,2,4,4,6,6,8,8.  Two captures per plan are
made by default.  It measures physical frame size, per-lane word counts, CH1
period/sample rate, CH2 period/sample rate when present, hardware ready state,
and acquisition timings.

Run this at both validated Triggered A3 rates (11 and 0F).  This checks whether
the channel-width relationship is invariant across the two production-rate
families rather than assuming the 10 ms/div Windows observation generalises.

## Suite `semantics`

At each odd boundary N=3,5,7 the lab runs all four combinations:

- A0 logical count + AA logical mask
- A0 rounded width + AA logical mask
- A0 logical count + AA rounded-width mask
- A0 rounded width + AA rounded-width mask

This isolates which command controls physical acquisition geometry.  It also
runs sparse masks CH1+CH8, CH1+CH3, CH1+CH4, and CH1+CH6 to check whether active
physical channels are packed into the returned stream.

## Suite `partner`

This is run three times, with a distinctive 4 kHz signal moved to CH4, CH6,
and CH8 respectively while CH1 remains the 1 kHz trigger/reference.  For each
odd logical count it compares the exact logical mask against the official
Windows rounded-width mask.  The result tells us whether the extra lane carries
the adjacent physical ADC input or is padding/internal acquisition state.

## Evidence discipline

The official Windows width table remains an observation, not an architectural
claim.  Python results are protocol-lab evidence until hardware validation is
complete.  Only then should the canonical Python acquisition API and the
libsigrok production driver gain a multi-channel sampling model.
