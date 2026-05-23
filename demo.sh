#!/bin/bash
# =============================================================================
# demo.sh — Starts monitor + Claude CLI stress test in one step
#
# Usage: ./demo.sh [workers] [rounds] [interval_seconds]
#
#   workers          Parallel Claude CLI workers  (default: 3)
#   rounds           Rounds per worker             (default: 5)
#   interval_seconds Monitor sampling interval     (default: 5)
#
# Examples:
#   ./demo.sh                  # 3 workers, 5 rounds, 5 s sampling
#   ./demo.sh 5 3              # 5 workers, 3 rounds, 5 s sampling
#   ./demo.sh 5 3 10           # 5 workers, 3 rounds, 10 s sampling
# =============================================================================

WORKERS="${1:-3}"
ROUNDS="${2:-5}"
STRESS_INTERVAL="${3:-5}"
STRESS_SAMPLES=$(( 3600 / STRESS_INTERVAL ))

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8765

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   Claude Performance Monitor + Stress Test       ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── 1. Start monitor with configured interval if not already running ──────────
if lsof -i :${PORT} -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} Monitor already running at http://127.0.0.1:${PORT}"
else
    echo -e "${YELLOW}▶ Starting monitor (${STRESS_SAMPLES} samples × ${STRESS_INTERVAL}s)...${NC}"
    bash "${SCRIPT_DIR}/start_monitor.sh" "${STRESS_SAMPLES}" "${STRESS_INTERVAL}"
    sleep 3
fi

# ── 2. Start stress test ─────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}▶ Starting Claude CLI stress test (${WORKERS} workers × ${ROUNDS} rounds)...${NC}"
bash "${SCRIPT_DIR}/start_stress_test.sh" "${WORKERS}" "${ROUNDS}" "${STRESS_INTERVAL}"

# ── 3. Open dashboard ─────────────────────────────────────────────────────────
sleep 2
echo -e "${GREEN}▶ Opening dashboard...${NC}"
open "http://127.0.0.1:${PORT}" 2>/dev/null || echo "Open http://127.0.0.1:${PORT} in your browser"
