#!/bin/bash
# stop_stress_test.sh — Stop all Claude stress test workers

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.stress_pids"
LOG_DIR="$SCRIPT_DIR/.stress_logs"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

if [ ! -f "$PID_FILE" ]; then
    echo -e "${YELLOW}No stress test PID file found — nothing to stop.${NC}"
    exit 0
fi

echo -e "${YELLOW}↓ Stopping Claude stress test workers...${NC}"
while IFS= read -r pid; do
    if kill -0 "$pid" 2>/dev/null; then
        # Kill the shell wrapper and its claude CLI children
        pkill -P "$pid" 2>/dev/null
        kill "$pid" 2>/dev/null
        echo -e "  ${GREEN}✓${NC} PID $pid stopped"
    else
        echo -e "  (PID $pid already gone)"
    fi
done < "$PID_FILE"

rm -f "$PID_FILE"

# Remove the claude-worker binary created at startup
rm -f "$SCRIPT_DIR/claude-worker" 2>/dev/null

echo -e "${GREEN}✓ Stress test stopped.${NC}"
