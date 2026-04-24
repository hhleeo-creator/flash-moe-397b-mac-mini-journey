#!/bin/bash
# Full stack shutdown — bot → wrapper → infer (reverse of startup).

echo "=== Stopping Flash-MoE Full Stack ==="

for SESSION in telegram_bot wrapper infer_serve; do
  if tmux kill-session -t "$SESSION" 2>/dev/null; then
    echo "  killed: $SESSION"
  else
    echo "  (not running: $SESSION)"
  fi
done

sleep 2
pkill -9 -f "infer --serve" 2>/dev/null
pkill -9 -f "uvicorn server:app" 2>/dev/null
pkill -9 -f "telegram/bot.py" 2>/dev/null
sleep 1

echo ""
echo "=== Remaining processes (should be empty) ==="
pgrep -lf "infer --serve" || true
pgrep -lf "uvicorn server" || true
pgrep -lf "telegram/bot" || true
echo "(above should be empty = fully stopped)"
