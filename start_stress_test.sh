#!/bin/bash
# =============================================================================
# start_stress_test.sh — Claude Performance Monitor stress test
#
# Launches N parallel local Python workers that appear as "claude-worker-N"
# in top/ps — detected by the monitor as Claude processes — and perform
# heavy numpy matrix multiplication to drive up CPU and RAM.
#
# NO Claude API calls → zero tokens spent.
# Each worker allocates RAM_MB of memory and runs matmul in a tight loop.
#
# Usage: ./start_stress_test.sh [workers] [rounds] [duration_s] [ram_mb] [interval]
#
#   workers    Parallel worker processes         (default: 4)
#   rounds     Computation rounds per worker     (default: 3)
#   duration_s Seconds of CPU/RAM load per round (default: 45)
#   ram_mb     RAM to allocate per worker (MB)   (default: 400)
#   interval   Monitor sampling interval (s)     (default: 5)
#
# Examples:
#   ./start_stress_test.sh                      # 4 workers, 3×45s, 400 MB each
#   ./start_stress_test.sh 6 5 60 512           # 6 workers, 5×60s, 512 MB each
#   ./start_stress_test.sh 8 0 0 600            # 8 workers, run until stopped
#
# Requirements:
#   • /bin/zsh  (available on all macOS since Catalina — used for exec -a)
#   • python3   (standard on macOS)
#   • numpy     (pip3 install numpy --break-system-packages)
#     Falls back to pure Python if numpy is not installed.
# =============================================================================

WORKERS="${1:-4}"
ROUNDS="${2:-3}"
DURATION_S="${3:-45}"
RAM_MB="${4:-400}"
STRESS_INTERVAL="${5:-5}"
STRESS_SAMPLES=$(( 3600 / STRESS_INTERVAL ))   # ~1 h coverage

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.stress_pids"
LOG_DIR="$SCRIPT_DIR/.stress_logs"
LAUNCHER="$SCRIPT_DIR/.claude-stress-launcher"
WORKER_PY="$SCRIPT_DIR/.claude-stress.py"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

# ── Banner ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Claude Performance Monitor — Stress Test     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
TOTAL_S=$(( DURATION_S * ROUNDS ))
ROUNDS_LABEL="${ROUNDS} rounds × ${DURATION_S}s"
[ "$ROUNDS" -eq 0 ] && ROUNDS_LABEL="∞ (run until stopped)"
echo -e "  Workers        : ${YELLOW}${WORKERS}${NC} parallel processes"
echo -e "  Load per worker: ${YELLOW}${ROUNDS_LABEL}${NC}"
echo -e "  RAM per worker : ${YELLOW}${RAM_MB} MB${NC}"
echo -e "  Sample interval: ${YELLOW}${STRESS_INTERVAL}s${NC}"
echo ""

# ── Check requirements ─────────────────────────────────────────────────────────
if [ ! -f "$LAUNCHER" ]; then
    echo -e "${RED}✗ .claude-stress-launcher not found in $SCRIPT_DIR${NC}"
    exit 1
fi
if [ ! -f "$WORKER_PY" ]; then
    echo -e "${RED}✗ .claude-stress.py not found in $SCRIPT_DIR${NC}"
    exit 1
fi
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}✗ python3 not found in PATH.${NC}"
    exit 1
fi
chmod +x "$LAUNCHER"

# Check numpy availability (non-fatal)
if python3 -c "import numpy" 2>/dev/null; then
    echo -e "  ${GREEN}✓${NC} numpy available — using BLAS matmul for maximum CPU load"
else
    echo -e "  ${YELLOW}⚠${NC}  numpy not found — using pure Python fallback (lower CPU load)"
    echo -e "     To install: ${CYAN}pip3 install numpy --break-system-packages${NC}"
fi
echo ""

# ── Auto-start monitor if not running ─────────────────────────────────────────
if ! lsof -i :8765 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠  Monitor not running — starting with ${STRESS_INTERVAL}s interval...${NC}"
    if [ -f "$SCRIPT_DIR/start_monitor.sh" ]; then
        bash "$SCRIPT_DIR/start_monitor.sh" "$STRESS_SAMPLES" "$STRESS_INTERVAL" &
        echo -e "${GREEN}✓ Monitor started. Waiting for server...${NC}"
        for i in $(seq 1 15); do
            sleep 1
            lsof -i :8765 -sTCP:LISTEN -t >/dev/null 2>&1 && break
        done
        if ! lsof -i :8765 -sTCP:LISTEN -t >/dev/null 2>&1; then
            echo -e "${RED}✗ Monitor did not start. Check start_monitor.sh${NC}"
            exit 1
        fi
        echo -e "${GREEN}✓ Monitor ready at http://127.0.0.1:8765${NC}"
        echo ""
    else
        echo -e "${RED}✗ start_monitor.sh not found${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Monitor already running at http://127.0.0.1:8765${NC}"
    echo ""
fi

# ── Stop any previous stress test ─────────────────────────────────────────────
if [ -f "$PID_FILE" ]; then
    echo -e "${YELLOW}↓ Stopping previous stress test...${NC}"
    while IFS= read -r pid; do
        pkill -P "$pid" 2>/dev/null
        kill "$pid" 2>/dev/null && echo -e "  PID $pid stopped"
    done < "$PID_FILE"
    rm -f "$PID_FILE"
    sleep 1
fi

mkdir -p "$LOG_DIR"
> "$PID_FILE"

# ── Launch workers ─────────────────────────────────────────────────────────────
echo -e "${GREEN}🚀 Starting ${WORKERS} claude-worker processes...${NC}"
echo ""

for i in $(seq 1 $WORKERS); do
    LOG="$LOG_DIR/worker_${i}.log"
    PROC_NAME="claude-worker-${i}"

    # The launcher (zsh) uses `exec -a $PROC_NAME python3 ...`
    # → process replaces zsh, appears as "claude-worker-N" in top/ps
    "$LAUNCHER" "$PROC_NAME" "$WORKER_PY" \
        "$DURATION_S" "$RAM_MB" "$i" "$ROUNDS" \
        > "$LOG" 2>&1 &

    PID=$!
    echo "$PID" >> "$PID_FILE"
    echo -e "  ${GREEN}✓${NC}  $PROC_NAME  PID ${YELLOW}$PID${NC}  log: $(basename "$LOG")"
done

echo ""
echo -e "${GREEN}✓ Stress test running.${NC}"
echo -e "  ${WORKERS} workers visible in top/ps as ${YELLOW}claude-worker-1…${WORKERS}${NC}"
echo -e "  Each allocates ${YELLOW}${RAM_MB} MB RAM${NC} and burns CPU with numpy matmul."
echo ""
echo -e "  Dashboard  → ${CYAN}http://127.0.0.1:8765${NC}"
echo -e "  To stop    → ${YELLOW}./stop_stress_test.sh${NC}"
echo ""
