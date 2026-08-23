# Hantek 1008C Linux

Linux USB protocol research and tooling for the Hantek 1008C 8-channel USB oscilloscope.

Confirmed on the development unit:

- VID:PID `0783:5725`
- Configuration `1`, interface `0`
- Bulk IN `0x81`, bulk OUT `0x02`
- 64-byte max packets
- Observed at USB full-speed (12 Mbit/s)
- No kernel driver bound to interface 0

Confirmed protocol transaction:

```text
OUT 0x02: F3
IN  0x81: F3
```

## Setup

```bash
cd ~/tools/hantek-1008c
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## USB permissions

```bash
sudo cp udev/60-hantek-1008c.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug/reconnect the scope.

## Tools

Enumeration only:

```bash
python tools/enumerate.py
```

F3 keepalive/ping:

```bash
python tools/ping.py
```

Conservative query-like command probing:

```bash
python tools/probe_queries.py
```

Restrict probes if desired:

```bash
python tools/probe_queries.py --command B0
python tools/probe_queries.py --command B5 --command B6
```

Transactions are logged as JSONL under `captures/`.

## Direction

1. Confirm/document USB transport.
2. Characterise query-like commands.
3. Capture vendor-software USB traffic.
4. Run controlled one-variable protocol experiments.
5. Decode acquisition framing/sample representation.
6. Build a reliable Python reference implementation.
7. Evaluate a native libsigrok driver for PulseView.

See `docs/protocol.md`.
