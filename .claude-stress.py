#!/usr/bin/env python3
"""
.claude-stress.py — Heavy-computation worker for claude-perfmon stress test.

Launched via .claude-stress-launcher so that the process appears as
"claude-worker-N" in top/ps (detected by the monitor as a Claude process).

Usage: python3 .claude-stress.py <duration_s> <ram_mb> <worker_id> <rounds>
  duration_s  Seconds of computation per round     (default: 45)
  ram_mb      Megabytes of RAM to allocate          (default: 400)
  worker_id   Worker identifier shown in logs       (default: ?)
  rounds      Rounds to run before exiting (0=∞)   (default: 0)
"""

import sys
import time
import math

DURATION_S = int(sys.argv[1]) if len(sys.argv) > 1 else 45
RAM_MB     = int(sys.argv[2]) if len(sys.argv) > 2 else 400
WORKER_ID  = sys.argv[3]     if len(sys.argv) > 3 else "?"
ROUNDS     = int(sys.argv[4]) if len(sys.argv) > 4 else 0  # 0 = run forever

TAG = f"[claude-worker-{WORKER_ID}]"


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}]{TAG} {msg}", flush=True)


# ── Try to import numpy (preferred for CPU load) ──────────────────────────────
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def allocate_ram(ram_mb: int):
    """Allocate ~ram_mb of RAM and return the array(s) to keep them alive."""
    if HAS_NUMPY:
        # Two square float32 matrices of ~ram_mb/2 MB each
        n = max(100, int(math.sqrt(ram_mb * 1024 * 1024 / 2 / 4)))
        A = np.random.rand(n, n).astype("float32")
        B = np.random.rand(n, n).astype("float32")
        actual_mb = (A.nbytes + B.nbytes) / 1024 / 1024
        log(f"numpy: allocated {actual_mb:.0f} MB  (matrix {n}×{n} float32)")
        return A, B
    else:
        # Pure Python fallback: bytearray
        buf = bytearray(ram_mb * 1024 * 1024)
        log(f"fallback: allocated {ram_mb} MB bytearray")
        return buf, None


def compute_round(A, B, duration_s: int):
    """Burn CPU for duration_s seconds using matrix multiplication."""
    t_end = time.time() + duration_s
    iters = 0

    if HAS_NUMPY:
        while time.time() < t_end:
            _ = np.dot(A, B)   # BLAS matmul — uses all CPU cores via Accelerate/MKL
            iters += 1
            if iters % 5 == 0:
                left = t_end - time.time()
                log(f"iter {iters:4d}  remaining {max(0, left):.0f}s")
    else:
        # Pure Python CPU burn: pointless float arithmetic
        x = 1.23456789
        while time.time() < t_end:
            for _ in range(100_000):
                x = math.sin(x) * math.cos(x) + math.sqrt(abs(x))
            iters += 1
            if iters % 10 == 0:
                left = t_end - time.time()
                log(f"iter {iters:4d}  remaining {max(0, left):.0f}s")

    return iters


# ── Main ──────────────────────────────────────────────────────────────────────
log(f"start  duration={DURATION_S}s  ram={RAM_MB}MB  rounds={'∞' if ROUNDS==0 else ROUNDS}")

A, B = allocate_ram(RAM_MB)

round_num = 0
try:
    while True:
        round_num += 1
        if ROUNDS > 0 and round_num > ROUNDS:
            break
        label = f"round {round_num}" + ("" if ROUNDS == 0 else f"/{ROUNDS}")
        log(f"{label} — start")
        n = compute_round(A, B, DURATION_S)
        log(f"{label} — done ({n} iters)")
        time.sleep(1)

except KeyboardInterrupt:
    pass

log(f"exit after {round_num} rounds")
