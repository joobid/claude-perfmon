#!/bin/bash
# =============================================================================
# start_stress_test.sh — Claude Performance Monitor stress test
#
# Startes N parallel Claude CLI tasks with heavy prompts so that real
# claude processes appear in the dashboard.
#
# Usage: ./start_stress_test.sh [workers] [rounds] [interval_seconds]
#
#   workers          Parallel Claude CLI processes  (default: 3)
#   rounds           Prompt rounds per worker        (default: 5)
#   interval_seconds Monitor sampling interval in s  (default: 5)
#                    Use a short interval (≤10 s) so that claude CLI
#                    processes (2–4 min each) are reliably captured.
#
# Examples:
#   ./start_stress_test.sh              # 3 workers, 5 rounds, 5 s sampling
#   ./start_stress_test.sh 5 3          # 5 workers, 3 rounds, 5 s sampling
#   ./start_stress_test.sh 5 3 10       # 5 workers, 3 rounds, 10 s sampling
#
# Requirements: 'claude' CLI must be installed and authenticated.
# =============================================================================

WORKERS="${1:-3}"
ROUNDS="${2:-5}"
STRESS_INTERVAL="${3:-5}"
STRESS_SAMPLES=$(( 3600 / STRESS_INTERVAL ))   # always cover ~1 hour

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.stress_pids"
LOG_DIR="$SCRIPT_DIR/.stress_logs"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

# ── Check claude CLI is available ─────────────────────────────────────────────
if ! command -v claude &>/dev/null; then
    echo -e "${RED}✗ 'claude' CLI not found in PATH.${NC}"
    echo -e "  Install Claude Code: https://claude.ai/code"
    exit 1
fi

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Claude Performance Monitor — Stress Test     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Workers        : ${YELLOW}${WORKERS}${NC} parallel Claude CLI processes"
echo -e "  Rounds/worker  : ${YELLOW}${ROUNDS}${NC}"
echo -e "  Sample interval: ${YELLOW}${STRESS_INTERVAL}s${NC} (${STRESS_SAMPLES} samples ≈ 1 h coverage)"
echo ""

# ── Auto-start monitor with configured interval if not running ────────────────
if ! lsof -i :8765 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}⚠  Monitor not running — starting with ${STRESS_INTERVAL}s interval...${NC}"
    if [ -f "$SCRIPT_DIR/start_monitor.sh" ]; then
        bash "$SCRIPT_DIR/start_monitor.sh" "$STRESS_SAMPLES" "$STRESS_INTERVAL" &
        echo -e "${GREEN}✓ Monitor started. Waiting for server...${NC}"
        for i in $(seq 1 15); do
            sleep 1
            lsof -i :8765 -sTCP:LISTEN -t >/dev/null 2>&1 && break
            echo -e "  waiting... ($i/15)"
        done
        if ! lsof -i :8765 -sTCP:LISTEN -t >/dev/null 2>&1; then
            echo -e "${RED}✗ Monitor did not start. Check start_monitor.sh${NC}"
            exit 1
        fi
        echo -e "${GREEN}✓ Monitor ready at http://127.0.0.1:8765${NC}"
        echo ""
        echo -e "  Open ${CYAN}http://127.0.0.1:8765${NC} in your browser."
        echo ""
    else
        echo -e "${RED}✗ start_monitor.sh not found${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Monitor already running at http://127.0.0.1:8765${NC}"
    echo -e "  ${YELLOW}Tip:${NC} If using the default 60 s interval, restart with:"
    echo -e "  ${CYAN}./stop_monitor.sh && ./start_monitor.sh ${STRESS_SAMPLES} ${STRESS_INTERVAL}${NC}"
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

# ── Heavy prompts (designed for long streaming responses: 2–4 min each) ───────
PROMPTS=(
    "Write a complete, detailed technical essay of at least 3000 words about the history and future of artificial intelligence. Cover: symbolic AI and expert systems (1950s-1980s), the first AI winter, connectionism and backpropagation (1980s-1990s), the second AI winter, the deep learning revolution (2012+), the transformer architecture breakthrough (2017), large language models and GPT, constitutional AI and RLHF, multimodal models, and what the next decade holds. Include technical depth, specific dates, researchers, papers, and forward-looking analysis. Do not truncate."

    "You are a senior software engineer. Write a COMPLETE, production-ready Python implementation of a red-black tree data structure. Include: full Node and RedBlackTree classes, insert with all rotation and recoloring cases (left-rotate, right-rotate, fix-insert), delete with all transplant and fix-delete cases, search, minimum, maximum, successor, predecessor, and an in-order traversal. Add detailed inline comments explaining EVERY rotation and color-flip step. Then write a comprehensive pytest test suite with at least 25 test cases covering edge cases, sequential inserts, random inserts, and deletions. Do not truncate or abbreviate."

    "Explain in extreme depth how transformer architectures work from first principles. Cover: the attention is all you need paper, scaled dot-product attention with full mathematical derivation, multi-head attention and why multiple heads help, positional encoding (sinusoidal and learned), layer normalization vs batch normalization, feed-forward sublayers, residual connections, the encoder and decoder stacks, masked attention in decoders, cross-attention, beam search vs sampling decoding strategies, temperature and top-p sampling, and how RLHF fine-tuning works on top of a pre-trained transformer. Include LaTeX-style formulas and intuitive explanations. At least 3000 words."

    "Write a comprehensive guide (3000+ words) to distributed systems design patterns with working Python code examples for each: (1) CAP theorem and its real-world implications, (2) eventual consistency and conflict resolution, (3) the Raft consensus algorithm step by step, (4) two-phase commit and its failure modes, (5) the Saga pattern for distributed transactions with choreography and orchestration variants, (6) CQRS and event sourcing with a complete example, (7) circuit breaker pattern with exponential backoff, (8) consistent hashing for load balancing, (9) leader election with ZooKeeper. For each pattern provide a full Python implementation, not pseudocode."

    "Implement a complete working chess engine in Python with the following components: (1) Board representation using a 64-element array with piece encoding, (2) legal move generation for ALL piece types including pawns (en passant, promotion), knights, bishops, rooks, queens, kings (castling, check detection), (3) attack tables for fast check detection, (4) minimax search with alpha-beta pruning to depth 5, (5) iterative deepening with a simple transposition table, (6) a material + positional evaluation function using piece-square tables for each piece type, (7) a simple UCI protocol interface. Write every function completely — no placeholders or abbreviations. The engine should be fully runnable."
)

# ── Start workers ─────────────────────────────────────────────────────────────
echo -e "${GREEN}🚀 Starting $WORKERS Claude CLI workers...${NC}"
echo ""

for i in $(seq 1 $WORKERS); do
    PROMPT_IDX=$(( (i - 1) % ${#PROMPTS[@]} ))
    PROMPT="${PROMPTS[$PROMPT_IDX]}"
    LOG="$LOG_DIR/worker_${i}.log"

    (
        for r in $(seq 1 $ROUNDS); do
            echo "[$(date '+%H:%M:%S')][worker-$i] Round $r/$ROUNDS — calling Claude CLI..." | tee -a "$LOG"
            START=$(date +%s)
            claude --print "$PROMPT" >> "$LOG" 2>&1
            END=$(date +%s)
            ELAPSED=$(( END - START ))
            echo "[$(date '+%H:%M:%S')][worker-$i] Round $r done in ${ELAPSED}s." | tee -a "$LOG"
            sleep 3
        done
        echo "[$(date '+%H:%M:%S')][worker-$i] All $ROUNDS rounds complete." | tee -a "$LOG"
    ) &

    PID=$!
    echo "$PID" >> "$PID_FILE"
    echo -e "  ${GREEN}✓${NC} Worker $i  shell PID ${YELLOW}$PID${NC}  log: $LOG"
done

echo ""
echo -e "${GREEN}✓ Stress test running.${NC}"
echo -e "  ${WORKERS} workers × ${ROUNDS} rounds of heavy Claude CLI calls."
echo -e "  Each call takes ~2–4 min — processes visible in dashboard as ${YELLOW}claude${NC}."
echo ""
echo -e "  Dashboard  → ${CYAN}http://127.0.0.1:8765${NC}"
echo -e "  To stop    → ${YELLOW}./stop_stress_test.sh${NC}"
echo ""
