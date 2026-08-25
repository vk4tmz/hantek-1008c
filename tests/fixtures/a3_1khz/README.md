# Hantek 1008C A3 / 1 kHz regression corpus

Captured 2026-08-25 from the Hantek 1008C onboard 1 kHz, 2 Vpp square-wave
calibration output connected to CH1.  Only CH1 was enabled (`A0=01`,
`AA=01 00 00 00 00 00 00 00`).  The only intentional acquisition change
between records was `A3`.

The corpus preserves the original capture metadata, transaction logs and raw
`C6/A6` buffer 02/03 payloads.  It is intended as protocol-archaeology and
regression data; do not regenerate fixtures merely to make a failing test pass.

Empirical timing anchors from raw transition-impulse clusters:

| A3 | half-period (samples) | rate for 1 kHz input |
|----|-----------------------|----------------------|
| 11 | ~400                  | ~0.8 MS/s            |
| 10 | ~400                  | ~0.8 MS/s            |
| 0F | ~1200                 | ~2.4 MS/s            |
| 0E | ~1200                 | ~2.4 MS/s            |

Each CH1-only acquisition contains 8000 payload bytes = 4000 little-endian
16-bit words, split as 500 bytes in buffer 02 and 7500 bytes in buffer 03.
