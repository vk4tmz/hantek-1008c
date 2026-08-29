#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

LOGDIR="captures/ultraslow-ground-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$LOGDIR"

echo
echo "============================================================"
echo " Hantek 1008C ultra-slow Scan grounded campaign: A3=23..28"
echo
echo " PHYSICAL CONDITION:"
echo "   GROUND CH1"
echo
echo "   KEEP CH1 GROUNDED FOR THE ENTIRE CAMPAIGN"
echo "============================================================"
echo

run_profile()
{
    profile="$1"
    duration="$2"

    echo
    echo "============================================================"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting A3=$profile"
    echo "Capture duration: ${duration}s"
    echo "PHYSICAL CONDITION: GROUND CH1"
    echo "============================================================"

    python tools/probe_official_scan.py \
        --profile "$profile" \
        --capture-s "$duration" \
        --poll-ms 5 \
        2>&1 | tee "$LOGDIR/a3-${profile}.log"

    echo
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) completed A3=$profile"
}

# Approximate expected observation counts:
#   A3=23  0.8 Sa/s  ×   60 s  ~= 48
#   A3=24  0.4 Sa/s  ×   90 s  ~= 36
#   A3=25  0.2 Sa/s  ×  150 s  ~= 30
#   A3=26 0.08 Sa/s  ×  300 s  ~= 24
#   A3=27 0.04 Sa/s  ×  600 s  ~= 24
#   A3=28 0.02 Sa/s  × 1200 s  ~= 24

run_profile 23   60
run_profile 24   90
run_profile 25  150
run_profile 26  300
run_profile 27  600
run_profile 28 1200

echo
echo "============================================================"
echo " ALL ULTRA-SLOW GROUNDED CAPTURES COMPLETE"
echo "============================================================"
echo
echo "PHYSICAL CONDITION THROUGHOUT: CH1 GROUNDED"
echo
echo "Logs:"
echo "  $LOGDIR"
echo
echo "Capture JSON files:"
echo "  captures/"
echo
