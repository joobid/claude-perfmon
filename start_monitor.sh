#!/bin/bash
# =============================================================================
# start_monitor.sh — CPU/RAM monitoring starter for macOS
#
# Usage: ./start_monitor.sh [samples] [interval_seconds]
#
#   samples          Number of data points to collect  (default: 360)
#   interval_seconds Seconds between samples            (default: 60)
#
# Examples:
#   ./start_monitor.sh              # 360 x 60 s = 6 h  (default)
#   ./start_monitor.sh 720 30       # 720 x 30 s = 6 h, finer resolution
#   ./start_monitor.sh 720 5        # 720 x  5 s = 1 h, stress-test mode
# =============================================================================

SAMPLES="${1:-360}"
INTERVAL="${2:-60}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP=$(date +%d%m%y_%H%M%S)
LOG_FILE="$HOME/informe_cpu_${TIMESTAMP}.txt"
PID_FILE="$SCRIPT_DIR/.monitor_pids"
LOG_PTR="$SCRIPT_DIR/.current_log"
INTERVAL_FILE="$SCRIPT_DIR/.current_interval"
PORT=8765

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     CPU Performance Monitor — macOS          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── Stop any previous instance (top + server) ───────────────────────
if [ -f "$PID_FILE" ]; then
    for PID in $(cat "$PID_FILE"); do
        kill "$PID" 2>/dev/null && echo -e "${YELLOW}↓ Previous process $PID stopped${NC}"
    done
    rm -f "$PID_FILE"
fi
# Liberar el puerto por si quedó algo huérfano
lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null
sleep 1

# ── Compute total duration ───────────────────────────────────────────────────
TOTAL_SECS=$((SAMPLES * INTERVAL))
HOURS=$((TOTAL_SECS / 3600))
MINS=$(( (TOTAL_SECS % 3600) / 60 ))

echo -e "  Samples    : ${YELLOW}${SAMPLES}${NC} (every ${INTERVAL}s → ~${HOURS}h ${MINS}min)"
echo -e "  Log file   : ${YELLOW}${LOG_FILE}${NC}"
echo -e "  Dashboard  : ${YELLOW}http://127.0.0.1:${PORT}${NC}"
echo ""

# ── Start top in background ──────────────────────────────────────────────────
nohup python3 "$SCRIPT_DIR/sampler.py" "$LOG_FILE" "$SAMPLES" "$INTERVAL" \
    > "$SCRIPT_DIR/.sampler.log" 2>&1 &
TOP_PID=$!

# Save active log path and sampling interval (read by server.py)
echo "$LOG_FILE" > "$LOG_PTR"
echo "$INTERVAL" > "$INTERVAL_FILE"

# ── Start web server pointing to the new log file ────────────────────────
nohup python3 "$SCRIPT_DIR/server.py" "$LOG_FILE" "$PORT" \
    > "$SCRIPT_DIR/.server.log" 2>&1 &
SERVER_PID=$!

# Save PIDs so we can stop them later
echo "$TOP_PID $SERVER_PID" > "$PID_FILE"

# ── Verify the server started ─────────────────────────────────────────
sleep 2
if kill -0 "$SERVER_PID" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} top PID       : $TOP_PID  (→ $LOG_FILE)"
    echo -e "${GREEN}✓${NC} Server PID    : $SERVER_PID"
    echo ""
    echo -e "${GREEN}✓ Monitoring is running.${NC}"
    echo -e "  First sample in ~${INTERVAL}s (sampler.py log → .sampler.log)"
    echo -e "  Dashboard → ${YELLOW}http://127.0.0.1:${PORT}${NC}"
    echo -e "  To stop → ${YELLOW}./stop_monitor.sh${NC}"
    echo ""
    open "http://127.0.0.1:${PORT}" 2>/dev/null || true
else
    echo -e "${RED}✗ Server failed to start. Contents of .server.log:${NC}"
    cat "$SCRIPT_DIR/.server.log"
    kill "$TOP_PID" 2>/dev/null
    rm -f "$PID_FILE"
    exit 1
fi
