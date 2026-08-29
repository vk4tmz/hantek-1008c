#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

WAV="/tmp/hantek-ultraslow-0.001hz-4h.wav"
AUDIO_DEV="plughw:2,0"
LOGDIR="captures/ultraslow-audio-$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$LOGDIR"

echo
echo "============================================================"
echo " Hantek 1008C ultra-slow Scan campaign: A3=24..28"
echo
echo " PHYSICAL CONDITION:"
echo "   CONNECT CH1 TO ATR2x-USB AUDIO OUTPUT"
echo
echo " Reference tone: 0.001 Hz sine"
echo "============================================================"
echo

if [[ ! -f "$WAV" ]]; then
    echo "Generating 4-hour 0.001 Hz reference WAV..."

    python - <<'PY'
import math
import struct
import wave

path = "/tmp/hantek-ultraslow-0.001hz-4h.wav"
rate = 1000
freq = 0.001
duration = 4 * 60 * 60
amplitude = 0.25

with wave.open(path, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)

    block = bytearray()

    for n in range(rate * duration):
        x = amplitude * math.sin(2.0 * math.pi * freq * n / rate)
        block += struct.pack("<h", round(x * 32767))

        if len(block) >= 1024 * 1024:
            w.writeframesraw(block)
            block.clear()

    if block:
        w.writeframesraw(block)

print(f"Created {path}")
PY
else
    echo "Using existing WAV: $WAV"
fi

echo
echo "Starting ATR2x reference tone..."
aplay -q -D "$AUDIO_DEV" "$WAV" &
APLAY_PID=$!

cleanup()
{
    if kill -0 "$APLAY_PID" 2>/dev/null; then
        kill "$APLAY_PID" 2>/dev/null || true
        wait "$APLAY_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

sleep 2

run_profile()
{
    profile="$1"
    duration="$2"

    echo
    echo "============================================================"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting A3=$profile"
    echo "Capture duration: ${duration}s"
    echo "PHYSICAL CONDITION: CH1 CONNECTED TO ATR2x-USB AUDIO OUTPUT"
    echo "============================================================"

    python tools/probe_official_scan.py \
        --profile "$profile" \
        --capture-s "$duration" \
        --poll-ms 5 \
        2>&1 | tee "$LOGDIR/a3-${profile}.log"

    echo
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) completed A3=$profile"
}

run_profile 24 600
run_profile 25 900
run_profile 26 1500
run_profile 27 2500
run_profile 28 5000

echo
echo "============================================================"
echo " ALL ULTRA-SLOW AUDIO CAPTURES COMPLETE"
echo "============================================================"
echo
echo "Logs:"
echo "  $LOGDIR"
echo
echo "Capture JSON files are under:"
echo "  captures/"
echo
