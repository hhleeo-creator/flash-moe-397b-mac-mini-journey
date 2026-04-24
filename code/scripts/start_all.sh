#!/bin/bash
# Full stack startup: infer (8000) + wrapper (8771) + telegram bot.
# Idempotent — kills old sessions before starting.
# Run after reboot.

set -e

echo "=== Flash-MoE 397B Full Stack Startup ==="
date

LOG_DIR=/Users/migi/flashmoe_logs
mkdir -p "$LOG_DIR"

# === 1. Stop existing ===
echo ""
echo "[1/4] Cleaning old sessions..."
for SESSION in telegram_bot wrapper infer_serve; do
  if tmux kill-session -t "$SESSION" 2>/dev/null; then
    echo "  killed: $SESSION"
  else
    echo "  (not running: $SESSION)"
  fi
done
pkill -9 -f "infer --serve" 2>/dev/null || true
pkill -9 -f "uvicorn server:app" 2>/dev/null || true
pkill -9 -f "telegram/bot.py" 2>/dev/null || true
sleep 2

# === 2. Start infer ===
echo ""
echo "[2/4] Starting infer (port 8000)..."
tmux new-session -d -s infer_serve \
  "ulimit -n 10240; \
   cd /Users/migi/.flashmoe/flash-moe/metal_infer && \
   ./infer --model /Users/migi/.flashmoe/model/Qwen3.5-397B-A17B-4bit \
   --serve 8000 \
   2>&1 | tee $LOG_DIR/infer_serve.log"

for i in 1 2 3 4 5 6 7 8; do
  sleep 5
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "  infer ready (${i}x5s)"
    break
  fi
  echo "  waiting infer... ${i}x5s"
done

# === 3. Start wrapper ===
echo ""
echo "[3/4] Starting wrapper (port 8771)..."
tmux new-session -d -s wrapper \
  "cd /Users/migi/.flashmoe/flash-moe/wrapper && \
   /Users/migi/flashmoe_venv/bin/uvicorn server:app \
   --host 127.0.0.1 --port 8771 \
   2>&1 | tee $LOG_DIR/wrapper.log"

sleep 5
if curl -sf http://localhost:8771/health >/dev/null 2>&1; then
  echo "  wrapper ready"
else
  echo "  ⚠ wrapper not responding"
fi

# === 4. Start telegram bot ===
echo ""
echo "[4/4] Starting telegram bot..."
tmux new-session -d -s telegram_bot \
  "/Users/migi/flashmoe_venv/bin/python /Users/migi/.flashmoe/telegram/bot.py \
   2>&1 | tee $LOG_DIR/telegram_bot.log"

sleep 3

# === Final status ===
echo ""
echo "=== Status ==="
tmux ls
echo ""
curl -sf http://localhost:8000/health && echo " <- infer"
curl -sf http://localhost:8771/health && echo " <- wrapper"
echo ""
echo "Telegram bot: tmux attach -t telegram_bot"
echo "All logs:     tail -f $LOG_DIR/*.log"
echo ""
echo "Ready ✓"
