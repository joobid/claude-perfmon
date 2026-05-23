#!/usr/bin/env python3
"""
sampler.py — Reliable macOS CPU/process sampler for Claude Performance Monitor.

Replaces `top -l N -s S` (which dies in nohup mode) with a robust Python loop
that calls `top -l 2 -s <interval>` once per cycle, discards the init sample,
and appends only the real delta measurement to the log file.

Usage: python3 sampler.py <log_file> <samples> <interval_seconds>
"""
import subprocess
import sys
import time
import signal
import re
from pathlib import Path

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

count = 0
while running and count < samples:
    t0 = time.time()
    try:
        # top -l 2 -s <wait>:
        #   block 0 = init sample  (stale CPU deltas — discard)
        #   block 1 = real delta measurement over `wait` seconds
        wait = max(1, interval - 1)
        result = subprocess.run(
            ['top', '-l', '2', '-s', str(wait), '-n', '9999'],
            capture_output=True, text=True, timeout=interval + 15
        )
        out = result.stdout

        # Split on lines starting with "Processes:" (same logic as server.py)
        blocks = [
            b for b in re.split(r'(?=^Processes:)', out, flags=re.MULTILINE)
            if b.strip() and 'Processes:' in b
        ]

        if len(blocks) >= 2:
            # Write only the second (real delta) block
            block_to_write = blocks[-1]
        elif blocks:
            # Fallback: only one block found, write it anyway
            block_to_write = blocks[0]
        else:
            print(f'[sampler] WARNING: no Processes: block in top output (sample {count+1})', flush=True)
            block_to_write = None

        if block_to_write:
            with open(log_file, 'a') as f:
                f.write(block_to_write)
            count += 1
            print(f'[sampler] {count}/{samples}', flush=True)

    except subprocess.TimeoutExpired:
        print(f'[sampler] WARNING: top timed out on sample {count + 1}', flush=True)
    except Exception as e:
        print(f'[sampler] ERROR: {e}', flush=True)

    # Sleep any remaining time in this interval
    elapsed = time.time() - t0
    remaining = interval - elapsed
    if remaining > 0.1 and running:
        time.sleep(remaining)

print('[sampler] Complete.', flush=True)
