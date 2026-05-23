# Claude Performance Monitor

A lightweight local dashboard that tracks **CPU and RAM consumed by Claude** in real time,
comparing them against total system resources. Built with a Python HTTP server and a
single-page HTML dashboard — no external dependencies beyond Python 3.

![Dashboard showing Claude CPU and RAM gauges, time-series charts, and process table](https://raw.githubusercontent.com/jootef/claude-performance-monitor/main/screenshot.png)

---

## What it does

- Collects system metrics every N seconds using the OS process monitor
- Identifies **all processes named "claude"** and aggregates their CPU and RAM
- Serves a live dashboard at `http://127.0.0.1:8765` that refreshes automatically
- Shows:
  - **Segmented resource bars** — Claude's share of total CPU and RAM at a glance
  - **Stacked time-series charts** — Claude vs rest-of-system over the full session
  - **CPU donut** — proportional breakdown of Claude / other / idle
  - **Process table** — every Claude subprocess with individual CPU and memory

---

## Architecture

```
start_monitor.sh  [samples] [interval_s]
  │
  ├─ top -l <samples> -s <interval_s>  → ~/informe_cpu_YYMMDD_HHMMSS.txt
  │
  └─ server.py  <log_file>             → http://127.0.0.1:8765
       │
       ├─ GET /data   → JSON (parsed top output, aggregated Claude metrics)
       └─ GET /       → monitor.html (dashboard, polls /data every 5 s)
```

| File | Purpose |
|---|---|
| `start_monitor.sh` | Starts `top` sampler + web server; kills any previous instance |
| `stop_monitor.sh` | Gracefully stops data collection and the web server |
| `server.py` | Python 3 HTTP server — parses `top` output, aggregates Claude processes, serves JSON + HTML |
| `monitor.html` | Self-contained dashboard (Chart.js via CDN) |
| `demo.sh` | **All-in-one**: starts monitor + stress test + opens browser |
| `start_stress_test.sh` | Startes N parallel `claude --print` calls — real Claude processes |
| `stop_stress_test.sh` | Stops all stress workers |

---

## macOS

### Requirements

- macOS 11 or later (Intel or Apple Silicon)
- Python 3 (pre-installed on macOS 12+; otherwise `brew install python`)

### Quick start

```bash
# Clone or download
git clone https://github.com/jootef/claude-performance-monitor.git
cd claude-performance-monitor

# Make scripts executable (first time only)
chmod +x *.sh

# Start with default settings (360 samples × 60 s = 6 hours)
./start_monitor.sh

# The browser opens automatically at http://127.0.0.1:8765
# First data point appears after the first interval (60 s by default)
```

**Customise the sampling interval:**

```bash
./start_monitor.sh              # 360 × 60 s = 6 h  (default)
./start_monitor.sh 720 30       # 720 × 30 s = 6 h, finer resolution
./start_monitor.sh 720 5        # 720 ×  5 s = 1 h, stress-test mode
./start_monitor.sh 20 10        # 20  × 10 s ≈ 3 min, quick test
```

### Stop

```bash
./stop_monitor.sh
```

---

## Verifying the monitor works (stress test)

The stress test startes **real Claude CLI processes** (`claude --print`) with
heavy prompts so that genuine `claude` processes appear in the dashboard.

> **Requirements:**
> - `claude` CLI installed and authenticated ([claude.ai/code](https://claude.ai/code))
> - Use a **short sampling interval** (5 s recommended) so that CLI processes
>   (~2–4 min each) are reliably captured in every sample window

### Option A — All in one command (recommended)

```bash
./demo.sh                    # 3 workers × 5 rounds, 5 s sampling (default)
./demo.sh 5 3                # 5 workers × 3 rounds, 5 s sampling
./demo.sh 5 3 10             # 5 workers × 3 rounds, 10 s sampling
```

`demo.sh` starts the monitor with the chosen interval, startes the workers,
and opens the browser automatically.

### Option B — Step by step

```bash
# Step 1 — start the monitor with a short interval
./start_monitor.sh 720 5

# Step 2 — in a second terminal, run the stress test
./start_stress_test.sh              # 3 workers, 5 rounds, 5 s (default)
./start_stress_test.sh 5 3          # 5 workers, 3 rounds, 5 s
./start_stress_test.sh 5 3 10       # 5 workers, 3 rounds, 10 s
```

> If the monitor is not already running, `start_stress_test.sh` starts it
> automatically with the configured interval.
>
> If the monitor **is** already running with the default 60 s interval, restart it:
> ```bash
> ./stop_monitor.sh && ./start_monitor.sh 720 5
> ```

### Why 5-second intervals for the stress test?

Each `claude --print` call takes 2–4 minutes (it streams from the API).
With 60 s sampling there is a high chance of missing a process that starts
and finishes between two samples. At 5 s, each call is captured ~24–48 times,
giving smooth curves in the charts.

### What you will see in the dashboard

- New rows in the **Claude Processes** table — one per active `claude` CLI call
- Spikes in the **CPU over time** and **RAM over time** charts
- Rising values in the **Claude processes count** bar chart

### Stop everything

```bash
./stop_stress_test.sh   # stops stress workers
./stop_monitor.sh       # stops data collection and web server
```

---

## How it works on macOS

`start_monitor.sh` runs `top` in logging mode:

```bash
nohup top -l <samples> -s <interval_seconds> > ~/informe_cpu_YYMMDD_HHMMSS.txt &
```

- `-l <N>` — logging mode, N samples total
- `-s <S>` — S-second interval between samples
- `nohup` + `&` — keeps running after the terminal closes

`server.py` parses each sample block (delimited by `Processes:`) and extracts
CPU usage, physical memory (via `sysctl hw.memsize` for authoritative total RAM),
load average, and the full process list. It aggregates all processes whose name
contains `"claude"` (case-insensitive) and exposes the result as JSON at `/data`.

---

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `samples` (arg 1 of `start_monitor.sh`) | `360` | Number of data points to collect |
| `interval_seconds` (arg 2) | `60` | Seconds between samples — use `5` for stress-test mode |
| `workers` (arg 1 of `start_stress_test.sh`) | `3` | Parallel Claude CLI processes |
| `rounds` (arg 2 of `start_stress_test.sh`) | `5` | Prompt rounds per worker |
| `interval_seconds` (arg 3 of `start_stress_test.sh`) | `5` | Sampling interval when auto-starting the monitor |
| `PORT` | `8765` | HTTP port for the dashboard (edit in `server.py`) |
| `CLAUDE_KEYWORDS` | `['claude']` | Process name filters (edit in `server.py`) |

**Sampling interval quick reference:**

| Use case | Command | Coverage |
|---|---|---|
| Normal monitoring (default) | `./start_monitor.sh` | 360 × 60 s = 6 h |
| Fine-grained monitoring | `./start_monitor.sh 720 30` | 720 × 30 s = 6 h |
| Stress-test mode | `./start_monitor.sh 720 5` | 720 × 5 s = 1 h |
| Custom | `./start_monitor.sh <N> <S>` | N × S seconds total |

To track additional processes (e.g. also monitor `node` or `python`), edit `server.py`:

```python
CLAUDE_KEYWORDS = ['claude', 'node', 'python']
```

---

## Dashboard panels

| Panel | What it shows |
|---|---|
| **CPU gauge** | Claude's CPU % vs total active CPU, segmented bar (Claude · Others · Idle) |
| **RAM gauge** | Claude's RAM in GB vs total, segmented bar (Claude · Others · Free) |
| **CPU chart** | Stacked area over time — Claude (orange) + other processes (blue) |
| **RAM chart** | Stacked area over time — Claude (orange) + other processes (blue) |
| **Process count** | Bar chart of active Claude subprocesses per sample |
| **Load average** | System load 1m / 5m / 15m |
| **CPU donut** | Proportional breakdown for the latest sample |
| **Process table** | All Claude subprocesses — PID, name, CPU%, RAM |

---

## Troubleshooting

**No connection / dashboard won't load**
Open the dashboard via `http://127.0.0.1:8765`, not by double-clicking `monitor.html`.
Browsers block local `fetch()` requests from `file://` URLs.

**RAM shows `—` or "Others" shows 0 GB**
Check that `server.py` can read the `PhysMem:` line from the log:
```bash
grep 'PhysMem' ~/informe_cpu_*.txt | tail -3
```
If it prints nothing, your macOS version may use a different field name — open an issue.

**Port already in use**
```bash
lsof -ti tcp:8765 | xargs kill -9
./start_monitor.sh
```

**No Claude processes detected**
The filter matches process names containing `"claude"` (case-insensitive). Verify with:
```bash
ps aux | grep -i claude
```

**Stress test workers not showing in dashboard**
Make sure the monitor is running with a short interval (≤ 10 s):
```bash
./stop_monitor.sh && ./start_monitor.sh 720 5
./start_stress_test.sh
```

---

## Linux

### Requirements

- Python 3
- `top` (included in `procps` on Debian/Ubuntu, `procps-ng` on Fedora/RHEL)

### Differences from macOS

Linux `top` uses **batch mode** (`-b`) instead of `-l`, and the output format is different.
You need a Linux-specific start script and a small adjustment to `server.py`.

### Start script for Linux

Create `start_monitor_linux.sh`:

```bash
#!/bin/bash
SAMPLES="${1:-360}"
INTERVAL="${2:-60}"
TIMESTAMP=$(date +%d%m%y_%H%M%S)
LOG_FILE="$HOME/informe_cpu_${TIMESTAMP}.txt"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# top in batch mode: -b batch, -n samples, -d interval (seconds)
nohup top -b -n "$SAMPLES" -d "$INTERVAL" > "$LOG_FILE" 2>/dev/null &
echo "top PID: $!"
echo "$LOG_FILE" > "$SCRIPT_DIR/.current_log"
nohup python3 "$SCRIPT_DIR/server_linux.py" "$LOG_FILE" 8765 \
    > "$SCRIPT_DIR/.server.log" 2>&1 &
echo "Server PID: $!"
sleep 2
echo "Dashboard → http://127.0.0.1:8765"
xdg-open "http://127.0.0.1:8765" 2>/dev/null || true
```

### Parser adjustments for Linux (`server_linux.py`)

Linux `top -b` sample blocks look like:

```
top - 10:30:00 up 2 days, load average: 1.23, 1.45, 1.67
Tasks: 543 total,   3 running, 540 sleeping
%Cpu(s): 12.5 us,  8.3 sy,  0.0 ni, 79.1 id,  0.1 wa
MiB Mem :  15826.5 total,   1898.2 free,  12025.8 used
MiB Swap:   2048.0 total,   1024.0 free,   1024.0 used

  PID USER   PR  NI    VIRT    RES  %CPU  %MEM  COMMAND
 1234 user   20   0 1234567 456789  12.5   2.8  Claude
```

Key regex differences in `server_linux.py`:

```python
# Timestamp
re.search(r'top - (\d{2}:\d{2}:\d{2})', block)
# CPU (idle is the 4th field)
re.search(r'%Cpu.*?(\d+\.\d+)\s+us.*?(\d+\.\d+)\s+sy.*?(\d+\.\d+)\s+id', block)
# Memory (MiB)
re.search(r'MiB Mem\s*:\s*([\d.]+)\s+total,\s*([\d.]+)\s+free,\s*([\d.]+)\s+used', block)
# Process: column order is PID(0) USER(1) PR(2) NI(3) VIRT(4) RES(5) %CPU(8) COMMAND(11)
```

---

## Windows

### Requirements

- Python 3 (https://python.org)
- `psutil` library: `pip install psutil`

### Recommended approach: Python collector

On Windows, `top` is not available. The cleanest cross-platform approach is a Python
script using **psutil** — it produces the same JSON format that `server.py` already serves:

Create `collect_windows.py`:

```python
import psutil, time, json, sys, os
from datetime import datetime

samples   = int(sys.argv[1]) if len(sys.argv) > 1 else 360
interval  = int(sys.argv[2]) if len(sys.argv) > 2 else 60
timestamp = datetime.now().strftime('%d%m%y_%H%M%S')
log_file  = os.path.join(os.path.expanduser('~'), f'informe_cpu_{timestamp}.json')

results = []
for i in range(samples):
    cpu_pct    = psutil.cpu_percent(interval=1)
    mem        = psutil.virtual_memory()
    load       = psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0)
    procs_raw  = []
    for p in psutil.process_iter(['pid','name','cpu_percent','memory_info']):
        try:
            procs_raw.append({
                'pid':  str(p.info['pid']),
                'cmd':  p.info['name'],
                'cpu':  p.info['cpu_percent'] or 0.0,
                'mem_gb': (p.info['memory_info'].rss or 0) / 1024**3,
                'mem_str': f"{(p.info['memory_info'].rss or 0) // 1024 // 1024}M",
                'time': '-',
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    results.append({
        'timestamp':  datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
        'cpu_used':   round(cpu_pct, 2),
        'cpu_idle':   round(100 - cpu_pct, 2),
        'mem_used_gb':  round(mem.used  / 1024**3, 2),
        'mem_total_gb': round(mem.total / 1024**3, 2),
        'mem_free_gb':  round(mem.available / 1024**3, 2),
        'mem_pct':      mem.percent,
        'load_1m': round(load[0], 2),
        'load_5m': round(load[1], 2),
        'load_15m': round(load[2], 2),
        'processes': procs_raw,
    })
    with open(log_file, 'w') as f:
        json.dump(results, f)
    if i < samples - 1:
        time.sleep(interval - 1)  # -1 because cpu_percent already waited 1s
print(f"Done. Log: {log_file}")
```

Then create `server_windows.py` — a variant of `server.py` that reads the JSON file
directly instead of parsing `top` text output (PR welcome).

### Windows start (PowerShell)

```powershell
# Install dependency (once)
pip install psutil

# Start collector in background
$job = Start-Job -ScriptBlock {
    python "$using:PSScriptRoot\collect_windows.py" 360 60
}

# Start web server
Start-Process python -ArgumentList "server_windows.py $env:USERPROFILE\informe_cpu_*.json 8765" -WindowStyle Hidden

# Open dashboard
Start-Process "http://127.0.0.1:8765"
```

---

## License

MIT
