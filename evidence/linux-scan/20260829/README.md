# Linux official Scan Mode evidence — 2026-08-29

This directory preserves the first complete A3=1A / 500 ms/div Linux run used
to refine C9/CA semantics.  Files are gzip-compressed without modification.

Observed in the JSON/transaction evidence:

- 305 C9 polls, 304 CA transactions.
- First non-zero C9: 2992; one CA transaction followed by C9=0.
- Steady-state C9 counts: 8 (9x), 10 (211x), 12 (81x), 14 (2x).
- For all steady-state counts, bytes after the C9-sized CA prefix were zero.
- Immediate post-CA C9 was zero except one observation of 4.

The original v2 diagnostic included the first 64-byte oversize/startup CA
packet in the raw `.bin`.  The subsequent v3 probe intentionally quarantines
such C9>64 packets instead of treating them as samples.

### A3=1C stateful-framing evidence

`20260829T054750Z_official-scan.json.gz` is the uploaded Linux A3=1C
(2 s/div) diagnostic result used to validate the stateful candidate-row
framing change.  It contains 1586 steady-state bytes, 396 complete candidate
4-byte rows, a 2-byte capture-end tail, and the neutral word0/word1 statistics
recorded in `docs/official-scan-linux-probe.md`.  Only the JSON result was
uploaded for this run; no binary or transaction log is implied to be present.
