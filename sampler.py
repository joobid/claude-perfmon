#!/usr/bin/env python3
"""
sampler.py — Reliable CPU/process sampler for Claude Performance Monitor.
Supports macOS (top -l) and Linux / WSL (top -b).

Calls top once per cycle with 2 iterations, discards the stale init sample,
and appends only the real delta measurement to the log file.

Usage: python3 sampler.py <log_file> <samples> <interval_seconds>
"""
import subprocess
import sys
import time
import signal
import re

IS_LINUX = sys.platform.startswith('linux')

log_file = sys.argv[1]
samples  = int(sys.argv[2]) if len(sys.argv) > 2 else 360
interval = int(sys.argv[3]) if len(sys.argv) > 3 else 60

# ── Graceful shutdown on SIGTERM / SIGINT ─────────────────────────────────────
running = True
def _stop(sig, frame):
    global running
    running = False
signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT,  _stop)

print(f'[sampler] Starting: {samples} samples × {interval}s → {log_file}', flush=True)
print(f'[sampler] Platform: {"Linux/WSL" if IS_LINUX else "macOS"}', flush=True)


def _run_top(wait, timeout):
    """Run top with 2 iterations and return the real delta block, or None on failure."""
    try:
        if IS_LINUX:
            # -b batch mode, -n 2 iterations, -d delay in seconds
            cmd = ['top', '-b', '-n', '2', '-d', str(wait)]
        else:
            # macOS: -l log mode, 2 samples, -s interval, -n max processes shown
            cmd = ['top', '-l', '2', '-s', str(wait), '-n', '9999']

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        if IS_LINUX:
            # Each iteration block starts with 'top - HH:MM:SS'
            blocks = [b for b in re.split(r'(?=^top - )', result.stdout, flags=re.MULTILINE)
                      if b.strip() and b.lstrip().startswith('top - ')]
        else:
            blocks = [b for b in re.split(r'(?=^Processes:)', result.stdout, flags=re.MULTILINE)
                      if b.strip() and 'Processes:' in b]

        if len(blocks) >= 2:
            return blocks[-1]
        if blocks:
            return blocks[0]
    except subprocess.TimeoutExpired:
        print('[sampler] WARNING: top timed out', flush=True)
    except Exception as e:
        print(f'[sampler] ERROR: {e}', flush=True)
    return None


# ── Initial quick sample — shows data immediately instead of waiting the full interval ──
print('[sampler] Taking initial sample (quick)...', flush=True)
block = _run_top(wait=1, timeout=15)
count = 0
if block:
    with open(log_file, 'a') as f:
        f.write(block)
    count = 1
    print('[sampler] initial/1 written', flush=True)
else:
    print('[sampler] WARNING: initial sample failed — will retry in main loop', flush=True)

# ── Main sampling loop ─────────────────────────────────────────────────────────
while running and count < samples:
    t0 = time.time()

    # top -l 2 -s <wait>:
    #   block 0 = init sample  (stale CPU deltas — discard)
    #   block 1 = real delta measurement over `wait` seconds
    wait = max(1, interval - 1)
    block = _run_top(wait=wait, timeout=interval + 15)

    if block:
        with open(log_file, 'a') as f:
            f.write(block)
        count += 1
        print(f'[sampler] {count}/{samples}', flush=True)
    else:
        print(f'[sampler] WARNING: no valid block in top output (sample {count+1})', flush=True)

    # Sleep any remaining time in this interval
    elapsed = time.time() - t0
    remaining = interval - elapsed
    if remaining > 0.1 and running:
        time.sleep(remaining)

print('[sampler] Complete.', flush=True)
