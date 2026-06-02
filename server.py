#!/usr/bin/env python3
"""
server.py — Local HTTP server for CPU Performance Monitor (Claude-focused)
Parses macOS `top -l N -s S` output and serves JSON data + dashboard.

Usage: python3 server.py <log_file> [port]
"""

import http.server
import json
import re
import sys
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Optional

# Token-consumption collector (reads ~/.claude/projects/**/*.jsonl).
# Optional: if it fails to import, the dashboard still serves CPU/RAM data.
try:
    from tokens import collect_token_usage
except Exception as _e:                       # pragma: no cover
    collect_token_usage = None
    print(f'[server] WARNING: token collector unavailable: {_e}')

IS_LINUX = sys.platform.startswith('linux')

LOG_FILE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.expanduser('~'), 'informe_cpu.txt')
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
SCRIPT_DIR = Path(__file__).parent

# Sampling interval written by start_monitor.sh at startup
def _get_sample_interval() -> int:
    try:
        v = int((SCRIPT_DIR / '.current_interval').read_text().strip())
        return v if v > 0 else 60
    except Exception:
        return 60

# Keywords to identify Claude processes (case-insensitive).
# Matches: claude, Claude, claude-worker-N, claude-stress, etc.
CLAUDE_KEYWORDS = ['claude']


# ── Total system RAM (authoritative, independent of top output parsing) ─────

def _get_total_ram_gb() -> Optional[float]:
    """Returns total physical RAM installed in the system."""
    # macOS: sysctl hw.memsize returns bytes as integer
    try:
        out = subprocess.run(['sysctl', '-n', 'hw.memsize'],
                             capture_output=True, text=True, timeout=3)
        if out.returncode == 0:
            return int(out.stdout.strip()) / 1024 ** 3
    except Exception:
        pass
    # Linux: /proc/meminfo
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    return int(line.split()[1]) / 1024 ** 2   # KiB → GB
    except Exception:
        pass
    return None

TOTAL_RAM_GB: Optional[float] = _get_total_ram_gb()
print(f'[server] Total RAM detected: {TOTAL_RAM_GB:.2f} GB' if TOTAL_RAM_GB else
      '[server] WARNING: could not detect total system RAM')


# ── Real-time process snapshot via ps ─────────────────────────────────────────

def get_live_ps_procs() -> list:
    """
    Real-time snapshot of all claude-named processes via ps.

    Uses 'command=' (full argv[0] + args) instead of 'comm=' (p_comm, max 15
    chars from executable path).  This catches both:
      • Binaries named 'claude-worker' via hard-link/copy (p_comm = claude-worker)
      • Processes renamed via exec -a / setproctitle (argv[0] = claude-worker-N)
    """
    try:
        result = subprocess.run(
            ['ps', 'ax', '-o', 'pid=,pcpu=,rss=,command='],
            capture_output=True, text=True, timeout=3
        )
        procs = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            # 'command=' gives full argv including args; argv[0] is the first token
            argv0     = parts[3].split()[0] if parts[3].strip() else ''
            argv0_base = os.path.basename(argv0)   # strip leading path

            full_cmd = parts[3] if len(parts) > 3 else ''
            is_stress_worker = '.claude-stress' in full_cmd
            if not is_claude_process(argv0_base) and not is_stress_worker:
                continue
            try:
                pid    = parts[0].strip()
                cpu    = float(parts[1].strip())
                rss_kb = int(parts[2].strip())
                mem_gb = round(rss_kb / 1024 ** 2, 3)
                if rss_kb >= 1024 * 1024:
                    mem_str = f'{rss_kb / 1024 / 1024:.1f}G'
                elif rss_kb >= 1024:
                    mem_str = f'{rss_kb // 1024}M'
                else:
                    mem_str = f'{rss_kb}K'
                # Strip leading dot from hidden-file names (e.g. .claude-worker → claude-worker)
                # If running as plain python3 with stress script, label it as claude-worker
                if is_stress_worker and not is_claude_process(argv0_base):
                    display_name = 'claude-worker'
                else:
                    display_name = argv0_base.lstrip('.')[:30]
                procs.append({
                    'pid':     pid,
                    'cmd':     display_name,
                    'cpu':     cpu,
                    'time':    '-',
                    'mem_gb':  mem_gb,
                    'mem_str': mem_str,
                })
            except (ValueError, IndexError):
                pass
        return sorted(procs, key=lambda x: x['cpu'], reverse=True)
    except Exception as e:
        print(f'[server] WARNING: ps query failed: {e}')
        return []


# ── Unit conversion utilities ──────────────────────────────────────────────────────────

def to_gb(val: float, unit: str) -> float:
    mult = {'B': 1/1024**3, 'K': 1/1024**2, 'M': 1/1024, 'G': 1.0, 'T': 1024.0}
    return val * mult.get(unit.upper(), 0.0)


def parse_mem_value(s: str) -> float:
    """Parses '14G', '3025M', '1898M', '5536K', '0B' → GB."""
    m = re.match(r'([\d.]+)\s*([BKMGT])', str(s), re.IGNORECASE)
    return to_gb(float(m.group(1)), m.group(2)) if m else 0.0


def _parse_rss_linux(s: str) -> float:
    """Linux top RES column (plain KB integer or K/M/G suffix) → GB."""
    s = s.strip().lower()
    try:
        if s.endswith('g'): return float(s[:-1])
        if s.endswith('m'): return float(s[:-1]) / 1024
        if s.endswith('k'): return float(s[:-1]) / 1024 / 1024
        return int(s) / 1024 / 1024   # plain KB (Linux default)
    except (ValueError, AttributeError):
        return 0.0


def is_claude_process(cmd: str) -> bool:
    """True if the process name corresponds to Claude."""
    cmd_lower = cmd.lower()
    return any(kw in cmd_lower for kw in CLAUDE_KEYWORDS)


def get_token_usage() -> dict:
    """Token-consumption summary from Claude Code transcripts (best-effort)."""
    if collect_token_usage is None:
        return {'available': False, 'reason': 'collector not loaded'}
    try:
        return collect_token_usage(interval_s=_get_sample_interval())
    except Exception as e:
        print(f'[server] WARNING: token collection failed: {e}')
        return {'available': False, 'reason': str(e)}


# ── Main parser ───────────────────────────────────────────────────────────────────

def parse_top_output(filepath: str) -> dict:
    try:
        with open(filepath, 'r', errors='replace') as f:
            content = f.read()
    except FileNotFoundError:
        return {'samples': [], 'log_file': filepath, 'sample_count': 0,
                'error': f'File not found: {filepath}'}
    except Exception as e:
        return {'samples': [], 'log_file': filepath, 'sample_count': 0,
                'error': str(e)}

    samples = []

    # Block splitting differs by platform: Linux starts each iteration with 'top - ',
    # macOS starts with 'Processes:'.
    if IS_LINUX:
        raw_blocks = re.split(r'(?=^top - )', content, flags=re.MULTILINE)
    else:
        raw_blocks = re.split(r'(?=^Processes:)', content, flags=re.MULTILINE)

    for block in raw_blocks:
        if not block.strip():
            continue
        if IS_LINUX and not block.lstrip().startswith('top - '):
            continue
        if not IS_LINUX and 'Processes:' not in block:
            continue

        sample = {}

        # ── Timestamp ────────────────────────────────────────────────────────
        if IS_LINUX:
            # Linux top -b only reports time, not date — prepend today's date.
            dt = re.search(r'^top - (\d{2}:\d{2}:\d{2})', block, re.MULTILINE)
            if dt:
                today = date.today().strftime('%Y/%m/%d')
                sample['timestamp']  = f'{today} {dt.group(1)}'
                sample['time_label'] = dt.group(1)
        else:
            dt = re.search(r'^(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})', block, re.MULTILINE)
            if dt:
                sample['timestamp']  = dt.group(1)
                sample['time_label'] = dt.group(1)[11:]  # HH:MM:SS

        # ── Total processes ───────────────────────────────────────────────────
        if IS_LINUX:
            proc = re.search(
                r'Tasks:\s+(\d+)\s+total,\s+(\d+)\s+running,\s+(\d+)\s+sleeping', block)
        else:
            proc = re.search(
                r'Processes:\s+(\d+)\s+total,\s+(\d+)\s+running,\s+(\d+)\s+sleeping', block)
        if proc:
            sample['proc_total']    = int(proc.group(1))
            sample['proc_running']  = int(proc.group(2))
            sample['proc_sleeping'] = int(proc.group(3))

        # ── Load Average ──────────────────────────────────────────────────────
        if IS_LINUX:
            load = re.search(r'load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', block)
        else:
            load = re.search(r'Load Avg:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', block)
        if load:
            sample['load_1m']  = float(load.group(1))
            sample['load_5m']  = float(load.group(2))
            sample['load_15m'] = float(load.group(3))

        # ── System CPU ────────────────────────────────────────────────────────
        if IS_LINUX:
            # %Cpu(s):  3.7 us,  0.9 sy,  0.0 ni, 95.3 id, ...
            cpu = re.search(
                r'%Cpu\(s\):\s*([\d.]+)\s+us,\s*([\d.]+)\s+sy,.*?([\d.]+)\s+id', block)
        else:
            cpu = re.search(
                r'CPU usage:\s*([\d.]+)%\s+user,\s*([\d.]+)%\s+sys,\s*([\d.]+)%\s+idle', block)
        if cpu:
            sample['cpu_user'] = float(cpu.group(1))
            sample['cpu_sys']  = float(cpu.group(2))
            sample['cpu_idle'] = float(cpu.group(3))
            sample['cpu_used'] = round(100.0 - float(cpu.group(3)), 2)

        # ── System physical memory ────────────────────────────────────────────
        if IS_LINUX:
            # MiB Mem :  15836.1 total,  12963.9 free,   1538.8 used,  1580.6 buff/cache
            mem = re.search(
                r'MiB Mem\s*:\s*([\d.]+)\s+total,\s*([\d.]+)\s+free,\s*([\d.]+)\s+used',
                block)
            if mem:
                total_gb = TOTAL_RAM_GB if TOTAL_RAM_GB else float(mem.group(1)) / 1024
                used_gb  = float(mem.group(3)) / 1024
                free_gb  = float(mem.group(2)) / 1024
                sample['mem_used_gb']  = round(used_gb, 2)
                sample['mem_free_gb']  = round(free_gb, 3)
                sample['mem_total_gb'] = round(total_gb, 2)
                if total_gb > 0:
                    sample['mem_pct'] = round(used_gb / total_gb * 100, 1)
            elif TOTAL_RAM_GB:
                sample['mem_total_gb'] = round(TOTAL_RAM_GB, 2)
        else:
            # macOS PhysMem line: "14G used, 1898M unused, ..."
            # Total RAM comes from sysctl at startup (100% reliable).
            phys_line = next((l for l in block.splitlines() if 'PhysMem' in l), '')
            sample['_raw_phys_mem'] = phys_line.strip()

            used_gb = None

            # Match the "used" value, explicitly excluding "unused".
            for pat in [
                r'PhysMem:\s*([\d.]+\s*[BKMGT])\b',
                r'(?<![a-z])([\d.]+\s*[BKMGT])\s+used(?![\w])',
            ]:
                m = re.search(pat, phys_line, re.IGNORECASE)
                if m:
                    candidate = parse_mem_value(m.group(1))
                    if candidate > 0 and (TOTAL_RAM_GB is None or candidate <= TOTAL_RAM_GB * 1.05):
                        used_gb = candidate
                        break

            # Parse "unused" directly — avoids rounding error in top's "used" figure.
            free_gb = None
            mf = re.search(r'([\d.]+\s*[BKMGT])\s+unused', phys_line, re.IGNORECASE)
            if mf:
                free_gb = parse_mem_value(mf.group(1))

            if used_gb is None:
                if free_gb is not None and TOTAL_RAM_GB:
                    used_gb = max(0.0, TOTAL_RAM_GB - free_gb)

            total_gb = TOTAL_RAM_GB
            if used_gb is not None:
                if free_gb is None and total_gb is not None:
                    free_gb = max(0.0, total_gb - used_gb)
                sample['mem_used_gb'] = round(used_gb, 2)
                if free_gb is not None:
                    sample['mem_free_gb'] = round(free_gb, 3)
                if total_gb is not None:
                    sample['mem_total_gb'] = round(total_gb, 2)
                    sample['mem_pct'] = round(used_gb / total_gb * 100, 1)
            elif total_gb is not None:
                sample['mem_total_gb'] = round(total_gb, 2)

        # ── Parse ALL processes ───────────────────────────────────────────────
        all_procs    = []
        claude_procs = []

        if IS_LINUX:
            # Linux columns: PID USER PR NI VIRT RES SHR S %CPU %MEM TIME+ COMMAND
            header_match = re.search(r'^\s*PID\s+USER', block, re.MULTILINE | re.IGNORECASE)
            if header_match:
                lines = block[header_match.end():].strip().splitlines()
                for line in lines:
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) < 12:
                        continue
                    try:
                        pid     = parts[0]
                        cmd     = parts[11]
                        cpu_val = float(parts[8])
                        time_s  = parts[10]
                        mem_gb  = _parse_rss_linux(parts[5])
                        if mem_gb >= 1:
                            mem_str = f'{mem_gb:.1f}G'
                        elif mem_gb * 1024 >= 1:
                            mem_str = f'{int(mem_gb * 1024)}M'
                        else:
                            mem_str = f'{int(mem_gb * 1024 * 1024)}K'

                        proc_entry = {
                            'pid':     pid,
                            'cmd':     cmd[:30],
                            'cpu':     cpu_val,
                            'time':    time_s,
                            'mem_gb':  round(mem_gb, 3),
                            'mem_str': mem_str,
                        }
                        all_procs.append(proc_entry)
                        if is_claude_process(cmd):
                            claude_procs.append(proc_entry)
                    except (ValueError, IndexError):
                        pass
        else:
            # macOS columns: PID COMMAND %CPU TIME #TH #WQ #PORT MEM ...
            header_match = re.search(r'^\s*PID\s+COMMAND', block, re.MULTILINE | re.IGNORECASE)
            if header_match:
                lines = block[header_match.end():].strip().splitlines()
                for line in lines:
                    if not line.strip():
                        break   # blank line signals end of process table
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    try:
                        pid     = parts[0]
                        cmd     = parts[1]
                        cpu_val = float(parts[2])
                        time_s  = parts[3] if len(parts) > 3 else '-'
                        mem_str = parts[7] if len(parts) > 7 else '0B'
                        mem_gb  = parse_mem_value(mem_str)

                        proc_entry = {
                            'pid':     pid,
                            'cmd':     cmd[:30],
                            'cpu':     cpu_val,
                            'time':    time_s,
                            'mem_gb':  round(mem_gb, 3),
                            'mem_str': mem_str,
                        }
                        all_procs.append(proc_entry)
                        if is_claude_process(cmd):
                            claude_procs.append(proc_entry)
                    except (ValueError, IndexError):
                        pass

        # ── Aggregate Claude metrics ──────────────────────────────────────────
        sample['claude_procs']      = sorted(claude_procs, key=lambda x: x['cpu'], reverse=True)
        sample['claude_proc_count'] = len(claude_procs)
        sample['claude_cpu_total']  = round(sum(p['cpu'] for p in claude_procs), 2)
        sample['claude_mem_gb']     = round(sum(p['mem_gb'] for p in claude_procs), 3)

        if sample.get('cpu_used', 0) > 0:
            sample['claude_cpu_pct_of_system'] = round(
                sample['claude_cpu_total'] / sample['cpu_used'] * 100, 1)
        else:
            sample['claude_cpu_pct_of_system'] = 0.0

        if sample.get('mem_total_gb', 0) > 0:
            sample['claude_mem_pct_of_system'] = round(
                sample['claude_mem_gb'] / sample['mem_total_gb'] * 100, 1)
        else:
            sample['claude_mem_pct_of_system'] = 0.0

        if 'timestamp' in sample or 'cpu_used' in sample:
            samples.append(sample)

    return {
        'samples':           samples,
        'log_file':          filepath,
        'sample_count':      len(samples),
        'sample_interval_s': _get_sample_interval(),
    }


# ── HTTP handler ──────────────────────────────────────────────────────────────────

class MonitorHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        try:
            self._handle()
        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self.send_error(500, str(e))
            except Exception:
                pass

    def _handle(self):
        if self.path.startswith('/data'):
            data = parse_top_output(LOG_FILE)

            # ── Augment the latest sample with a real-time ps snapshot ────────
            # top samples every N seconds; ps gives the instantaneous picture.
            # We replace claude_procs in the last sample so the process table
            # always reflects what is actually running right now.
            if data.get('samples'):
                live = get_live_ps_procs()
                last = data['samples'][-1]
                # Use live data if it found something, OR if top found nothing
                if live or not last.get('claude_procs'):
                    last['claude_procs']      = live
                    last['claude_proc_count'] = len(live)
                    last['claude_cpu_total']  = round(sum(p['cpu']    for p in live), 2)
                    last['claude_mem_gb']     = round(sum(p['mem_gb'] for p in live), 3)
                    if last.get('cpu_used', 0) > 0:
                        last['claude_cpu_pct_of_system'] = round(
                            last['claude_cpu_total'] / last['cpu_used'] * 100, 1)
                    if last.get('mem_total_gb', 0) > 0:
                        last['claude_mem_pct_of_system'] = round(
                            last['claude_mem_gb'] / last['mem_total_gb'] * 100, 1)

            # ── Token consumption (from Claude Code transcripts) ──────────────
            data['tokens'] = get_token_usage()

            body = json.dumps(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', len(body))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

        elif self.path in ('/', '/index.html', '/monitor.html'):
            html_path = SCRIPT_DIR / 'monitor.html'
            if html_path.exists():
                body = html_path.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', len(body))
                # Never cache the dashboard: an old tab would keep polling /data
                # with stale JS and miss newly added panels (e.g. tokens).
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404, 'monitor.html not found')

        elif self.path == '/export.csv':
            import csv, io
            data = parse_top_output(LOG_FILE)
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow([
                'timestamp',
                'cpu_used_pct', 'cpu_user_pct', 'cpu_sys_pct', 'cpu_idle_pct',
                'mem_used_gb', 'mem_free_gb', 'mem_total_gb', 'mem_used_pct',
                'load_1m', 'load_5m', 'load_15m',
                'proc_total', 'proc_running',
                'claude_proc_count',
                'claude_cpu_pct', 'claude_cpu_pct_of_system',
                'claude_mem_gb', 'claude_mem_pct_of_system',
            ])
            for s in data.get('samples', []):
                writer.writerow([
                    s.get('timestamp', ''),
                    s.get('cpu_used', ''),
                    s.get('cpu_user', ''),
                    s.get('cpu_sys', ''),
                    s.get('cpu_idle', ''),
                    s.get('mem_used_gb', ''),
                    s.get('mem_free_gb', ''),
                    s.get('mem_total_gb', ''),
                    s.get('mem_pct', ''),
                    s.get('load_1m', ''),
                    s.get('load_5m', ''),
                    s.get('load_15m', ''),
                    s.get('proc_total', ''),
                    s.get('proc_running', ''),
                    s.get('claude_proc_count', ''),
                    s.get('claude_cpu_total', ''),
                    s.get('claude_cpu_pct_of_system', ''),
                    s.get('claude_mem_gb', ''),
                    s.get('claude_mem_pct_of_system', ''),
                ])

            # ── Second section: token consumption time series ─────────────────
            tok = get_token_usage()
            if tok.get('available'):
                tt = tok.get('totals', {})
                td = tok.get('today', {})
                writer.writerow([])
                writer.writerow(['# tokens — cumulative',
                                 'input', 'output', 'cache_read', 'cache_creation',
                                 'total', 'cost_usd'])
                for label, agg in (('all_time', tt), ('today', td)):
                    writer.writerow([label, agg.get('input', ''), agg.get('output', ''),
                                     agg.get('cache_read', ''), agg.get('cache_creation', ''),
                                     agg.get('total', ''), agg.get('cost_usd', '')])
                writer.writerow([])
                writer.writerow(['# tokens — today by interval',
                                 'input', 'output', 'cache_read', 'cache_creation', 'total'])
                ser = tok.get('series', {})
                labels = ser.get('labels', [])
                for i, label in enumerate(labels):
                    writer.writerow([
                        label,
                        ser['input'][i], ser['output'][i], ser['cache_read'][i],
                        ser['cache_creation'][i], ser['total'][i],
                    ])

            body = buf.getvalue().encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition',
                             'attachment; filename="claude_perfmon.csv"')
            self.send_header('Content-Length', len(body))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)

        elif self.path == '/ping':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', 4)
            self.end_headers()
            self.wfile.write(b'pong')

        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        pass  # silenciar logs de acceso


# ── Entry point ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print(f'[server] Listening on http://127.0.0.1:{PORT}')
    print(f'[server] Reading data from: {LOG_FILE}')
    try:
        httpd = http.server.HTTPServer(('127.0.0.1', PORT), MonitorHandler)
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n[server] Stopped.')
    except OSError as e:
        print(f'\n[server] ERROR: {e}')
        print(f'Try: lsof -ti tcp:{PORT} | xargs kill -9')
