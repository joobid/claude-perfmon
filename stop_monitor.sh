#!/bin/bash
# stop_monitor.sh — Stops the CPU monitor
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.monitor_pids"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo ""
if [ ! -f "$PID_FILE" ]; then
    echo -e "${YELLOW}No active monitor found.${NC}"
    exit 0
fi

PIDS=$(cat "$PID_FILE")
STOPPED=0
for PID in $PIDS; do
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        echo -e "${GREEN}✓${NC} Process $PID stopped."
        STOPPED=$((STOPPED + 1))
    fi
done

rm -f "$PID_FILE"
[ $STOPPED -eq 0 ] && echo -e "${YELLOW}Processes had already finished.${NC}" \
                    || echo -e "\n${GREEN}Monitor stopped.${NC}"
echo ""
